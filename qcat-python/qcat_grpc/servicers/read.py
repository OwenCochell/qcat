import numpy as np

from .._proto import read_pb2_grpc
from ..serialize import array_to_frames, memtype_to_str, opt
from . import streaming


class ReadServicer(read_pb2_grpc.ReadServicer):
    def __init__(self, soc):
        self.soc = soc

    # get_decimated/get_accumulated return a single (length, 2) ndarray
    # (I/Q on the last axis, per AxisAvgBuffer.transfer_buf/transfer_avg),
    # so no reshaping is needed to satisfy the protocol's [..., 2] convention;
    # np.asarray only matters if a driver hands back a list.

    @streaming
    def GetDecimated(self, request, context):
        data = self.soc.get_decimated(request.channel, address=request.address, length=opt(request, "length"))
        yield from array_to_frames(np.asarray(data))

    @streaming
    def GetAccumulated(self, request, context):
        data = self.soc.get_accumulated(request.channel, address=request.address, length=opt(request, "length"))
        yield from array_to_frames(np.asarray(data))

    @streaming
    def GetDdr4(self, request, context):
        yield from array_to_frames(np.asarray(self.soc.get_ddr4(request.num_trans, start=opt(request, "start"))))

    @streaming
    def GetMr(self, request, context):
        yield from array_to_frames(np.asarray(self.soc.get_mr(start=opt(request, "start"))))

    @streaming
    def ReadMem(self, request, context):
        data = self.soc.read_mem(request.length, mem_sel=memtype_to_str(request.memory), addr=request.address)
        yield from array_to_frames(np.asarray(data))
