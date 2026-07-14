"""Round-trip tests for the serialization layer. No hardware, no sockets."""

import numpy as np
import pytest

from qcat_grpc import serialize
from qcat_grpc._proto import array_chunk_pb2, array_def_pb2, array_frame_pb2, get_cfg_pb2, memory_type_pb2

ALL_DTYPES = [np.int16, np.int32, np.int64, np.float32, np.float64,
              np.uint16, np.uint32, np.uint64]


def roundtrip(arr, chunk_bytes=serialize.CHUNK_BYTES):
    return serialize.frames_to_array(serialize.array_to_frames(arr, chunk_bytes))


@pytest.mark.parametrize("dtype", ALL_DTYPES)
def test_roundtrip_all_dtypes(dtype):
    rng = np.random.default_rng(seed=42)
    arr = rng.integers(0, 100, size=(37, 2)).astype(dtype)
    out = roundtrip(arr)
    assert out.dtype == arr.dtype
    assert out.shape == arr.shape
    np.testing.assert_array_equal(out, arr)


@pytest.mark.parametrize("shape", [(0,), (1,), (100,), (5, 8), (3, 4, 2), (2, 3, 4, 2)])
def test_roundtrip_shapes(shape):
    arr = np.arange(np.prod(shape), dtype=np.int32).reshape(shape)
    out = roundtrip(arr)
    assert out.shape == shape
    np.testing.assert_array_equal(out, arr)


def test_multi_chunk_roundtrip():
    # force many chunks with a small chunk size
    arr = np.arange(10_000, dtype=np.int64)
    frames = list(serialize.array_to_frames(arr, chunk_bytes=1024))
    # 80 kB of data / 1 kB chunks = 79 chunk frames + 1 def frame minimum
    assert len(frames) > 50
    assert frames[0].WhichOneof("body") == "def"
    assert all(f.WhichOneof("body") == "chunk" for f in frames[1:])
    assert all(len(f.chunk.data) <= 1024 for f in frames[1:])
    np.testing.assert_array_equal(serialize.frames_to_array(iter(frames)), arr)


def test_def_frame_metadata():
    arr = np.zeros((7, 2), dtype=np.int16)
    frames = list(serialize.array_to_frames(arr))
    adef = serialize.get_def(frames[0])
    assert adef.dtype == array_def_pb2.DT_INT16
    assert list(adef.shape) == [7, 2]
    assert adef.byte_length == arr.nbytes
    assert adef.compression == array_def_pb2.NONE


def test_big_endian_buffer_decoded():
    arr = np.arange(50, dtype=np.int32)
    adef = serialize.array_to_def(arr)
    adef.order = array_def_pb2.BIG
    out = serialize.buffer_to_array(adef, arr.astype(">i4").tobytes())
    np.testing.assert_array_equal(out, arr)
    assert out.dtype == np.dtype(np.int32)


def test_byte_length_mismatch_raises():
    arr = np.arange(10, dtype=np.int32)
    adef = serialize.array_to_def(arr)
    with pytest.raises(ValueError, match="reassembly"):
        serialize.buffer_to_array(adef, arr.tobytes()[:-4])


def test_result_is_writable():
    out = roundtrip(np.arange(10, dtype=np.int16))
    out[0] = 99  # np.frombuffer alone would be read-only


def test_missing_def_raises():
    arr = np.arange(10, dtype=np.int32)
    frames = list(serialize.array_to_frames(arr))[1:]  # drop the descriptor
    with pytest.raises(ValueError, match="descriptor"):
        serialize.frames_to_array(iter(frames))


def test_unsupported_dtype_raises():
    with pytest.raises(TypeError):
        serialize.array_to_def(np.zeros(3, dtype=np.complex64))


# ---- config / dict blobs ----

def test_cfg_json_roundtrip_with_numpy():
    cfg = {"fs": np.float64(9830.4), "n": np.int32(7), "arr": np.arange(3), "name": "qick"}
    data = serialize.encode_cfg(cfg)
    out = serialize.decode_cfg(data, get_cfg_pb2.JSON)
    assert out == {"fs": 9830.4, "n": 7, "arr": [0, 1, 2], "name": "qick"}


def test_cfg_accepts_predumped_json():
    assert serialize.decode_cfg(serialize.encode_cfg('{"a": 1}'), get_cfg_pb2.JSON) == {"a": 1}


def test_dict_blob_roundtrip():
    tones = [{"freq_int": np.int64(123), "gain_int": 32000}, {"freq_int": 456, "gain_int": 0}]
    out = serialize.decode_dict(serialize.encode_dict(tones))
    assert out == [{"freq_int": 123, "gain_int": 32000}, {"freq_int": 456, "gain_int": 0}]


# ---- optional fields and enums ----

