"""Client-side argument dispatch for _TprocClient. The tproc surface has to
accept both the v1 (single_read(addr)) and v2 (single_read(mem_sel, addr))
call styles from QICK code; these tests pin the request each style builds,
using a recording stub instead of a server."""

import pytest

from qcat_grpc.client import _TprocClient
from qcat_grpc._proto import int64_reply_pb2, memory_type_pb2


class RecordingStub:
    """Stands in for the generated TprocStub: records the last request and
    returns a canned reply for the reading call."""

    def __init__(self, read_value=7):
        self.last = None
        self._read_value = read_value

    def TprocSingleRead(self, req):
        self.last = req
        return int64_reply_pb2.Int64Reply(value=self._read_value)

    def TprocSingleWrite(self, req):
        self.last = req

    def TprocStart(self, req):
        self.last = ("start", req)

    def TprocSetLfsrCfg(self, req):
        self.last = req


@pytest.fixture
def stub():
    return RecordingStub()


@pytest.fixture
def tproc(stub):
    return _TprocClient(stub)


# ---- single_read ----

def test_single_read_v1_positional_addr(tproc, stub):
    assert tproc.single_read(5) == 7
    assert stub.last.address == 5
    assert stub.last.memory == memory_type_pb2.MEMORY_TYPE_UNSPECIFIED  # left unset for v1


def test_single_read_v2_two_positional(tproc, stub):
    tproc.single_read("pmem", 9)
    assert stub.last.address == 9
    assert stub.last.memory == memory_type_pb2.PMEM


def test_single_read_v2_mem_positional_addr_keyword(tproc, stub):
    tproc.single_read("wmem", addr=3)
    assert stub.last.address == 3
    assert stub.last.memory == memory_type_pb2.WMEM


def test_single_read_accepts_raw_int_memtype(tproc, stub):
    # QICK's v2 driver passes the raw MemoryType int, not the name
    tproc.single_read(memory_type_pb2.WMEM, 1)
    assert stub.last.memory == memory_type_pb2.WMEM


def test_single_read_all_keywords(tproc, stub):
    tproc.single_read(mem_sel="dmem", addr=2)
    assert stub.last.address == 2
    assert stub.last.memory == memory_type_pb2.DMEM


def test_single_read_too_many_positional_raises(tproc):
    with pytest.raises(TypeError, match="at most 2 positional"):
        tproc.single_read("dmem", 1, 2)


# ---- single_write ----

def test_single_write_v1_keywords(tproc, stub):
    tproc.single_write(addr=6, data=99)
    assert (stub.last.address, stub.last.data) == (6, 99)
    assert stub.last.memory == memory_type_pb2.MEMORY_TYPE_UNSPECIFIED


def test_single_write_v2_all_positional(tproc, stub):
    tproc.single_write("pmem", 6, 99)
    assert (stub.last.address, stub.last.data) == (6, 99)
    assert stub.last.memory == memory_type_pb2.PMEM


def test_single_write_v2_mem_and_addr_positional(tproc, stub):
    tproc.single_write("dmem", 4)
    assert (stub.last.address, stub.last.data) == (4, 0)
    assert stub.last.memory == memory_type_pb2.DMEM


def test_single_write_too_many_positional_raises(tproc):
    with pytest.raises(TypeError, match="at most 3 positional"):
        tproc.single_write("dmem", 1, 2, 3)


# ---- misc passthrough ----

def test_start_and_set_lfsr_cfg(tproc, stub):
    tproc.start()
    assert stub.last[0] == "start"
    tproc.set_lfsr_cfg(mode=1, core=2)
    assert (stub.last.mode, stub.last.core) == (1, 2)
