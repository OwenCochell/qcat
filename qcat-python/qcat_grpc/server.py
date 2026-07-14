"""gRPC server entrypoint: initializes a QickSoc on the board and serves the
six qcat services. Mirrors qick.pyro.start_server as the Pyro replacement.

    python -m qcat_grpc.server --port 8000
    python -m qcat_grpc.server --tls-cert server.pem --tls-key server.key [--tls-ca ca.pem]
"""

import argparse
import logging
from concurrent import futures

import grpc

from ._proto import (
    bootstrap_pb2_grpc,
    control_pb2_grpc,
    load_pb2_grpc,
    read_pb2_grpc,
    readout_pb2_grpc,
    tproc_pb2_grpc,
)
from .servicers import (
    BootstrapServicer,
    ControlServicer,
    LoadServicer,
    ReadServicer,
    ReadoutServicer,
    TprocServicer,
)

logger = logging.getLogger(__name__)

# chunks are ~1 MiB; 8 MiB message caps give margin for readout DataPackets
GRPC_OPTIONS = [
    ("grpc.max_send_message_length", 8 << 20),
    ("grpc.max_receive_message_length", 8 << 20),
]


def register_servicers(server, soc):
    """Register all six qcat services, each wrapping the same QickSoc."""
    bootstrap_pb2_grpc.add_BootstrapServicer_to_server(BootstrapServicer(soc), server)
    load_pb2_grpc.add_LoadServicer_to_server(LoadServicer(soc), server)
    read_pb2_grpc.add_ReadServicer_to_server(ReadServicer(soc), server)
    control_pb2_grpc.add_ControlServicer_to_server(ControlServicer(soc), server)
    readout_pb2_grpc.add_ReadoutServicer_to_server(ReadoutServicer(soc), server)
    tproc_pb2_grpc.add_TprocServicer_to_server(TprocServicer(soc), server)


def start_server(host="0.0.0.0", port=8000, soc=None, soc_class=None,
                 server_credentials=None, max_workers=8, **kwargs):
    """Initialize the QickSoc and start (but don't block on) the gRPC server.

    Parameters
    ----------
    host, port : bind address. port=0 picks a free port.
    soc : an already-constructed QickSoc (e.g. an RFQickSoc subclass instance);
        if None, one is built from soc_class(**kwargs).
    soc_class : class to instantiate when soc is None (default qick.QickSoc).
    server_credentials : grpc.ServerCredentials for TLS/mTLS; None = plaintext.
    max_workers : thread pool size; must be >1 so a PollData stream can run
        concurrently with control calls.
    kwargs : passed to the QickSoc constructor (e.g. bitfile).

    Returns
    -------
    (grpc.Server, int) : the started server and the bound port.
    """
    if soc is None:
        if soc_class is None:
            from qick import QickSoc
            soc_class = QickSoc
        soc = soc_class(**kwargs)
        logger.info("initialized QICK")

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers), options=GRPC_OPTIONS)
    register_servicers(server, soc)

    address = f"{host}:{port}"
    if server_credentials is not None:
        bound_port = server.add_secure_port(address, server_credentials)
    else:
        bound_port = server.add_insecure_port(address)
    server.start()
    logger.info("serving QICK on %s:%d", host, bound_port)
    return server, bound_port


def load_server_credentials(cert_file, key_file, ca_file=None):
    """Build TLS server credentials; passing ca_file enables mTLS (clients must
    present a certificate signed by that CA)."""
    with open(key_file, "rb") as f:
        key = f.read()
    with open(cert_file, "rb") as f:
        cert = f.read()
    root = None
    if ca_file is not None:
        with open(ca_file, "rb") as f:
            root = f.read()
    return grpc.ssl_server_credentials(
        [(key, cert)], root_certificates=root, require_client_auth=root is not None)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve a QickSoc over gRPC")
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="bind port (default 8000)")
    parser.add_argument("--bitfile", default=None, help="firmware bitfile passed to QickSoc")
    parser.add_argument("--tls-cert", default=None, help="server certificate (PEM); enables TLS")
    parser.add_argument("--tls-key", default=None, help="server private key (PEM)")
    parser.add_argument("--tls-ca", default=None,
                        help="CA certificate (PEM) for verifying clients; enables mTLS")
    parser.add_argument("--workers", type=int, default=8, help="thread pool size (default 8)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)

    credentials = None
    if args.tls_cert or args.tls_key:
        if not (args.tls_cert and args.tls_key):
            parser.error("--tls-cert and --tls-key must be given together")
        credentials = load_server_credentials(args.tls_cert, args.tls_key, args.tls_ca)

    kwargs = {}
    if args.bitfile is not None:
        kwargs["bitfile"] = args.bitfile

    server, _ = start_server(
        host=args.host, port=args.port, server_credentials=credentials,
        max_workers=args.workers, **kwargs)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
