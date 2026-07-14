# qcat_grpc — QICK over gRPC

The server and client implementation of the qcat protocol: a gRPC replacement
for QICK's Pyro4 remote (`qick.pyro`). The wire schema lives in the `.proto`
files under `../qcat/`; this package binds them to hardware.

- **Server** (`qcat_grpc.server`): runs on the RFSoC/PYNQ board, wraps a real
  `QickSoc` with the six qcat services (Bootstrap, Load, Read, Control,
  Readout, Tproc).
- **Client** (`qcat_grpc.client`): a `QickSoc`-shaped proxy usable from any
  host. `make_proxy()` mirrors `qick.pyro.make_proxy` and returns
  `(soc, soccfg)`, so existing programs (`AveragerProgram`, `QickProgramV2`,
  ...) work unchanged — a drop-in transport swap. All `QickConfig` compute
  methods (`freq2reg`, `us2cycles`, ...) run client-side on `soccfg`.

## Setup

1. Generate the Python stubs (writes into `qcat_grpc/_pb/`, git-ignored):

   ```
   pip install grpcio-tools
   python ../generate_stubs.py
   ```

2. Install the package (both sides also need `qick`):

   ```
   pip install -e .
   ```

## Run

On the board:

```
python -m qcat_grpc.server --port 8000
# TLS:  --tls-cert server.pem --tls-key server.key   (add --tls-ca ca.pem for mTLS)
```

On the client:

```python
from qcat_grpc import make_proxy
soc, soccfg = make_proxy("192.168.1.2", 8000)
# TLS: make_proxy(host, port, channel_credentials=grpc.ssl_channel_credentials(...))
```

## Design notes

- Bulk arrays travel as a streamed `ArrayDef` descriptor plus bounded ~1 MiB
  `ArrayChunk` frames (`serialize.py`), staying under gRPC's per-message limit.
- Config dicts (`cfg`, `tones`, `ro_regs`, `cfgs`) travel as numpy-aware JSON
  blobs.
- Optional proto fields mean "unset ⇒ apply the Python API default"; the
  server branches on `HasField` (`serialize.opt`).
- `binprog` is version-shaped: tProc v1 = one untagged uint64 section,
  v2 = one tagged int32 section per populated memory (pmem/dmem/wmem).
- Streaming readout keeps the `start_readout()`/`poll_data()` contract: the
  client opens one server-streaming `PollData` RPC per acquisition and drains
  a local queue with the original `poll_data` time/count semantics.
- Unlike Pyro, results are real local objects — no `obtain()` anywhere.

## Tests (no hardware needed)

```
pip install pytest
python -m pytest tests/
```

`tests/conftest.py` provides a `FakeSoc` that records calls and returns canned
arrays; `test_client_server.py` runs the real client against a real in-process
server over localhost. On-hardware parity vs. the Pyro path (step 8 in
`../docs/server_client_implementation.md`) is the remaining validation step.
