"""End-to-end tests: a real QickSocClient talking to a real grpc.server over
localhost, backed by the FakeSoc. Exercises both directions of every transport
pattern (unary, client-streaming, server-streaming) without hardware."""

import time
from concurrent import futures

import grpc
import numpy as np
import pytest

from conftest import FakeSoc, make_poll_batch
from qcat_grpc.client import GRPC_OPTIONS, QickSocClient
from qcat_grpc.server import register_servicers


@pytest.fixture
def fake_soc():
    return FakeSoc(tproc_version=1)


@pytest.fixture
def client(fake_soc):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8), options=GRPC_OPTIONS)
    register_servicers(server, fake_soc)
    port = server.add_insecure_port("localhost:0")
    server.start()
    channel = grpc.insecure_channel(f"localhost:{port}", options=GRPC_OPTIONS)
    soc = QickSocClient(channel)
    yield soc
    soc.close()
    server.stop(grace=None)


def test_get_cfg_roundtrip(client, fake_soc):
    assert client.get_cfg() == fake_soc.get_cfg()
    assert client.dump_cfg() == fake_soc.dump_cfg()


def test_control_calls(client, fake_soc):
    client.set_mixer_freq(2, 1000.5)
    assert fake_soc.last("set_mixer_freq") == ("set_mixer_freq", 2, 1000.5, None, True)
    client.set_mixer_freq(2, 1000.5, ro_ch=0, phase_reset=False)
    assert fake_soc.last("set_mixer_freq") == ("set_mixer_freq", 2, 1000.5, 0, False)
    client.config_mux_gen(1, [{"freq_int": 5}])
    assert fake_soc.last("config_mux_gen") == ("config_mux_gen", 1, [{"freq_int": 5}])
    client.start_src("external")
    assert fake_soc.last("start_src") == ("start_src", "external")
    assert client.get_tproc_counter(1) == 42
    assert client.clocks_locked() is True
    assert client.get_sample_rates() == {"dac": {"0": 9830.4}, "adc": {"2": 4915.2}}
    assert client.set_adc_attenuator("21", 5.4) == 5.0
    client.clear_ddr4()
    assert fake_soc.last("clear_ddr4") == ("clear_ddr4", None)


def test_all_control_wrappers_roundtrip(client, fake_soc):
    """Every client control wrapper builds the right request and the server
    forwards it to the SoC. One test so each method is exercised over the wire."""
    client.set_nyquist(1, 2, force=True)
    assert fake_soc.last("set_nyquist") == ("set_nyquist", 1, 2, True)
    client.set_iq(0, 100.0, 0.5, -0.5)
    assert fake_soc.last("set_iq") == ("set_iq", 0, 100.0, 0.5, -0.5, None, True)
    client.set_iq(0, 100.0, 0.5, -0.5, ro_ch=2, phase_reset=False)
    assert fake_soc.last("set_iq") == ("set_iq", 0, 100.0, 0.5, -0.5, 2, False)
    client.reset_gens()
    assert fake_soc.last("reset_gens") == ("reset_gens",)
    client.configure_readout(3, {"r": 1})
    assert fake_soc.last("configure_readout") == ("configure_readout", 3, {"r": 1})
    client.config_mux_readout("blk/pfb", [{"f": 1}], sel="input")
    assert fake_soc.last("config_mux_readout") == ("config_mux_readout", "blk/pfb", [{"f": 1}], "input")
    client.config_avg(1, address=16, length=4, edge_counting=True, high_threshold=2000, low_threshold=1)
    assert fake_soc.last("config_avg") == ("config_avg", 1, 16, 4, True, 2000, 1)
    client.config_buf(2, address=8, length=3)
    assert fake_soc.last("config_buf") == ("config_buf", 2, 8, 3)
    client.enable_buf(0, enable_avg=False, enable_buf=True)
    assert fake_soc.last("enable_buf") == ("enable_buf", 0, False, True)
    client.start_tproc()
    assert fake_soc.last("start_tproc") == ("start_tproc",)
    client.stop_tproc(lazy=True)
    assert fake_soc.last("stop_tproc") == ("stop_tproc", True)
    client.prepare_round()
    assert fake_soc.last("prepare_round") == ("prepare_round",)
    client.cleanup_round()
    assert fake_soc.last("cleanup_round") == ("cleanup_round",)
    client.clear_tproc_counter(7)
    assert fake_soc.last("clear_tproc_counter") == ("clear_tproc_counter", 7)
    assert client.get_adc_attenuator("21") == 5.0
    client.freeze_adc_cals(["a", "b"])
    assert fake_soc.last("freeze_adc_cals") == ("freeze_adc_cals", ["a", "b"])
    client.unfreeze_adc_cals(["c"])
    assert fake_soc.last("unfreeze_adc_cals") == ("unfreeze_adc_cals", ["c"])
    client.pl_reset(reinit=False)
    assert fake_soc.last("pl_reset") == ("pl_reset", False)
    client.clear_ddr4(length=64)
    assert fake_soc.last("clear_ddr4") == ("clear_ddr4", 64)
    client.arm_ddr4(1, 4, force_overwrite=True)
    assert fake_soc.last("arm_ddr4") == ("arm_ddr4", 1, 4, True)
    client.arm_mr(2)
    assert fake_soc.last("arm_mr") == ("arm_mr", 2)


