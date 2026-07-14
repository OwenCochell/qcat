"""Servicer tests against a FakeSoc: argument mapping (optional defaults,
enum -> str), stream framing/reassembly, and version dispatch. No sockets."""

import json

import grpc
import numpy as np
import pytest

from conftest import FakeAbort, FakeContext, FakeSoc, make_poll_batch
from qcat_grpc import serialize
from qcat_grpc._proto import (
    arm_ddr4_pb2,
    arm_mr_pb2,
    clear_tproc_counter_pb2,
    config_avg_pb2,
    config_buf_pb2,
    config_mux_gen_pb2,
    config_mux_readout_pb2,
    configure_readout_pb2,
    ddr4_buff_pb2,
    empty_pb2,
    enable_buf_pb2,
    freeze_adc_cals_pb2,
    get_adc_attenuator_pb2,
    load_bin_frame_pb2,
    load_bin_pb2,
    load_data_frame_pb2,
    load_data_pb2,
    load_memory_frame_pb2,
    load_memory_pb2,
    memory_pb2,
    memory_type_pb2,
    pl_reset_pb2,
    poll_data_pb2,
    read_data_pb2,
    set_iq_pb2,
    set_mixer_freq_pb2,
    set_nyquist_pb2,
    start_readout_pb2,
    start_src_pb2,
    stop_tproc_pb2,
    tproc_set_lfsr_cfg_pb2,
    tproc_single_read_pb2,
    tproc_single_write_pb2,
    unfreeze_adc_cals_pb2,
)
from qcat_grpc.servicers import (
    BootstrapServicer,
    ControlServicer,
    LoadServicer,
    ReadServicer,
    ReadoutServicer,
    TprocServicer,
)

EMPTY = empty_pb2.Empty()


# --------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------

def test_get_cfg(soc, context):
    reply = BootstrapServicer(soc).GetCfg(EMPTY, context)
    assert serialize.decode_cfg(reply.data, reply.encoding) == soc.get_cfg()


def test_dump_cfg(soc, context):
    reply = BootstrapServicer(soc).DumpCfg(EMPTY, context)
    assert json.loads(reply.json) == soc.get_cfg()


# --------------------------------------------------------------------------
# Control: optional-field defaults, enum mapping, dict decoding
# --------------------------------------------------------------------------

def test_set_mixer_freq_defaults(soc, context):
    req = set_mixer_freq_pb2.SetMixerFreq(channel=2, freq=500.0)
    ControlServicer(soc).SetMixerFreq(req, context)
    assert soc.last("set_mixer_freq") == ("set_mixer_freq", 2, 500.0, None, True)


def test_set_mixer_freq_explicit(soc, context):
    req = set_mixer_freq_pb2.SetMixerFreq(channel=2, freq=500.0, ro_ch=0, phase_reset=False)
    ControlServicer(soc).SetMixerFreq(req, context)
    assert soc.last("set_mixer_freq") == ("set_mixer_freq", 2, 500.0, 0, False)


def test_config_avg_defaults(soc, context):
    req = config_avg_pb2.ConfigAvg(channel=1, address=16)
    ControlServicer(soc).ConfigAvg(req, context)
    assert soc.last("config_avg") == ("config_avg", 1, 16, 1, False, 1000, 0)


def test_enable_buf_explicit_false(soc, context):
    req = enable_buf_pb2.EnableBuf(channel=0, enable_avg=False)
    ControlServicer(soc).EnableBuf(req, context)
    assert soc.last("enable_buf") == ("enable_buf", 0, False, True)


def test_start_src_enum_mapping(soc, context):
    servicer = ControlServicer(soc)
    servicer.StartSrc(start_src_pb2.StartSrc(src=start_src_pb2.INTERNAL), context)
    assert soc.last("start_src") == ("start_src", "internal")
    servicer.StartSrc(start_src_pb2.StartSrc(src=start_src_pb2.EXTERNAL), context)
    assert soc.last("start_src") == ("start_src", "external")


