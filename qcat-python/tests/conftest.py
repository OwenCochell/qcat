"""Shared test fixtures: a FakeSoc that records calls and returns canned data,
and a fake ServicerContext for calling servicer methods directly."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import grpc
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeAbort(grpc.RpcError):
    def __init__(self, code, details):
        super().__init__(details)
        self.code = code
        self.details = details


class FakeContext:
    """Minimal ServicerContext stand-in for direct servicer calls."""

    def __init__(self):
        self.abort_code = None
        self.abort_details = None

    def abort(self, code, details):
        self.abort_code = code
        self.abort_details = details
        raise FakeAbort(code, details)

    def is_active(self):
        return True


class FakeTprocV1:
    def __init__(self, log):
        self._log = log

    def start(self):
        self._log.append(("tproc.start",))

    def single_read(self, addr):
        self._log.append(("tproc.single_read", addr))
        return 7

    def single_write(self, addr=0, data=0):
        self._log.append(("tproc.single_write", addr, data))


class FakeTprocV2:
    def __init__(self, log, broken_single_access=False):
        self._log = log
        self._broken = broken_single_access

    def start(self):
        self._log.append(("tproc.start",))

    def single_read(self, mem_sel, addr):
        if self._broken:
            raise NameError("name 'i' is not defined")
        self._log.append(("tproc.single_read", mem_sel, addr))
        return 9

    def single_write(self, mem_sel, addr=0, data=0):
        if self._broken:
            raise NameError("name 'i' is not defined")
        self._log.append(("tproc.single_write", mem_sel, addr, data))

    def set_lfsr_cfg(self, mode, core=0):
        self._log.append(("tproc.set_lfsr_cfg", mode, core))


class FakeSoc:
    """Mock QickSoc: records every call in .calls and returns canned arrays."""

    def __init__(self, tproc_version=1, broken_single_access=False):
        self.calls = []
        self.TPROC_VERSION = tproc_version
        if tproc_version == 1:
            self.tproc = FakeTprocV1(self.calls)
        else:
            self.tproc = FakeTprocV2(self.calls, broken_single_access)
        self._cfg = {"board": "fake", "sf": 9.8, "readouts": [{"avg_maxlen": 1024}]}
        self.streamer = SimpleNamespace(count=0, total_count=0)
        # scripted poll_data return batches: list of lists of (length, (acc_buf, stats))
        self.poll_batches = []

    def _rec(self, *entry):
        self.calls.append(entry)

    def last(self, name):
        matches = [c for c in self.calls if c[0] == name]
        assert matches, f"{name} was never called; calls: {self.calls}"
        return matches[-1]

    # ---- bootstrap ----
    def get_cfg(self):
        return self._cfg

    def dump_cfg(self):
        return json.dumps(self._cfg)

    # ---- loads ----
    def load_bin_program(self, binprog, load_mem=True):
        self._rec("load_bin_program", binprog, load_mem)

    def reload_mem(self):
        self._rec("reload_mem")

    def load_mem(self, data, mem_sel="dmem", addr=0):
        self._rec("load_mem", data, mem_sel, addr)

    def load_envelope(self, ch, data, addr):
        self._rec("load_envelope", ch, data, addr)

    def load_weights(self, ch, data, addr=0):
        self._rec("load_weights", ch, data, addr)

    # ---- reads ----
    def get_decimated(self, ch, address=0, length=None):
        self._rec("get_decimated", ch, address, length)
        n = 16 if length is None else length
        return np.arange(2 * n, dtype=np.int16).reshape(-1, 2)

    def get_accumulated(self, ch, address=0, length=None):
        self._rec("get_accumulated", ch, address, length)
        n = 16 if length is None else length
        return np.arange(2 * n, dtype=np.int64).reshape(-1, 2)

    def get_ddr4(self, nt, start=None):
        self._rec("get_ddr4", nt, start)
        return np.arange(2 * 128 * nt, dtype=np.int16).reshape(-1, 2)

    def get_mr(self, start=None):
        self._rec("get_mr", start)
        return np.arange(64, dtype=np.int16).reshape(-1, 2)

    def read_mem(self, length, mem_sel="dmem", addr=0):
        self._rec("read_mem", length, mem_sel, addr)
        if mem_sel in ("pmem", "wmem"):
            return np.arange(8 * length, dtype=np.int32).reshape(-1, 8)
        return np.arange(length, dtype=np.int32)

    # ---- control (record-only) ----
    def set_nyquist(self, ch, nqz, force=False):
        self._rec("set_nyquist", ch, nqz, force)

    def set_mixer_freq(self, ch, f, ro_ch=None, phase_reset=True):
        self._rec("set_mixer_freq", ch, f, ro_ch, phase_reset)

    def config_mux_gen(self, ch, tones):
        self._rec("config_mux_gen", ch, tones)

    def set_iq(self, ch, f, i, q, ro_ch=None, phase_reset=True):
        self._rec("set_iq", ch, f, i, q, ro_ch, phase_reset)

    def reset_gens(self):
        self._rec("reset_gens")

    def configure_readout(self, ch, ro_regs):
        self._rec("configure_readout", ch, ro_regs)

    def config_mux_readout(self, pfbpath, cfgs, sel=None):
        self._rec("config_mux_readout", pfbpath, cfgs, sel)

    def config_avg(self, ch, address=0, length=1,
                   edge_counting=False, high_threshold=1000, low_threshold=0):
        self._rec("config_avg", ch, address, length, edge_counting, high_threshold, low_threshold)

    def config_buf(self, ch, address=0, length=1):
        self._rec("config_buf", ch, address, length)

    def enable_buf(self, ch, enable_avg=True, enable_buf=True):
        self._rec("enable_buf", ch, enable_avg, enable_buf)

    def start_src(self, src):
        self._rec("start_src", src)

    def start_tproc(self):
        self._rec("start_tproc")

    def stop_tproc(self, lazy=False):
        self._rec("stop_tproc", lazy)

    def prepare_round(self):
        self._rec("prepare_round")

    def cleanup_round(self):
        self._rec("cleanup_round")

    def clear_tproc_counter(self, addr):
        self._rec("clear_tproc_counter", addr)

    def get_tproc_counter(self, addr):
        self._rec("get_tproc_counter", addr)
        return 42

    def set_adc_attenuator(self, blockname, attenuation):
        self._rec("set_adc_attenuator", blockname, attenuation)
        return round(attenuation)

    def get_adc_attenuator(self, blockname):
        self._rec("get_adc_attenuator", blockname)
        return 5.0

    def freeze_adc_cals(self, blocknames):
        self._rec("freeze_adc_cals", blocknames)

    def unfreeze_adc_cals(self, blocknames):
        self._rec("unfreeze_adc_cals", blocknames)

    def clocks_locked(self):
        self._rec("clocks_locked")
        return True

    def get_sample_rates(self):
        self._rec("get_sample_rates")
        return {"dac": {0: 9830.4}, "adc": {2: 4915.2}}

    def pl_reset(self, reinit=True):
        self._rec("pl_reset", reinit)

    def clear_ddr4(self, length=None):
        self._rec("clear_ddr4", length)

    def arm_ddr4(self, ch, nt, force_overwrite=False):
        self._rec("arm_ddr4", ch, nt, force_overwrite)

    def arm_mr(self, ch):
        self._rec("arm_mr", ch)

    # ---- streaming readout ----
    def start_readout(self, total_shots, counter_addr=1, ch_list=None,
                      reads_per_shot=1, stride=None):
        self._rec("start_readout", total_shots, counter_addr, ch_list, reads_per_shot, stride)
        self.streamer.total_count = total_shots
        self.streamer.count = 0
        # the real start_readout stops a leftover run and flushes the queue
        self.poll_batches = []

    def poll_data(self, totaltime=0.1, timeout=None):
        self._rec("poll_data", totaltime, timeout)
        if not self.poll_batches:
            # the real poll_data blocks on the data queue; don't busy-spin
            import time
            time.sleep(min(0.05, totaltime if totaltime > 0 else 0.05))
            return []
        batch = self.poll_batches.pop(0)
        self.streamer.count += sum(length for length, _ in batch)
        return batch


def make_poll_batch(newshots, nchan=2, reads_per_shot=1, elapsed=0.5, shots=None, addr=0):
    """One scripted streamer queue entry: (length, (acc_buf, stats))."""
    shots = newshots if shots is None else shots
    acc_buf = [np.arange(2 * newshots * reads_per_shot, dtype=np.int64).reshape(-1, 2) + ch
               for ch in range(nchan)]
    return (newshots, (acc_buf, (elapsed, shots, addr, newshots)))


@pytest.fixture
def soc():
    return FakeSoc(tproc_version=1)


@pytest.fixture
def soc_v2():
    return FakeSoc(tproc_version=2)


@pytest.fixture
def context():
    return FakeContext()
