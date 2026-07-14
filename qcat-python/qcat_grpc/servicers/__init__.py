"""gRPC servicers binding the qcat protocol to a QickSoc.

Each servicer wraps the one QickSoc instance; register all six on a single
grpc.server via qcat_grpc.server.register_servicers().
"""

import functools
import logging

import grpc

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """Raised by handler bodies to abort with a specific status code.

    Handlers must not call context.abort() directly: abort() raises a plain
    Exception, which the decorators below would re-abort as INTERNAL,
    clobbering the intended code.
    """

    def __init__(self, code, details):
        super().__init__(details)
        self.code = code
        self.details = details


def _abort(context, exc):
    if isinstance(exc, ServiceError):
        context.abort(exc.code, exc.details)
    logger.exception("RPC failed")
    context.abort(grpc.StatusCode.INTERNAL, f"{type(exc).__name__}: {exc}")


def unary(method):
    """Convert exceptions from a unary-response handler into a gRPC abort:
    ServiceError keeps its status code, anything else becomes INTERNAL."""
    @functools.wraps(method)
    def wrapper(self, request, context):
        try:
            return method(self, request, context)
        except Exception as e:  # noqa: BLE001 - everything crosses the wire as a status
            _abort(context, e)
    return wrapper


def streaming(method):
    """Same as `unary`, for server-streaming (generator) handlers."""
    @functools.wraps(method)
    def wrapper(self, request, context):
        try:
            yield from method(self, request, context)
        except Exception as e:  # noqa: BLE001
            _abort(context, e)
    return wrapper


from .bootstrap import BootstrapServicer
from .control import ControlServicer
from .load import LoadServicer
from .read import ReadServicer
from .readout import ReadoutServicer
from .tproc import TprocServicer

__all__ = [
    "BootstrapServicer",
    "ControlServicer",
    "LoadServicer",
    "ReadServicer",
    "ReadoutServicer",
    "TprocServicer",
    "unary",
    "streaming",
]