def test_config_mux_gen_decodes_tones(soc, context):
    tones = [{"freq_int": 123, "gain_int": 32000}]
    req = config_mux_gen_pb2.ConfigMuxGen(channel=4, tones=serialize.encode_dict(tones))
    ControlServicer(soc).ConfigMuxGen(req, context)
    assert soc.last("config_mux_gen") == ("config_mux_gen", 4, tones)


def test_config_mux_readout_sel_default(soc, context):
    req = config_mux_readout_pb2.ConfigMuxReadout(
        pfbpath="blk/pfb_0", cfgs=serialize.encode_dict([{"f_int": 1}]))
    ControlServicer(soc).ConfigMuxReadout(req, context)
    assert soc.last("config_mux_readout") == ("config_mux_readout", "blk/pfb_0", [{"f_int": 1}], None)


def test_scalar_replies(soc, context):
    servicer = ControlServicer(soc)
    assert servicer.ClocksLocked(EMPTY, context).value is True
    assert json.loads(servicer.GetSampleRates(EMPTY, context).json) == {
        "dac": {"0": 9830.4}, "adc": {"2": 4915.2}}


def test_exception_becomes_internal_abort(context):
    soc = FakeSoc()
    soc.reset_gens = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(FakeAbort):
        ControlServicer(soc).ResetGens(EMPTY, context)
    assert context.abort_code == grpc.StatusCode.INTERNAL
    assert "boom" in context.abort_details


def test_set_nyquist(soc, context):
    ControlServicer(soc).SetNyquist(set_nyquist_pb2.SetNyquist(channel=1, nqz=2, force=True), context)
    assert soc.last("set_nyquist") == ("set_nyquist", 1, 2, True)


def test_set_iq_defaults(soc, context):
    req = set_iq_pb2.SetIQ(channel=0, freq=100.0, i=0.5, q=-0.5)
    ControlServicer(soc).SetIQ(req, context)
    assert soc.last("set_iq") == ("set_iq", 0, 100.0, 0.5, -0.5, None, True)


def test_reset_gens(soc, context):
    ControlServicer(soc).ResetGens(EMPTY, context)
    assert soc.last("reset_gens") == ("reset_gens",)


def test_configure_readout(soc, context):
    req = configure_readout_pb2.ConfigureReadout(channel=2, ro_regs=serialize.encode_dict({"r": 1}))
    ControlServicer(soc).ConfigureReadout(req, context)
    assert soc.last("configure_readout") == ("configure_readout", 2, {"r": 1})


def test_config_buf_default_length(soc, context):
    ControlServicer(soc).ConfigBuf(config_buf_pb2.ConfigBuf(channel=1, address=8), context)
    assert soc.last("config_buf") == ("config_buf", 1, 8, 1)  # length unset => 1


def test_start_stop_prepare_cleanup_tproc(soc, context):
    servicer = ControlServicer(soc)
    servicer.StartTproc(EMPTY, context)
    assert soc.last("start_tproc") == ("start_tproc",)
    servicer.StopTproc(stop_tproc_pb2.StopTproc(lazy=True), context)
    assert soc.last("stop_tproc") == ("stop_tproc", True)
    servicer.PrepareRound(EMPTY, context)
    assert soc.last("prepare_round") == ("prepare_round",)
    servicer.CleanupRound(EMPTY, context)
    assert soc.last("cleanup_round") == ("cleanup_round",)


def test_clear_tproc_counter(soc, context):
    ControlServicer(soc).ClearTprocCounter(clear_tproc_counter_pb2.ClearTprocCounter(address=3), context)
    assert soc.last("clear_tproc_counter") == ("clear_tproc_counter", 3)


def test_get_adc_attenuator(soc, context):
    reply = ControlServicer(soc).GetAdcAttenuator(
        get_adc_attenuator_pb2.GetAdcAttenuator(blockname="21"), context)
    assert reply.value == 5.0


