import json

from .._proto import (
    ack_pb2,
    bool_reply_pb2,
    control_pb2_grpc,
    float_reply_pb2,
    int64_reply_pb2,
    sample_rates_pb2,
    start_src_pb2,
)
from ..serialize import decode_dict, opt
from . import unary

_ACK = ack_pb2.Ack()

_START_SRC = {
    start_src_pb2.INTERNAL: "internal",
    start_src_pb2.EXTERNAL: "external",
}


class ControlServicer(control_pb2_grpc.ControlServicer):
    def __init__(self, soc):
        self.soc = soc

    # ---- generator / mixer config ----

    @unary
    def SetNyquist(self, request, context):
        self.soc.set_nyquist(request.channel, request.nqz, force=request.force)
        return _ACK

    @unary
    def SetMixerFreq(self, request, context):
        self.soc.set_mixer_freq(
            request.channel, request.freq,
            ro_ch=opt(request, "ro_ch"), phase_reset=opt(request, "phase_reset", True))
        return _ACK

    @unary
    def ConfigMuxGen(self, request, context):
        self.soc.config_mux_gen(request.channel, decode_dict(request.tones))
        return _ACK

    @unary
    def SetIQ(self, request, context):
        self.soc.set_iq(
            request.channel, request.freq, request.i, request.q,
            ro_ch=opt(request, "ro_ch"), phase_reset=opt(request, "phase_reset", True))
        return _ACK

    @unary
    def ResetGens(self, request, context):
        self.soc.reset_gens()
        return _ACK

    # ---- readout / buffer config ----

    @unary
    def ConfigureReadout(self, request, context):
        self.soc.configure_readout(request.channel, decode_dict(request.ro_regs))
        return _ACK

    @unary
    def ConfigMuxReadout(self, request, context):
        self.soc.config_mux_readout(
            request.pfbpath, decode_dict(request.cfgs), sel=opt(request, "sel"))
        return _ACK

    @unary
    def ConfigAvg(self, request, context):
        self.soc.config_avg(
            request.channel, address=request.address, length=opt(request, "length", 1),
            edge_counting=request.edge_counting,
            high_threshold=opt(request, "high_threshold", 1000),
            low_threshold=request.low_threshold)
        return _ACK

    @unary
    def ConfigBuf(self, request, context):
        self.soc.config_buf(request.channel, address=request.address, length=opt(request, "length", 1))
        return _ACK

    @unary
    def EnableBuf(self, request, context):
        self.soc.enable_buf(
            request.channel,
            enable_avg=opt(request, "enable_avg", True),
            enable_buf=opt(request, "enable_buf", True))
        return _ACK

    # ---- tProc start / stop / counter ----

    @unary
    def StartSrc(self, request, context):
        self.soc.start_src(_START_SRC[request.src])
        return _ACK

    @unary
    def StartTproc(self, request, context):
        self.soc.start_tproc()
        return _ACK

    @unary
    def StopTproc(self, request, context):
        self.soc.stop_tproc(lazy=request.lazy)
        return _ACK

    @unary
    def PrepareRound(self, request, context):
        self.soc.prepare_round()
        return _ACK

    @unary
    def CleanupRound(self, request, context):
        self.soc.cleanup_round()
        return _ACK

    @unary
    def ClearTprocCounter(self, request, context):
        self.soc.clear_tproc_counter(request.address)
        return _ACK

    @unary
    def GetTprocCounter(self, request, context):
        return int64_reply_pb2.Int64Reply(value=int(self.soc.get_tproc_counter(request.address)))

    # ---- ADC attenuator / calibration ----

    @unary
    def SetAdcAttenuator(self, request, context):
        rounded = self.soc.set_adc_attenuator(request.blockname, request.attenuation)
        return float_reply_pb2.FloatReply(value=float(rounded))

    @unary
    def GetAdcAttenuator(self, request, context):
        return float_reply_pb2.FloatReply(value=float(self.soc.get_adc_attenuator(request.blockname)))

    @unary
    def FreezeAdcCals(self, request, context):
        self.soc.freeze_adc_cals(list(request.blocknames))
        return _ACK

    @unary
    def UnfreezeAdcCals(self, request, context):
        self.soc.unfreeze_adc_cals(list(request.blocknames))
        return _ACK

    # ---- clocks / rates / reset ----

    @unary
    def ClocksLocked(self, request, context):
        return bool_reply_pb2.BoolReply(value=bool(self.soc.clocks_locked()))

    @unary
    def GetSampleRates(self, request, context):
        return sample_rates_pb2.SampleRatesReply(json=json.dumps(self.soc.get_sample_rates()))

    @unary
    def PlReset(self, request, context):
        self.soc.pl_reset(reinit=opt(request, "reinit", True))
        return _ACK

    # ---- DDR4 / MR buffers ----

    @unary
    def ClearDdr4(self, request, context):
        self.soc.clear_ddr4(length=opt(request, "length"))
        return _ACK

    @unary
    def ArmDdr4(self, request, context):
        self.soc.arm_ddr4(request.channel, request.num_trans, force_overwrite=request.force_overwrite)
        return _ACK

    @unary
    def ArmMr(self, request, context):
        self.soc.arm_mr(request.channel)
        return _ACK
