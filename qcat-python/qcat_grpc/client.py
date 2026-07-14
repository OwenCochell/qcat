"""QickSocClient: a QickSoc proxy over a gRPC channel.

Drop-in replacement for the Pyro4 proxy from qick.pyro - existing programs
(AveragerProgram, QickProgramV2, ...) work unchanged:

    from qcat_grpc import make_proxy
    soc, soccfg = make_proxy("192.168.1.2", 8000)

Unlike the Pyro proxy, results are real local objects: no obtain() needed.
"""

import json
import queue
import threading
import time

import grpc
import numpy as np

from ._proto import (
    arm_ddr4_pb2,
    arm_mr_pb2,
    bootstrap_pb2_grpc,
    clear_ddr4_pb2,
    clear_tproc_counter_pb2,
    config_avg_pb2,
    config_buf_pb2,
    config_mux_gen_pb2,
    config_mux_readout_pb2,
    configure_readout_pb2,
    control_pb2_grpc,
    ddr4_buff_pb2,
    empty_pb2,
    enable_buf_pb2,
    freeze_adc_cals_pb2,
    get_adc_attenuator_pb2,
    get_tproc_counter_pb2,
    load_bin_frame_pb2,
    load_bin_pb2,
    load_data_frame_pb2,
    load_data_pb2,
    load_memory_frame_pb2,
    load_memory_pb2,
    load_pb2_grpc,
    memory_pb2,
    memory_type_pb2,
    mr_buff_pb2,
    pl_reset_pb2,
    poll_data_pb2,
    read_data_pb2,
    read_pb2_grpc,
    readout_pb2_grpc,
    set_adc_attenuator_pb2,
    set_iq_pb2,
    set_mixer_freq_pb2,
    set_nyquist_pb2,
    start_readout_pb2,
    start_src_pb2,
    stop_tproc_pb2,
    tproc_pb2_grpc,
    tproc_set_lfsr_cfg_pb2,
    tproc_single_read_pb2,
    tproc_single_write_pb2,
    unfreeze_adc_cals_pb2,
)
from .serialize import (
    array_to_def,
    buffer_to_array,
    bytes_to_chunks,
    decode_cfg,
    encode_dict,
    frames_to_array,
    str_to_memtype,
)

_EMPTY = empty_pb2.Empty()

# chunks are ~1 MiB; 8 MiB message caps give margin for readout DataPackets
GRPC_OPTIONS = [
    ("grpc.max_send_message_length", 8 << 20),
    ("grpc.max_receive_message_length", 8 << 20),
]

_START_SRC = {
    "internal": start_src_pb2.INTERNAL,
    "external": start_src_pb2.EXTERNAL,
}


def _normalize_memtype(mem_sel):
    """Accept 'pmem'/'dmem'/'wmem' or the tProc v2 raw ints (1/2/3, which match
    the MemoryType enum values)."""
    if isinstance(mem_sel, str):
        return str_to_memtype(mem_sel)
    return mem_sel


class _TprocClient:
    """The soc.tproc sub-object: unified surface over the v1 and v2 drivers.

    v1 calls look like single_read(addr) / single_write(addr=..., data=...);
    v2 calls look like single_read(mem_sel, addr) / single_write(mem_sel,
    addr=..., data=...). The server ignores mem_sel on v1 and defaults it to
    dmem on v2 when omitted.
    """

    def __init__(self, stub):
        self._stub = stub

    def start(self):
        self._stub.TprocStart(_EMPTY)

    def single_read(self, *args, mem_sel=None, addr=None):
        if len(args) == 2:
            mem_sel, addr = args
        elif len(args) == 1:
            if addr is None:
                addr = args[0]  # v1: single_read(addr)
            else:
                mem_sel = args[0]  # v2: single_read(mem_sel, addr=...)
        elif len(args) > 2:
            raise TypeError(f"expected at most 2 positional arguments, got {len(args)}")
        req = tproc_single_read_pb2.TprocSingleRead(address=addr or 0)
        if mem_sel is not None:
            req.memory = _normalize_memtype(mem_sel)
        return self._stub.TprocSingleRead(req).value

    def single_write(self, *args, mem_sel=None, addr=0, data=0):
        # positional args are v2 style: (mem_sel[, addr[, data]]);
        # v1 callers use keywords, as QickSoc itself does
        if len(args) > 3:
            raise TypeError(f"expected at most 3 positional arguments, got {len(args)}")
        if len(args) >= 1:
            mem_sel = args[0]
        if len(args) >= 2:
            addr = args[1]
        if len(args) == 3:
            data = args[2]
        req = tproc_single_write_pb2.TprocSingleWrite(address=addr, data=data)
        if mem_sel is not None:
            req.memory = _normalize_memtype(mem_sel)
        self._stub.TprocSingleWrite(req)

    def set_lfsr_cfg(self, mode, core=0):
        self._stub.TprocSetLfsrCfg(
            tproc_set_lfsr_cfg_pb2.TprocSetLfsrCfg(mode=mode, core=core))