def test_freeze_unfreeze_adc_cals(soc, context):
    servicer = ControlServicer(soc)
    servicer.FreezeAdcCals(freeze_adc_cals_pb2.FreezeAdcCals(blocknames=["a", "b"]), context)
    assert soc.last("freeze_adc_cals") == ("freeze_adc_cals", ["a", "b"])
    servicer.UnfreezeAdcCals(unfreeze_adc_cals_pb2.UnfreezeAdcCals(blocknames=["c"]), context)
    assert soc.last("unfreeze_adc_cals") == ("unfreeze_adc_cals", ["c"])


def test_pl_reset_default_reinit(soc, context):
    ControlServicer(soc).PlReset(pl_reset_pb2.PlReset(), context)
    assert soc.last("pl_reset") == ("pl_reset", True)  # reinit unset => True


def test_arm_ddr4_and_mr(soc, context):
    servicer = ControlServicer(soc)
    servicer.ArmDdr4(arm_ddr4_pb2.ArmDdr4(channel=1, num_trans=4, force_overwrite=True), context)
    assert soc.last("arm_ddr4") == ("arm_ddr4", 1, 4, True)
    servicer.ArmMr(arm_mr_pb2.ArmMr(channel=2), context)
    assert soc.last("arm_mr") == ("arm_mr", 2)


# --------------------------------------------------------------------------
# Read: server-streaming framing
# --------------------------------------------------------------------------

def test_get_decimated_framing(soc, context):
    req = read_data_pb2.ReadData(channel=0, address=32, length=100)
    frames = ReadServicer(soc).GetDecimated(req, context)
    out = serialize.frames_to_array(frames)
    assert soc.last("get_decimated") == ("get_decimated", 0, 32, 100)
    assert out.dtype == np.int16 and out.shape == (100, 2)


def test_get_decimated_length_unset_means_none(soc, context):
    frames = ReadServicer(soc).GetDecimated(read_data_pb2.ReadData(channel=1), context)
    serialize.frames_to_array(frames)
    assert soc.last("get_decimated") == ("get_decimated", 1, 0, None)


def test_get_accumulated_int64(soc, context):
    req = read_data_pb2.ReadData(channel=0, length=8)
    out = serialize.frames_to_array(ReadServicer(soc).GetAccumulated(req, context))
    assert out.dtype == np.int64 and out.shape == (8, 2)


def test_get_ddr4_optional_start(soc, context):
    out = serialize.frames_to_array(
        ReadServicer(soc).GetDdr4(ddr4_buff_pb2.DDR4Buff(num_trans=2), context))
    assert soc.last("get_ddr4") == ("get_ddr4", 2, None)
    assert out.shape == (256, 2)


def test_read_mem_enum_default_and_shape(soc, context):
    # unset memory (UNSPECIFIED) => API default 'dmem'
    out = serialize.frames_to_array(
        ReadServicer(soc).ReadMem(memory_pb2.ReadMemory(length=16), context))
    assert soc.last("read_mem") == ("read_mem", 16, "dmem", 0)
    assert out.shape == (16,)
    # pmem keeps its (n, 8) shape across the wire
    out = serialize.frames_to_array(ReadServicer(soc).ReadMem(
        memory_pb2.ReadMemory(memory=memory_type_pb2.PMEM, length=4, address=2), context))
    assert soc.last("read_mem") == ("read_mem", 4, "pmem", 2)
    assert out.shape == (4, 8)


# --------------------------------------------------------------------------
# Load: client-streaming reassembly
# --------------------------------------------------------------------------

def _data_stream(frame_cls, params, arr, chunk_bytes=64):
    yield frame_cls(params=params)
    yield frame_cls(**{"def": serialize.array_to_def(arr)})
    for chunk in serialize.bytes_to_chunks(arr.tobytes(), chunk_bytes):
        yield frame_cls(chunk=chunk)


