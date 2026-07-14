"""Shared serialization layer: numpy <-> ArrayDef/ArrayChunk/ArrayFrame streams,
config/dict blobs, optional-field access, and enum maps.

This module is used identically by the server and the client, and is fully
testable without hardware.
"""

import json
import sys

import numpy as np

from ._proto import array_chunk_pb2, array_def_pb2, array_frame_pb2, get_cfg_pb2, memory_type_pb2

# chunk size for streamed arrays: safely under gRPC's 4 MB per-message limit
CHUNK_BYTES = 1 << 20

_DTYPE_TO_PB = {
    np.dtype(np.int16): array_def_pb2.DT_INT16,
    np.dtype(np.int32): array_def_pb2.DT_INT32,
    np.dtype(np.int64): array_def_pb2.DT_INT64,
    np.dtype(np.float32): array_def_pb2.DT_FLOAT32,
    np.dtype(np.float64): array_def_pb2.DT_FLOAT64,
    np.dtype(np.uint16): array_def_pb2.DT_UINT16,
    np.dtype(np.uint32): array_def_pb2.DT_UINT32,
    np.dtype(np.uint64): array_def_pb2.DT_UINT64,
}
_PB_TO_DTYPE = {v: k for k, v in _DTYPE_TO_PB.items()}

_NATIVE_ORDER = array_def_pb2.BIG if sys.byteorder == "big" else array_def_pb2.LITTLE


def get_def(msg):
    """Read a message's `def` field ("def" is a Python keyword, so attribute
    access needs getattr; setting it needs a **{"def": ...} splat)."""
    return getattr(msg, "def")


def dtype_to_pb(dtype):
    dtype = np.dtype(dtype)
    try:
        return _DTYPE_TO_PB[dtype]
    except KeyError:
        raise TypeError(f"dtype {dtype} is not supported by the qcat protocol") from None


def pb_to_dtype(code):
    try:
        return _PB_TO_DTYPE[code]
    except KeyError:
        raise ValueError(f"unknown DType enum value {code}") from None


def array_to_def(arr):
    """Build the ArrayDef descriptor for a (C-contiguous) array."""
    return array_def_pb2.ArrayDef(
        dtype=dtype_to_pb(arr.dtype),
        shape=list(arr.shape),
        order=_NATIVE_ORDER,
        compression=array_def_pb2.NONE,
        byte_length=arr.nbytes,
    )


def bytes_to_chunks(buf, chunk_bytes=CHUNK_BYTES):
    """Slice a raw buffer into bounded ArrayChunk messages."""
    for off in range(0, len(buf), chunk_bytes):
        yield array_chunk_pb2.ArrayChunk(data=buf[off:off + chunk_bytes], offset=off)


def array_to_frames(arr, chunk_bytes=CHUNK_BYTES):
    """Serialize an array as one ArrayDef frame followed by bounded chunk frames."""
    arr = np.ascontiguousarray(arr)

    frame = array_frame_pb2.ArrayFrame()
    getattr(frame, "def").CopyFrom(array_to_def(arr))
    yield frame

    for chunk in bytes_to_chunks(arr.tobytes(), chunk_bytes):
        yield array_frame_pb2.ArrayFrame(chunk=chunk)


def buffer_to_array(adef, buf):
    """Reinterpret a reassembled raw buffer per its ArrayDef descriptor.

    Returns a writable, native-byte-order array of the descriptor's shape.
    """
    if adef.compression == array_def_pb2.ZSTD:
        try:
            import zstandard
        except ImportError:
            raise RuntimeError("received a ZSTD-compressed array but zstandard is not installed") from None
        buf = zstandard.ZstdDecompressor().decompress(buf)
    elif adef.compression != array_def_pb2.NONE:
        raise ValueError(f"unknown Compression enum value {adef.compression}")

    if adef.byte_length and len(buf) != adef.byte_length:
        raise ValueError(f"array reassembly failed: expected {adef.byte_length} bytes, got {len(buf)}")

    dtype = pb_to_dtype(adef.dtype)
    wire_dtype = dtype.newbyteorder(">" if adef.order == array_def_pb2.BIG else "<")
    # np.array (vs frombuffer alone) byteswaps to native order if needed and
    # returns a writable copy
    arr = np.array(np.frombuffer(buf, dtype=wire_dtype), dtype=dtype)
    return arr.reshape(tuple(adef.shape))


