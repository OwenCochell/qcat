import threading

import grpc
import numpy as np

from .._proto import ack_pb2, acq_stats_pb2, data_packet_pb2, readout_pb2_grpc
from ..serialize import array_to_def, opt
from . import ServiceError, streaming, unary

_ACK = ack_pb2.Ack()

# queue-wait granularity when the client didn't give a timeout: bounded so the
# loop can notice a cancelled stream instead of blocking on the queue forever
_POLL_TIMEOUT = 1.0


def _make_packet(length, acc_buf, stats):
    """Build a DataPacket from one streamer queue entry.

    acc_buf is one accumulated array per channel (ordered by ch_list); each is
    stride-bounded, so the data rides inline rather than cross-message chunked.
    stats is the streamer's (elapsed, shots, addr, newshots) tuple.
    """
    channels = []
    for arr in acc_buf:
        arr = np.ascontiguousarray(arr)
        channels.append(data_packet_pb2.DataPacket.ChannelData(
            **{"def": array_to_def(arr)}, data=arr.tobytes()))
    elapsed, shots, addr, newshots = stats
    return data_packet_pb2.DataPacket(
        data=channels,
        stats=acq_stats_pb2.AcqStats(
            elapsed=float(elapsed), shots=int(shots), addr=int(addr), new_shots=int(newshots)))


class ReadoutServicer(readout_pb2_grpc.ReadoutServicer):
    def __init__(self, soc):
        self.soc = soc
        # readout is stateful: one acquisition (and one PollData stream) at a
        # time. StartReadout must wait for a cancelled PollData loop to actually
        # exit, or the old loop could steal the new acquisition's packets.
        self._poll_done = threading.Event()
        self._poll_done.set()

    @unary
    def StartReadout(self, request, context):
        if not self._poll_done.wait(timeout=10):
            raise ServiceError(grpc.StatusCode.FAILED_PRECONDITION,
                               "a previous PollData stream is still draining")
        reads_per_shot = list(request.reads_per_shot)
        if not reads_per_shot:
            reads_per_shot = 1  # empty => API default
        elif len(reads_per_shot) == 1:
            reads_per_shot = reads_per_shot[0]  # single value broadcasts to every channel
        self.soc.start_readout(
            request.total_shots,
            counter_addr=opt(request, "counter_addr", 1),
            ch_list=list(request.ch_list) or None,  # empty => API default [0, 1]
            reads_per_shot=reads_per_shot,
            stride=opt(request, "stride"))
        return _ACK

    @streaming
    def PollData(self, request, context):
        """Drain the streamer as a server stream, one DataPacket per queue entry.

        Loops soc.poll_data() until the acquisition started by StartReadout is
        complete (streamer.count >= total_count) or the client cancels. The
        request's totaltime/timeout only set the server-side polling cadence;
        the client applies its own poll_data() time semantics locally.
        """
        totaltime = opt(request, "totaltime", 0.1)
        timeout = opt(request, "timeout")
        streamer = self.soc.streamer
        self._poll_done.clear()
        try:
            while context.is_active():
                packets = self.soc.poll_data(
                    totaltime=totaltime, timeout=timeout if timeout is not None else _POLL_TIMEOUT)
                for length, (acc_buf, stats) in packets:
                    if acc_buf is None:
                        continue  # dummy packet pushed on stop/error
                    yield _make_packet(length, acc_buf, stats)
                if totaltime < 0:
                    # flush mode: one drain-until-timeout pass, then end the stream
                    break
                if streamer.count >= streamer.total_count:
                    break
        finally:
            self._poll_done.set()