def test_load_bin_program_v1(soc, context):
    binprog = np.arange(1000, dtype=np.uint64)

    def frames():
        yield load_bin_frame_pb2.LoadBinFrame(params=load_bin_pb2.LoadBin())
        yield load_bin_frame_pb2.LoadBinFrame(
            section=load_bin_frame_pb2.LoadBinFrame.Section(
                memory=memory_type_pb2.MEMORY_TYPE_UNSPECIFIED,
                **{"def": serialize.array_to_def(binprog)}))
        for chunk in serialize.bytes_to_chunks(binprog.tobytes(), 512):
            yield load_bin_frame_pb2.LoadBinFrame(chunk=chunk)

    LoadServicer(soc).LoadBinProgram(frames(), context)
    _, got, load_mem = soc.last("load_bin_program")
    assert load_mem is True  # unset => API default
    assert isinstance(got, np.ndarray) and got.dtype == np.uint64
    np.testing.assert_array_equal(got, binprog)


def test_load_bin_program_v2(context):
    soc = FakeSoc(tproc_version=2)
    prog = {
        "pmem": np.arange(64, dtype=np.int32).reshape(-1, 8),
        "wmem": np.arange(32, dtype=np.int32).reshape(-1, 8),
    }

    def frames():
        yield load_bin_frame_pb2.LoadBinFrame(
            params=load_bin_pb2.LoadBin(load_mem=False))
        for name, memtype in (("pmem", memory_type_pb2.PMEM), ("wmem", memory_type_pb2.WMEM)):
            arr = prog[name]
            yield load_bin_frame_pb2.LoadBinFrame(
                section=load_bin_frame_pb2.LoadBinFrame.Section(
                    memory=memtype, **{"def": serialize.array_to_def(arr)}))
            for chunk in serialize.bytes_to_chunks(arr.tobytes(), 100):
                yield load_bin_frame_pb2.LoadBinFrame(chunk=chunk)

    LoadServicer(soc).LoadBinProgram(frames(), context)
    _, got, load_mem = soc.last("load_bin_program")
    assert load_mem is False
    assert isinstance(got, dict)
    np.testing.assert_array_equal(got["pmem"], prog["pmem"])
    np.testing.assert_array_equal(got["wmem"], prog["wmem"])
    assert got["dmem"] is None


def test_load_mem_enum_default(soc, context):
    data = np.arange(300, dtype=np.int32)
    params = load_memory_pb2.LoadMemory(address=8)  # memory unset => dmem
    LoadServicer(soc).LoadMem(_data_stream(load_memory_frame_pb2.LoadMemoryFrame, params, data), context)
    _, got, mem_sel, addr = soc.last("load_mem")
    np.testing.assert_array_equal(got, data)
    assert (mem_sel, addr) == ("dmem", 8)


def test_load_envelope_and_weights(soc, context):
    env = np.arange(512, dtype=np.int16).reshape(-1, 2)
    params = load_data_pb2.LoadData(channel=3, address=128)
    LoadServicer(soc).LoadEnvelope(
        _data_stream(load_data_frame_pb2.LoadDataFrame, params, env), context)
    _, ch, got, addr = soc.last("load_envelope")
    assert (ch, addr) == (3, 128)
    np.testing.assert_array_equal(got, env)

    LoadServicer(soc).LoadWeights(
        _data_stream(load_data_frame_pb2.LoadDataFrame, params, env), context)
    _, ch, got, addr = soc.last("load_weights")
    assert (ch, addr) == (3, 128)
    np.testing.assert_array_equal(got, env)


def test_reload_mem(soc, context):
    LoadServicer(soc).ReloadMem(EMPTY, context)
    assert soc.last("reload_mem") == ("reload_mem",)


# ---- Load: malformed client streams abort INTERNAL ----

def test_load_mem_missing_params_aborts(soc, context):
    arr = np.arange(10, dtype=np.int32)

    def frames():  # def + chunks but no params frame
        yield load_memory_frame_pb2.LoadMemoryFrame(**{"def": serialize.array_to_def(arr)})
        for chunk in serialize.bytes_to_chunks(arr.tobytes(), 16):
            yield load_memory_frame_pb2.LoadMemoryFrame(chunk=chunk)

    with pytest.raises(FakeAbort):
        LoadServicer(soc).LoadMem(frames(), context)
    assert context.abort_code == grpc.StatusCode.INTERNAL
    assert "missing params" in context.abort_details