class QickSocClient:
    """QickSoc-compatible proxy: exposes the QICK method names and calls the
    corresponding qcat RPCs. QickConfig compute methods stay client-side on the
    soccfg object; this class only carries the hardware calls."""

    def __init__(self, channel):
        self._channel = channel
        self._bootstrap = bootstrap_pb2_grpc.BootstrapStub(channel)
        self._load = load_pb2_grpc.LoadStub(channel)
        self._read = read_pb2_grpc.ReadStub(channel)
        self._control = control_pb2_grpc.ControlStub(channel)
        self._readout = readout_pb2_grpc.ReadoutStub(channel)
        self.tproc = _TprocClient(tproc_pb2_grpc.TprocStub(channel))

        # local mirror of the streamer state driving poll_data() semantics
        self._poll_call = None
        self._poll_thread = None
        self._poll_queue = queue.Queue()
        self._poll_error = None
        self._poll_done = threading.Event()
        self._poll_done.set()  # nothing in flight yet
        self._count = 0
        self._total_count = 0

    def close(self):
        self._stop_poll_stream()
        self._channel.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- bootstrap ----

    def get_cfg(self):
        reply = self._bootstrap.GetCfg(_EMPTY)
        return decode_cfg(reply.data, reply.encoding)

    def dump_cfg(self):
        return self._bootstrap.DumpCfg(_EMPTY).json

    # ---- loads (client-streaming) ----

    def load_bin_program(self, binprog, load_mem=True):
        def frames():
            yield load_bin_frame_pb2.LoadBinFrame(
                params=load_bin_pb2.LoadBin(load_mem=load_mem))
            if isinstance(binprog, dict):
                # tProc v2: one tagged int32 section per populated memory
                for mem_sel in ("pmem", "dmem", "wmem"):
                    if binprog.get(mem_sel) is None:
                        continue
                    arr = np.ascontiguousarray(binprog[mem_sel], dtype=np.int32)
                    yield from self._bin_section(str_to_memtype(mem_sel), arr)
            else:
                # tProc v1: a single untagged uint64 array
                arr = np.ascontiguousarray(binprog, dtype=np.uint64)
                yield from self._bin_section(memory_type_pb2.MEMORY_TYPE_UNSPECIFIED, arr)
        self._load.LoadBinProgram(frames())

    @staticmethod
    def _bin_section(memory, arr):
        yield load_bin_frame_pb2.LoadBinFrame(
            section=load_bin_frame_pb2.LoadBinFrame.Section(
                memory=memory, **{"def": array_to_def(arr)}))
        for chunk in bytes_to_chunks(arr.tobytes()):
            yield load_bin_frame_pb2.LoadBinFrame(chunk=chunk)

    def reload_mem(self):
        self._load.ReloadMem(_EMPTY)

    def load_mem(self, data, mem_sel="dmem", addr=0):
        arr = np.ascontiguousarray(data, dtype=np.int32)
        params = load_memory_pb2.LoadMemory(memory=str_to_memtype(mem_sel), address=addr)
        self._load.LoadMem(self._data_frames(load_memory_frame_pb2.LoadMemoryFrame, params, arr))

    def load_envelope(self, ch, data, addr):
        arr = np.ascontiguousarray(data, dtype=np.int16)
        params = load_data_pb2.LoadData(channel=ch, address=addr)
        self._load.LoadEnvelope(self._data_frames(load_data_frame_pb2.LoadDataFrame, params, arr))

    def load_weights(self, ch, data, addr=0):
        arr = np.ascontiguousarray(data, dtype=np.int16)
        params = load_data_pb2.LoadData(channel=ch, address=addr)
        self._load.LoadWeights(self._data_frames(load_data_frame_pb2.LoadDataFrame, params, arr))

    @staticmethod
    def _data_frames(frame_cls, params, arr):
        yield frame_cls(params=params)
        yield frame_cls(**{"def": array_to_def(arr)})
        for chunk in bytes_to_chunks(arr.tobytes()):
            yield frame_cls(chunk=chunk)

    # ---- bulk reads (server-streaming) ----

    def get_decimated(self, ch, address=0, length=None):
        req = read_data_pb2.ReadData(channel=ch, address=address)
        if length is not None:
            req.length = length
        return frames_to_array(self._read.GetDecimated(req))

    def get_accumulated(self, ch, address=0, length=None):
        req = read_data_pb2.ReadData(channel=ch, address=address)
        if length is not None:
            req.length = length
        return frames_to_array(self._read.GetAccumulated(req))

    def get_ddr4(self, nt, start=None):
        req = ddr4_buff_pb2.DDR4Buff(num_trans=nt)
        if start is not None:
            req.start = start
        return frames_to_array(self._read.GetDdr4(req))

    def get_mr(self, start=None):
        req = mr_buff_pb2.MRBuff()
        if start is not None:
            req.start = start
        return frames_to_array(self._read.GetMr(req))

    def read_mem(self, length, mem_sel="dmem", addr=0):
        req = memory_pb2.ReadMemory(
            memory=str_to_memtype(mem_sel), length=length, address=addr)
        return frames_to_array(self._read.ReadMem(req))

    # ---- control ----

    def set_nyquist(self, ch, nqz, force=False):
        self._control.SetNyquist(set_nyquist_pb2.SetNyquist(channel=ch, nqz=nqz, force=force))

    def set_mixer_freq(self, ch, f, ro_ch=None, phase_reset=True):
        req = set_mixer_freq_pb2.SetMixerFreq(channel=ch, freq=f, phase_reset=phase_reset)
        if ro_ch is not None:
            req.ro_ch = ro_ch
        self._control.SetMixerFreq(req)

    def config_mux_gen(self, ch, tones):
        self._control.ConfigMuxGen(
            config_mux_gen_pb2.ConfigMuxGen(channel=ch, tones=encode_dict(tones)))

    def set_iq(self, ch, f, i, q, ro_ch=None, phase_reset=True):
        req = set_iq_pb2.SetIQ(channel=ch, freq=f, i=i, q=q, phase_reset=phase_reset)
        if ro_ch is not None:
            req.ro_ch = ro_ch
        self._control.SetIQ(req)

    def reset_gens(self):
        self._control.ResetGens(_EMPTY)

    def configure_readout(self, ch, ro_regs):
        self._control.ConfigureReadout(
            configure_readout_pb2.ConfigureReadout(channel=ch, ro_regs=encode_dict(ro_regs)))

    def config_mux_readout(self, pfbpath, cfgs, sel=None):
        req = config_mux_readout_pb2.ConfigMuxReadout(pfbpath=pfbpath, cfgs=encode_dict(cfgs))
        if sel is not None:
            req.sel = sel
        self._control.ConfigMuxReadout(req)

    def config_avg(self, ch, address=0, length=1,
                   edge_counting=False, high_threshold=1000, low_threshold=0):
        self._control.ConfigAvg(config_avg_pb2.ConfigAvg(
            channel=ch, address=address, length=length, edge_counting=edge_counting,
            high_threshold=high_threshold, low_threshold=low_threshold))

    def config_buf(self, ch, address=0, length=1):
        self._control.ConfigBuf(
            config_buf_pb2.ConfigBuf(channel=ch, address=address, length=length))

    def enable_buf(self, ch, enable_avg=True, enable_buf=True):
        self._control.EnableBuf(enable_buf_pb2.EnableBuf(
            channel=ch, enable_avg=enable_avg, enable_buf=enable_buf))

    def start_src(self, src):
        self._control.StartSrc(start_src_pb2.StartSrc(src=_START_SRC[src]))

    def start_tproc(self):
        self._control.StartTproc(_EMPTY)

    def stop_tproc(self, lazy=False):
        self._control.StopTproc(stop_tproc_pb2.StopTproc(lazy=lazy))

    def prepare_round(self):
        self._control.PrepareRound(_EMPTY)

    def cleanup_round(self):
        self._control.CleanupRound(_EMPTY)

    def clear_tproc_counter(self, addr):
        self._control.ClearTprocCounter(
            clear_tproc_counter_pb2.ClearTprocCounter(address=addr))

    def get_tproc_counter(self, addr):
        return self._control.GetTprocCounter(
            get_tproc_counter_pb2.GetTprocCounter(address=addr)).value

    def set_adc_attenuator(self, blockname, attenuation):
        return self._control.SetAdcAttenuator(set_adc_attenuator_pb2.SetAdcAttenuator(
            blockname=blockname, attenuation=attenuation)).value

    def get_adc_attenuator(self, blockname):
        return self._control.GetAdcAttenuator(
            get_adc_attenuator_pb2.GetAdcAttenuator(blockname=blockname)).value

    def freeze_adc_cals(self, blocknames):
        self._control.FreezeAdcCals(
            freeze_adc_cals_pb2.FreezeAdcCals(blocknames=list(blocknames)))

    def unfreeze_adc_cals(self, blocknames):
        self._control.UnfreezeAdcCals(
            unfreeze_adc_cals_pb2.UnfreezeAdcCals(blocknames=list(blocknames)))

    def clocks_locked(self):
        return self._control.ClocksLocked(_EMPTY).value

    def get_sample_rates(self):
        return json.loads(self._control.GetSampleRates(_EMPTY).json)

    def pl_reset(self, reinit=True):
        self._control.PlReset(pl_reset_pb2.PlReset(reinit=reinit))

    def clear_ddr4(self, length=None):
        req = clear_ddr4_pb2.ClearDdr4()
        if length is not None:
            req.length = length
        self._control.ClearDdr4(req)

    def arm_ddr4(self, ch, nt, force_overwrite=False):
        self._control.ArmDdr4(arm_ddr4_pb2.ArmDdr4(
            channel=ch, num_trans=nt, force_overwrite=force_overwrite))

    def arm_mr(self, ch):
        self._control.ArmMr(arm_mr_pb2.ArmMr(channel=ch))

    # ---- streaming readout ----

    def start_readout(self, total_shots, counter_addr=1, ch_list=None,
                      reads_per_shot=1, stride=None):
        """Arm the server-side readout worker and open the PollData stream that
        feeds the local packet queue drained by poll_data()."""
        self._stop_poll_stream()

        req = start_readout_pb2.StartReadout(
            total_shots=total_shots, counter_addr=counter_addr)
        if ch_list is not None:
            req.ch_list.extend(ch_list)
        if isinstance(reads_per_shot, int):
            req.reads_per_shot.append(reads_per_shot)  # single value broadcasts
        else:
            req.reads_per_shot.extend(reads_per_shot)
        if stride is not None:
            req.stride = stride
        self._readout.StartReadout(req)

        self._total_count = total_shots
        self._count = 0
        self._poll_queue = queue.Queue()
        self._poll_error = None
        self._poll_done.clear()
        self._poll_call = self._readout.PollData(poll_data_pb2.PollData(totaltime=0.1))
        self._poll_thread = threading.Thread(
            target=self._poll_reader, args=(self._poll_call, self._poll_queue), daemon=True)
        self._poll_thread.start()

    def poll_data(self, totaltime=0.1, timeout=None):
        """Drain the local packet queue with the same semantics as
        QickSoc.poll_data: stop on total_count reached, totaltime elapsed, or
        queue timeout; totaltime<0 reads until timeout. Returns a list of
        (length, (acc_buf, stats)) pairs, oldest first."""
        time_end = time.time() + totaltime
        new_data = []
        while (totaltime < 0) or (self._count < self._total_count and time.time() < time_end):
            if self._poll_error is not None:
                error, self._poll_error = self._poll_error, None
                raise RuntimeError("exception in readout stream") from error
            if self._poll_done.is_set() and self._poll_queue.empty():
                break
            try:
                length, data = self._poll_queue.get(block=True, timeout=timeout)
            except queue.Empty:
                break
            if data is None:  # end-of-stream sentinel
                break
            self._count += length
            new_data.append((length, data))
        return new_data

    def _poll_reader(self, call, out_queue):
        """Background thread: unpack the DataPacket stream into the local queue
        as (length, (acc_buf, stats)) entries matching the streamer's format."""
        try:
            for packet in call:
                acc_buf = [buffer_to_array(getattr(cd, "def"), cd.data) for cd in packet.data]
                stats = (packet.stats.elapsed, packet.stats.shots,
                         packet.stats.addr, packet.stats.new_shots)
                out_queue.put((packet.stats.new_shots, (acc_buf, stats)))
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                self._poll_error = e
        finally:
            self._poll_done.set()
            out_queue.put((0, None))

    def _stop_poll_stream(self):
        if self._poll_call is not None:
            self._poll_call.cancel()
            self._poll_call = None
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=2)
            self._poll_thread = None


def make_proxy(addr, port=8000, channel_credentials=None):
    """Connect to a qcat gRPC server and return (soc, soccfg), mirroring
    qick.pyro.make_proxy so demos/programs swap transports with one line.

    Parameters
    ----------
    addr : str
        hostname or IP address of the board
    port : int
        the port the server was started on
    channel_credentials : grpc.ChannelCredentials
        TLS credentials (e.g. grpc.ssl_channel_credentials()); None = plaintext

    Returns
    -------
    QickSocClient
        proxy to the QickSoc - this is usually called "soc" in demos
    QickConfig
        config object - this is usually called "soccfg" in demos
    """
    from qick.qick_asm import QickConfig

    target = f"{addr}:{port}"
    if channel_credentials is not None:
        channel = grpc.secure_channel(target, channel_credentials, options=GRPC_OPTIONS)
    else:
        channel = grpc.insecure_channel(target, options=GRPC_OPTIONS)
    soc = QickSocClient(channel)
    soccfg = QickConfig(soc.get_cfg())
    return soc, soccfg