def frames_to_array(frames):
    """Reassemble an ArrayFrame stream (one def, then chunks) into an ndarray."""
    adef = None
    buf = bytearray()
    for frame in frames:
        which = frame.WhichOneof("body")
        if which == "def":
            adef = get_def(frame)
        elif which == "chunk":
            if frame.chunk.offset != len(buf):
                raise ValueError(
                    f"array chunk out of order: offset {frame.chunk.offset}, expected {len(buf)}")
            buf += frame.chunk.data
        else:
            raise ValueError("ArrayFrame with no body")
    if adef is None:
        raise ValueError("array stream contained no descriptor frame")
    return buffer_to_array(adef, bytes(buf))


# --------------------------------------------------------------------------
# config / dict blobs
# --------------------------------------------------------------------------

def _np_json_default(obj):
    """JSON encoder default that handles the numpy scalars/arrays that show up
    in QICK config dicts and register dicts."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"object of type {type(obj).__name__} is not JSON serializable")


def encode_cfg(cfg, encoding=get_cfg_pb2.JSON):
    """Serialize a QICK config dict (or a pre-dumped JSON string) to bytes."""
    if encoding == get_cfg_pb2.JSON:
        if isinstance(cfg, str):
            return cfg.encode()
        return json.dumps(cfg, default=_np_json_default).encode()
    if encoding == get_cfg_pb2.CBOR:
        import cbor2
        return cbor2.dumps(cfg, default=lambda enc, o: enc.encode(_np_json_default(o)))
    raise ValueError(f"unknown CfgEncoding enum value {encoding}")


def decode_cfg(data, encoding):
    """Decode a CfgReply blob into the dict QickConfig() accepts."""
    if encoding == get_cfg_pb2.JSON:
        return json.loads(data.decode())
    if encoding == get_cfg_pb2.CBOR:
        import cbor2
        return cbor2.loads(data)
    raise ValueError(f"unknown CfgEncoding enum value {encoding}")


def encode_dict(obj):
    """Serialize a register/tone dict (or list of dicts) blob. Both sides must
    agree on the encoding, and the messages carry no encoding tag, so this is
    fixed to numpy-aware JSON."""
    return json.dumps(obj, default=_np_json_default).encode()


def decode_dict(data):
    return json.loads(data.decode())


# --------------------------------------------------------------------------
# optional fields and enums
# --------------------------------------------------------------------------

def opt(msg, field, default=None):
    """Value of an optional/presence field, or `default` if unset.

    Every optional field in the protos means "unset => apply the Python API
    default", which is often True/None/nonzero - never read the proto
    zero-value blindly.
    """
    return getattr(msg, field) if msg.HasField(field) else default


# MEMORY_TYPE_UNSPECIFIED is the "field left unset" sentinel: apply the API
# default, mem_sel='dmem'.
_MEMTYPE_TO_STR = {
    memory_type_pb2.MEMORY_TYPE_UNSPECIFIED: "dmem",
    memory_type_pb2.PMEM: "pmem",
    memory_type_pb2.DMEM: "dmem",
    memory_type_pb2.WMEM: "wmem",
}
_STR_TO_MEMTYPE = {
    "pmem": memory_type_pb2.PMEM,
    "dmem": memory_type_pb2.DMEM,
    "wmem": memory_type_pb2.WMEM,
}


def memtype_to_str(memtype) -> str:
    try:
        return _MEMTYPE_TO_STR[memtype]
    except KeyError:
        raise ValueError(f"unknown MemoryType enum value {memtype}") from None


def str_to_memtype(mem_sel) -> memory_type_pb2.MemoryType:
    try:
        return _STR_TO_MEMTYPE[mem_sel]
    except KeyError:
        raise ValueError(f"mem_sel should be pmem/dmem/wmem, got {mem_sel!r}") from None