def test_load_mem_out_of_order_chunk_aborts(soc, context):
    arr = np.arange(10, dtype=np.int32)

    def frames():
        yield load_memory_frame_pb2.LoadMemoryFrame(params=load_memory_pb2.LoadMemory())
        yield load_memory_frame_pb2.LoadMemoryFrame(**{"def": serialize.array_to_def(arr)})
        yield load_memory_frame_pb2.LoadMemoryFrame(
            chunk=serialize.array_chunk_pb2.ArrayChunk(data=arr.tobytes(), offset=8))

    with pytest.raises(FakeAbort):
        LoadServicer(soc).LoadMem(frames(), context)
    assert "out of order" in context.abort_details


def test_load_mem_empty_body_frame_aborts(soc, context):
    def frames():
        yield load_memory_frame_pb2.LoadMemoryFrame(params=load_memory_pb2.LoadMemory())
        yield load_memory_frame_pb2.LoadMemoryFrame()  # no body oneof set

    with pytest.raises(FakeAbort):
        LoadServicer(soc).LoadMem(frames(), context)
    assert "no body" in context.abort_details


def test_load_bin_program_empty_body_frame_aborts(soc, context):
    def frames():
        yield load_bin_frame_pb2.LoadBinFrame(params=load_bin_pb2.LoadBin())
        yield load_bin_frame_pb2.LoadBinFrame()  # no body oneof set

    with pytest.raises(FakeAbort):
        LoadServicer(soc).LoadBinProgram(frames(), context)
    assert "no body" in context.abort_details


def test_load_bin_program_chunk_before_section_aborts(soc, context):
    def frames():
        yield load_bin_frame_pb2.LoadBinFrame(params=load_bin_pb2.LoadBin())
        yield load_bin_frame_pb2.LoadBinFrame(
            chunk=serialize.array_chunk_pb2.ArrayChunk(data=b"\x00\x00\x00\x00", offset=0))

    with pytest.raises(FakeAbort):
        LoadServicer(soc).LoadBinProgram(frames(), context)
    assert "chunk before any section" in context.abort_details


def test_load_bin_program_no_sections_aborts(soc, context):
    def frames():
        yield load_bin_frame_pb2.LoadBinFrame(params=load_bin_pb2.LoadBin())

    with pytest.raises(FakeAbort):
        LoadServicer(soc).LoadBinProgram(frames(), context)
    assert "missing params or sections" in context.abort_details


def test_load_bin_program_unspecified_mixed_with_tagged_aborts(soc, context):
    a = np.arange(8, dtype=np.int32)
    b = np.arange(8, dtype=np.int32)

    def section(memory, arr):
        yield load_bin_frame_pb2.LoadBinFrame(
            section=load_bin_frame_pb2.LoadBinFrame.Section(
                memory=memory, **{"def": serialize.array_to_def(arr)}))
        yield load_bin_frame_pb2.LoadBinFrame(chunk=serialize.array_chunk_pb2.ArrayChunk(data=arr.tobytes()))

    def frames():
        yield load_bin_frame_pb2.LoadBinFrame(params=load_bin_pb2.LoadBin())
        yield from section(memory_type_pb2.PMEM, a)
        yield from section(memory_type_pb2.MEMORY_TYPE_UNSPECIFIED, b)

    with pytest.raises(FakeAbort):
        LoadServicer(soc).LoadBinProgram(frames(), context)
    assert "UNSPECIFIED section mixed" in context.abort_details


# --------------------------------------------------------------------------
# Readout
# --------------------------------------------------------------------------

def test_start_readout_defaults(soc, context):
    ReadoutServicer(soc).StartReadout(start_readout_pb2.StartReadout(total_shots=100), context)
    assert soc.last("start_readout") == ("start_readout", 100, 1, None, 1, None)


