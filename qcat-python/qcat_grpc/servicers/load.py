import numpy as np

from .._proto import ack_pb2, load_pb2_grpc, memory_type_pb2
from ..serialize import buffer_to_array, get_def, memtype_to_str, opt
from . import unary

_ACK = ack_pb2.Ack()


def _append_chunk(buf, chunk):
    if chunk.offset != len(buf):
        raise ValueError(f"array chunk out of order: offset {chunk.offset}, expected {len(buf)}")
    buf += chunk.data


def _collect_data_stream(request_iterator):
    """Reassemble a LoadMemoryFrame/LoadDataFrame client stream (params once,
    then def once, then chunks) into (params, ndarray)."""
    params = None
    adef = None
    buf = bytearray()
    for frame in request_iterator:
        which = frame.WhichOneof("body")
        if which == "params":
            params = frame.params
        elif which == "def":
            adef = get_def(frame)
        elif which == "chunk":
            _append_chunk(buf, frame.chunk)
        else:
            raise ValueError("load frame with no body")
    if params is None or adef is None:
        raise ValueError("load stream missing params or array descriptor")
    return params, buffer_to_array(adef, bytes(buf))


class LoadServicer(load_pb2_grpc.LoadServicer):
    def __init__(self, soc):
        self.soc = soc

    @unary
    def LoadBinProgram(self, request_iterator, context):
        params = None
        sections = []  # (MemoryType, ArrayDef, bytearray) per section, in stream order
        for frame in request_iterator:
            which = frame.WhichOneof("body")
            if which == "params":
                params = frame.params
            elif which == "section":
                sections.append((frame.section.memory, get_def(frame.section), bytearray()))
            elif which == "chunk":
                if not sections:
                    raise ValueError("LoadBinProgram chunk before any section frame")
                _append_chunk(sections[-1][2], frame.chunk)
            else:
                raise ValueError("LoadBinProgram frame with no body")
        if params is None or not sections:
            raise ValueError("LoadBinProgram stream missing params or sections")

        # v1 binprog is a single uint64 array (one UNSPECIFIED section);
        # v2 is a {pmem, dmem, wmem} dict of int32 arrays, tagged per section
        if len(sections) == 1 and sections[0][0] == memory_type_pb2.MEMORY_TYPE_UNSPECIFIED:
            binprog_old = buffer_to_array(sections[0][1], bytes(sections[0][2]))
            self.soc.load_bin_program(binprog_old, load_mem=opt(params, "load_mem", True))
        else:
            # None sections aren't sent on the wire; seed all keys so an empty
            # memory round-trips as {..: None}, matching QICK's v2 program dict.
            binprog: dict[str, np.ndarray | None] = {"pmem": None, "dmem": None, "wmem": None}
            for memory, adef, buf in sections:
                if memory == memory_type_pb2.MEMORY_TYPE_UNSPECIFIED:
                    raise ValueError("LoadBinProgram: UNSPECIFIED section mixed with tagged sections")
                binprog[memtype_to_str(memory)] = buffer_to_array(adef, bytes(buf))
            self.soc.load_bin_program(binprog, load_mem=opt(params, "load_mem", True))
        return _ACK

    @unary
    def LoadMem(self, request_iterator, context):
        params, data = _collect_data_stream(request_iterator)
        self.soc.load_mem(data, mem_sel=memtype_to_str(params.memory), addr=params.address)
        return _ACK

    @unary
    def LoadEnvelope(self, request_iterator, context):
        params, data = _collect_data_stream(request_iterator)
        self.soc.load_envelope(params.channel, data, params.address)
        return _ACK

    @unary
    def LoadWeights(self, request_iterator, context):
        params, data = _collect_data_stream(request_iterator)
        self.soc.load_weights(params.channel, data, addr=params.address)
        return _ACK

    @unary
    def ReloadMem(self, request, context):
        self.soc.reload_mem()
        return _ACK