def test_get_ddr4_and_mr_with_start(client, fake_soc):
    ddr4 = client.get_ddr4(2, start=16)
    assert fake_soc.last("get_ddr4") == ("get_ddr4", 2, 16)
    assert ddr4.dtype == np.int16 and ddr4.shape == (256, 2)
    mr = client.get_mr(start=8)
    assert fake_soc.last("get_mr") == ("get_mr", 8)
    assert mr.dtype == np.int16 and mr.shape == (32, 2)


def test_client_context_manager_closes(client):
    with client as c:
        assert c is client
    # __exit__ closed the channel; a fresh RPC should now fail (grpc raises
    # ValueError on a closed channel, RpcError if it reaches the transport)
    with pytest.raises((ValueError, grpc.RpcError)):
        client.clocks_locked()


def test_server_error_surfaces_as_internal(client, fake_soc):
    def boom():
        raise RuntimeError("kaboom")
    fake_soc.reset_gens = boom
    with pytest.raises(grpc.RpcError) as excinfo:
        client.reset_gens()
    assert excinfo.value.code() == grpc.StatusCode.INTERNAL
    assert "kaboom" in str(excinfo.value.details())


def test_reads_roundtrip(client, fake_soc):
    dec = client.get_decimated(0, length=50)
    assert dec.dtype == np.int16 and dec.shape == (50, 2)
    acc = client.get_accumulated(1, address=4, length=8)
    assert acc.dtype == np.int64 and acc.shape == (8, 2)
    assert fake_soc.last("get_accumulated") == ("get_accumulated", 1, 4, 8)
    pmem = client.read_mem(4, mem_sel="pmem", addr=2)
    assert pmem.shape == (4, 8)
    assert fake_soc.last("read_mem") == ("read_mem", 4, "pmem", 2)


def test_load_bin_program_v1_roundtrip(client, fake_soc):
    binprog = np.arange(5000, dtype=np.uint64)
    client.load_bin_program(binprog)
    _, got, load_mem = fake_soc.last("load_bin_program")
    assert load_mem is True
    np.testing.assert_array_equal(got, binprog)
    # also accepts a plain list, like the Pyro path did
    client.load_bin_program([1, 2, 3], load_mem=False)
    _, got, load_mem = fake_soc.last("load_bin_program")
    assert load_mem is False
    np.testing.assert_array_equal(got, np.array([1, 2, 3], dtype=np.uint64))


def test_load_bin_program_v2_roundtrip(client, fake_soc):
    prog = {"pmem": np.arange(80, dtype=np.int32).reshape(-1, 8),
            "dmem": np.arange(10, dtype=np.int32),
            "wmem": None}
    client.load_bin_program(prog)
    _, got, _ = fake_soc.last("load_bin_program")
    assert isinstance(got, dict)
    np.testing.assert_array_equal(got["pmem"], prog["pmem"])
    np.testing.assert_array_equal(got["dmem"], prog["dmem"])
    assert got["wmem"] is None


def test_load_envelope_multichunk(client, fake_soc):
    # > 2 MiB of int16, forcing multiple 1 MiB chunks on the wire
    env = np.arange(1 << 20, dtype=np.int16).reshape(-1, 2)
    client.load_envelope(4, env, 256)
    _, ch, got, addr = fake_soc.last("load_envelope")
    assert (ch, addr) == (4, 256)
    np.testing.assert_array_equal(got, env)


