"""Single import point for the generated protobuf/gRPC modules.

The stubs are generated into the git-ignored _pb/ directory by
generate_stubs.py (run it first if imports fail here, also done at build time). 
That script rewrites protoc's absolute imports to the installed package path 
and drops __init__.py into every directory, so the generated tree is an ordinary subpackage of
qcat_grpc that imports under exactly one name.
"""

from pathlib import Path

_PB_DIR = Path(__file__).resolve().parent / "_pb"
if not (_PB_DIR / "qcat").is_dir():
    raise ImportError(
        f"generated protobuf stubs not found in {_PB_DIR}; "
        "run generate_stubs.py to create them"
    )

# top-level array primitives
from ._pb.qcat.messages import array_chunk_pb2, array_def_pb2, array_frame_pb2, memory_type_pb2

# messages
from ._pb.qcat.messages.bootstrap import dump_cfg_pb2, get_cfg_pb2
from ._pb.qcat.messages.common import ack_pb2, bool_reply_pb2, empty_pb2, float_reply_pb2, int64_reply_pb2
from ._pb.qcat.messages.control import (
    arm_ddr4_pb2,
    arm_mr_pb2,
    clear_ddr4_pb2,
    clear_tproc_counter_pb2,
    config_avg_pb2,
    config_buf_pb2,
    config_mux_gen_pb2,
    config_mux_readout_pb2,
    configure_readout_pb2,
    enable_buf_pb2,
    freeze_adc_cals_pb2,
    get_adc_attenuator_pb2,
    get_tproc_counter_pb2,
    pl_reset_pb2,
    sample_rates_pb2,
    set_adc_attenuator_pb2,
    set_iq_pb2,
    set_mixer_freq_pb2,
    set_nyquist_pb2,
    start_src_pb2,
    stop_tproc_pb2,
    unfreeze_adc_cals_pb2,
)
from ._pb.qcat.messages.load import (
    load_bin_frame_pb2,
    load_bin_pb2,
    load_data_frame_pb2,
    load_data_pb2,
    load_memory_frame_pb2,
    load_memory_pb2,
)
from ._pb.qcat.messages.read import ddr4_buff_pb2, memory_pb2, mr_buff_pb2, read_data_pb2
from ._pb.qcat.messages.readout import acq_stats_pb2, data_packet_pb2, poll_data_pb2, start_readout_pb2
from ._pb.qcat.messages.tproc import tproc_set_lfsr_cfg_pb2, tproc_single_read_pb2, tproc_single_write_pb2

# services
from ._pb.qcat.services import bootstrap_pb2_grpc, control_pb2_grpc, load_pb2_grpc
from ._pb.qcat.services import read_pb2_grpc, readout_pb2_grpc, tproc_pb2_grpc
