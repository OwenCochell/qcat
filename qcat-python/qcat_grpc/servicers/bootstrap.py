from .._proto import bootstrap_pb2_grpc, dump_cfg_pb2, get_cfg_pb2
from . import unary


class BootstrapServicer(bootstrap_pb2_grpc.BootstrapServicer):
    def __init__(self, soc):
        self.soc = soc

    @unary
    def GetCfg(self, request, context):
        # dump_cfg() already produces JSON that QickConfig round-trips
        # (including numpy values), so reuse it rather than re-encoding get_cfg()
        return get_cfg_pb2.CfgReply(
            encoding=get_cfg_pb2.JSON, data=self.soc.dump_cfg().encode())

    @unary
    def DumpCfg(self, request, context):
        return dump_cfg_pb2.DumpCfgReply(json=self.soc.dump_cfg())
