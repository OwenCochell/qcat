"""gRPC transport for QICK: a server that binds the qcat protocol to a real
QickSoc, and a QickSoc-compatible client proxy (a drop-in replacement for the
Pyro4 proxy from qick.pyro).

Typical use:

    # on the RFSoC board
    python -m qcat_grpc.server --port 8000

    # on the client
    from qcat_grpc import make_proxy
    soc, soccfg = make_proxy("192.168.1.2", 8000)
"""

from .client import QickSocClient, make_proxy

__all__ = ["QickSocClient", "make_proxy"]
