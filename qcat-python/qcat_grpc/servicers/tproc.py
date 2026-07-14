import grpc

from .._proto import ack_pb2, int64_reply_pb2, memory_type_pb2, tproc_pb2_grpc
from . import ServiceError, unary

_ACK = ack_pb2.Ack()

# For tProc v2 the driver's single_read/single_write take a raw mem_sel int
# whose encoding (pmem=1, dmem=2, wmem=3; see the register maps in
# Axis_QICK_Proc.read_mem/load_mem) matches the MemoryType enum values.
_V2_DEFAULT_MEM = memory_type_pb2.DMEM


def _mem_sel_int(memtype):
    return int(memtype) if memtype != memory_type_pb2.MEMORY_TYPE_UNSPECIFIED else int(_V2_DEFAULT_MEM)


class TprocServicer(tproc_pb2_grpc.TprocServicer):
    """Dispatches on soc.TPROC_VERSION: v1 (AxisTProc64x32_x8) and v2
    (Axis_QICK_Proc) are different driver classes with different signatures."""

    def __init__(self, soc):
        self.soc = soc

    @unary
    def TprocStart(self, request, context):
        self.soc.tproc.start()
        return _ACK

    @unary
    def TprocSingleRead(self, request, context):
        if self.soc.TPROC_VERSION == 1:
            value = self.soc.tproc.single_read(request.address)
        else:
            value = self._v2_single_access(
                context, "single_read", _mem_sel_int(request.memory), request.address)
        return int64_reply_pb2.Int64Reply(value=int(value))

    @unary
    def TprocSingleWrite(self, request, context):
        if self.soc.TPROC_VERSION == 1:
            self.soc.tproc.single_write(addr=request.address, data=request.data)
        else:
            self._v2_single_access(
                context, "single_write", _mem_sel_int(request.memory), request.address, data=request.data)
        return _ACK

    @unary
    def TprocSetLfsrCfg(self, request, context):
        if self.soc.TPROC_VERSION != 2:
            raise ServiceError(grpc.StatusCode.UNIMPLEMENTED,
                               "set_lfsr_cfg is only available on tProc v2")
        self.soc.tproc.set_lfsr_cfg(int(request.mode), core=request.core)
        return _ACK

    def _v2_single_access(self, context, name, mem_sel, addr, **kwargs):
        # upstream caveat: the v2 driver's single_read/single_write reference an
        # undefined variable `i` and are docstring-marked "Do not use! Use the
        # DMA instead." - surface that clearly instead of an opaque NameError
        try:
            return getattr(self.soc.tproc, name)(mem_sel, addr=addr, **kwargs)
        except NameError as e:
            raise ServiceError(
                grpc.StatusCode.UNIMPLEMENTED,
                f"tProc v2 {name} is broken in this QICK version "
                f"(upstream marks it 'Do not use'; use read_mem/load_mem instead): {e}") from e