def test_opt_field_presence():
    from qcat_grpc._proto import set_mixer_freq_pb2
    req = set_mixer_freq_pb2.SetMixerFreq(channel=1, freq=100.0)
    assert serialize.opt(req, "ro_ch") is None
    assert serialize.opt(req, "phase_reset", True) is True
    req.phase_reset = False
    assert serialize.opt(req, "phase_reset", True) is False
    req.ro_ch = 0  # explicitly set to the proto zero-value
    assert serialize.opt(req, "ro_ch") == 0


def test_memtype_maps():
    assert serialize.memtype_to_str(memory_type_pb2.MEMORY_TYPE_UNSPECIFIED) == "dmem"
    assert serialize.memtype_to_str(memory_type_pb2.PMEM) == "pmem"
    assert serialize.memtype_to_str(memory_type_pb2.DMEM) == "dmem"
    assert serialize.memtype_to_str(memory_type_pb2.WMEM) == "wmem"
    for name in ("pmem", "dmem", "wmem"):
        assert serialize.memtype_to_str(serialize.str_to_memtype(name)) == name
    with pytest.raises(ValueError):
        serialize.str_to_memtype("imem")


def test_memtype_to_str_unknown_value_raises():
    with pytest.raises(ValueError, match="unknown MemoryType"):
        serialize.memtype_to_str(999)


# ---- dtype / enum error paths ----

def test_pb_to_dtype_unknown_enum_raises():
    with pytest.raises(ValueError, match="unknown DType"):
        serialize.pb_to_dtype(999)


def test_dtype_to_pb_roundtrips_every_supported_dtype():
    for dtype in ALL_DTYPES:
        assert serialize.pb_to_dtype(serialize.dtype_to_pb(dtype)) == np.dtype(dtype)


# ---- compression paths ----

def test_zstd_roundtrip():
    zstandard = pytest.importorskip("zstandard")
    arr = np.arange(500, dtype=np.int32)
    raw = arr.tobytes()
    adef = serialize.array_to_def(arr)
    adef.compression = array_def_pb2.ZSTD
    adef.byte_length = 0  # length check is on the compressed stream; skip it
    compressed = zstandard.ZstdCompressor().compress(raw)
    out = serialize.buffer_to_array(adef, compressed)
    np.testing.assert_array_equal(out, arr)


def test_unknown_compression_enum_raises():
    arr = np.arange(10, dtype=np.int32)
    adef = serialize.array_to_def(arr)
    adef.compression = 999
    with pytest.raises(ValueError, match="unknown Compression"):
        serialize.buffer_to_array(adef, arr.tobytes())


# ---- malformed frame streams ----

def test_empty_frame_body_raises():
    frames = [array_frame_pb2.ArrayFrame(**{"def": serialize.array_to_def(np.arange(4, dtype=np.int32))}),
              array_frame_pb2.ArrayFrame()]  # no body set
    with pytest.raises(ValueError, match="no body"):
        serialize.frames_to_array(iter(frames))


def test_out_of_order_chunk_raises():
    frames = [
        array_frame_pb2.ArrayFrame(**{"def": serialize.array_to_def(np.arange(8, dtype=np.int32))}),
        array_frame_pb2.ArrayFrame(chunk=array_chunk_pb2.ArrayChunk(data=b"\x00\x00\x00\x00", offset=16)),
    ]
    with pytest.raises(ValueError, match="out of order"):
        serialize.frames_to_array(iter(frames))


# ---- CBOR config encoding ----

def test_cfg_cbor_roundtrip_with_numpy():
    pytest.importorskip("cbor2")
    cfg = {"fs": np.float64(9830.4), "n": np.int32(7), "arr": np.arange(3), "name": "qick"}
    data = serialize.encode_cfg(cfg, encoding=get_cfg_pb2.CBOR)
    assert serialize.decode_cfg(data, get_cfg_pb2.CBOR) == {
        "fs": 9830.4, "n": 7, "arr": [0, 1, 2], "name": "qick"}


def test_encode_cfg_unknown_encoding_raises():
    with pytest.raises(ValueError, match="unknown CfgEncoding"):
        serialize.encode_cfg({"a": 1}, encoding=999)


def test_decode_cfg_unknown_encoding_raises():
    with pytest.raises(ValueError, match="unknown CfgEncoding"):
        serialize.decode_cfg(b"{}", encoding=999)


# ---- numpy JSON encoder ----

def test_np_json_default_handles_bool_and_ndarray():
    out = serialize.decode_dict(serialize.encode_dict({"flag": np.bool_(True), "vals": np.arange(2)}))
    assert out == {"flag": True, "vals": [0, 1]}


def test_np_json_default_rejects_unsupported_type():
    with pytest.raises(TypeError, match="not JSON serializable"):
        serialize.encode_dict({"bad": object()})