def test_start_readout_explicit(soc, context):
    req = start_readout_pb2.StartReadout(
        total_shots=500, counter_addr=2, ch_list=[0, 2, 3],
        reads_per_shot=[1, 2, 1], stride=50)
    ReadoutServicer(soc).StartReadout(req, context)
    assert soc.last("start_readout") == ("start_readout", 500, 2, [0, 2, 3], [1, 2, 1], 50)


def test_start_readout_single_reads_per_shot_broadcasts(soc, context):
    req = start_readout_pb2.StartReadout(total_shots=10, ch_list=[0, 1], reads_per_shot=[3])
    ReadoutServicer(soc).StartReadout(req, context)
    assert soc.last("start_readout")[4] == 3  # int, so start_readout broadcasts it


def test_poll_data_streams_until_complete(soc, context):
    soc.start_readout(10)
    soc.poll_batches = [[make_poll_batch(4, nchan=2)], [], [make_poll_batch(6, nchan=2)]]
    packets = list(ReadoutServicer(soc).PollData(poll_data_pb2.PollData(), context))
    assert len(packets) == 2
    assert [p.stats.new_shots for p in packets] == [4, 6]
    assert len(packets[0].data) == 2
    arr = serialize.buffer_to_array(
        serialize.get_def(packets[0].data[1]), packets[0].data[1].data)
    np.testing.assert_array_equal(arr, np.arange(8, dtype=np.int64).reshape(-1, 2) + 1)
    assert packets[1].stats.shots == 6 and packets[1].stats.elapsed == 0.5


# --------------------------------------------------------------------------
# Tproc: version dispatch
# --------------------------------------------------------------------------

def test_tproc_v1_read_write(soc, context):
    servicer = TprocServicer(soc)
    servicer.TprocStart(EMPTY, context)
    assert soc.calls[-1] == ("tproc.start",)
    reply = servicer.TprocSingleRead(tproc_single_read_pb2.TprocSingleRead(address=5), context)
    assert reply.value == 7
    assert soc.calls[-1] == ("tproc.single_read", 5)  # v1: no mem_sel
    servicer.TprocSingleWrite(
        tproc_single_write_pb2.TprocSingleWrite(address=6, data=99), context)
    assert soc.calls[-1] == ("tproc.single_write", 6, 99)


def test_tproc_v2_read_write(soc_v2, context):
    servicer = TprocServicer(soc_v2)
    reply = servicer.TprocSingleRead(tproc_single_read_pb2.TprocSingleRead(
        memory=memory_type_pb2.WMEM, address=5), context)
    assert reply.value == 9
    assert soc_v2.calls[-1] == ("tproc.single_read", 3, 5)  # wmem => mem_sel 3
    # memory unset => dmem (mem_sel 2)
    servicer.TprocSingleRead(tproc_single_read_pb2.TprocSingleRead(address=1), context)
    assert soc_v2.calls[-1] == ("tproc.single_read", 2, 1)
    servicer.TprocSingleWrite(tproc_single_write_pb2.TprocSingleWrite(
        memory=memory_type_pb2.PMEM, address=6, data=99), context)
    assert soc_v2.calls[-1] == ("tproc.single_write", 1, 6, 99)


def test_tproc_v2_broken_single_access_aborts_unimplemented(context):
    soc = FakeSoc(tproc_version=2, broken_single_access=True)
    with pytest.raises(FakeAbort):
        TprocServicer(soc).TprocSingleRead(
            tproc_single_read_pb2.TprocSingleRead(address=1), context)
    assert context.abort_code == grpc.StatusCode.UNIMPLEMENTED
    assert "Do not use" in context.abort_details


def test_set_lfsr_cfg_v2_only(soc, soc_v2, context):
    req = tproc_set_lfsr_cfg_pb2.TprocSetLfsrCfg(
        mode=tproc_set_lfsr_cfg_pb2.LFSR_FREE_RUNNING, core=1)
    TprocServicer(soc_v2).TprocSetLfsrCfg(req, context)
    assert soc_v2.calls[-1] == ("tproc.set_lfsr_cfg", 1, 1)
    with pytest.raises(FakeAbort):
        TprocServicer(soc).TprocSetLfsrCfg(req, FakeContext())