def test_load_mem_and_weights(client, fake_soc):
    client.load_mem(np.arange(100), mem_sel="dmem", addr=4)
    _, got, mem_sel, addr = fake_soc.last("load_mem")
    assert got.dtype == np.int32 and (mem_sel, addr) == ("dmem", 4)
    client.load_weights(0, np.ones((16, 2)))
    _, ch, got, addr = fake_soc.last("load_weights")
    assert got.dtype == np.int16 and (ch, addr) == (0, 0)
    client.reload_mem()
    assert fake_soc.last("reload_mem") == ("reload_mem",)


def test_tproc_subobject(client, fake_soc):
    client.tproc.start()
    assert fake_soc.calls[-1] == ("tproc.start",)
    assert client.tproc.single_read(5) == 7
    assert fake_soc.calls[-1] == ("tproc.single_read", 5)
    client.tproc.single_write(addr=3, data=17)
    assert fake_soc.calls[-1] == ("tproc.single_write", 3, 17)


def test_readout_end_to_end(client, fake_soc):
    client.start_readout(10, counter_addr=2, ch_list=[0, 1], reads_per_shot=2, stride=5)
    assert fake_soc.last("start_readout") == ("start_readout", 10, 2, [0, 1], 2, 5)
    fake_soc.poll_batches = [
        [make_poll_batch(4, nchan=2)],
        [make_poll_batch(6, nchan=2, shots=10, elapsed=1.5)],
    ]

    all_data = []
    deadline = time.time() + 5
    while len(all_data) < 2 and time.time() < deadline:
        all_data.extend(client.poll_data(totaltime=0.1, timeout=0.5))
    assert [length for length, _ in all_data] == [4, 6]

    length, (acc_buf, stats) = all_data[0]
    assert len(acc_buf) == 2
    np.testing.assert_array_equal(acc_buf[1], np.arange(8, dtype=np.int64).reshape(-1, 2) + 1)
    assert stats == (0.5, 4, 0, 4)
    length, (acc_buf, stats) = all_data[1]
    assert stats == (1.5, 10, 0, 6)

    # acquisition complete: poll_data returns immediately with no data
    assert client.poll_data(totaltime=0.1, timeout=0.5) == []


def test_readout_restart_cancels_previous_stream(client, fake_soc):
    client.start_readout(100)
    fake_soc.poll_batches = [[make_poll_batch(2, nchan=1)]]
    time.sleep(0.3)  # let the first stream consume the batch; 2 < 100 keeps it open
    client.start_readout(5)  # restart must cancel the stuck stream
    # new data appears only after the restart, as with the real streamer
    # (start_readout stops the old run and flushes the queue)
    fake_soc.poll_batches = [[make_poll_batch(5, nchan=1)]]
    deadline = time.time() + 5
    data = []
    while len(data) < 1 and time.time() < deadline:
        data.extend(client.poll_data(totaltime=0.1, timeout=0.5))
    assert [length for length, _ in data] == [5]


def test_poll_data_without_readout_returns_empty(client):
    assert client.poll_data(totaltime=-1, timeout=0.1) == []


def test_start_readout_reads_per_shot_list(client, fake_soc):
    client.start_readout(10, ch_list=[0, 1], reads_per_shot=[1, 2])
    assert fake_soc.last("start_readout") == ("start_readout", 10, 1, [0, 1], [1, 2], None)


def test_poll_data_surfaces_stream_error(client, fake_soc):
    """A server-side failure in the PollData stream propagates to poll_data as
    a RuntimeError, rather than hanging or silently ending."""
    def boom(*a, **k):
        raise RuntimeError("stream kaboom")
    client.start_readout(100)
    fake_soc.poll_data = boom  # next server-side poll raises => stream aborts
    deadline = time.time() + 5
    with pytest.raises(RuntimeError, match="exception in readout stream"):
        while time.time() < deadline:
            client.poll_data(totaltime=0.1, timeout=0.5)


def test_make_proxy_returns_soc_and_soccfg(fake_soc):
    pytest.importorskip("qick")
    from qcat_grpc import make_proxy

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8), options=GRPC_OPTIONS)
    register_servicers(server, fake_soc)
    port = server.add_insecure_port("localhost:0")
    server.start()
    try:
        soc, soccfg = make_proxy("localhost", port)
        # same contract as qick.pyro.make_proxy: a soc proxy + a QickConfig
        assert soccfg._cfg == fake_soc.get_cfg()
        assert soc.clocks_locked() is True
        soc.close()
    finally:
        server.stop(grace=None)
