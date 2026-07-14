#!/usr/bin/env python3
"""Generate the Python protobuf + gRPC stubs for the qcat impl package.

Runs grpc_tools.protoc over every .proto under qcat/ and writes the generated
*_pb2.py / *_pb2.pyi / *_pb2_grpc.py modules into impl/qcat_grpc/_pb/, which
is git-ignored. Re-run whenever the protos change:

    python generate_stubs.py

The .proto sources are the canonical, language-agnostic schema and live at the
repo root (../qcat), shared with server implementations in other languages. They
are not shipped with this package; instead the *generated* stubs are. setup.py
runs this before assembling any distribution, so the wheel and the sdist both
carry the generated _pb/ tree. When the protos aren't reachable (a wheel built
from an sdist, which contains the stubs but not the schema) this reuses the
already-generated tree.

protoc emits absolute imports rooted at the proto tree (``from qcat.messages
import ...``). Left alone those only resolve if ``_pb/`` is on sys.path, which
is fragile and, if the same modules are ever reached under a second name, makes
protobuf double-register its descriptors. So after generating we rewrite those
imports to the real installed package path (``qcat_grpc._pb.qcat...``) and drop
an ``__init__.py`` into every output directory. The result is an ordinary
package subtree: it imports under exactly one name and is picked up by
setuptools' package discovery, so it ships in the wheel with no sys.path tricks.

Requires grpcio-tools (pip install grpcio-tools); no native protoc or gRPC
plugin is needed.
"""

import re
import sys
from pathlib import Path

# Repo root holds the canonical `qcat/` proto tree, one level above this project.
ROOT = Path(__file__).resolve().parent.parent
OUT = Path("qcat_grpc") / "_pb"

# The Python package the generated tree lives under once installed.
PKG_PREFIX = "qcat_grpc._pb"

# Match import statements whose module root is the proto tree's top package
# (`qcat`), e.g. `from qcat.messages.read import memory_pb2 as ...` or
# `import qcat.services.read_pb2`. Only the leading `qcat` is rewritten; the
# `as ...` alias and any `qcat` substrings inside serialized descriptors are
# left untouched because this is anchored to the start of the line.
_IMPORT_RE = re.compile(r"^(from|import) qcat(\.|\s)", re.MULTILINE)


def _rewrite_imports(text: str) -> str:
    return _IMPORT_RE.sub(rf"\1 {PKG_PREFIX}.qcat\2", text)


def main():
    protos = sorted(str(p) for p in (ROOT / "qcat").rglob("*.proto"))
    if not protos:
        # No schema reachable. Expected when building a wheel from an sdist: the
        # sdist ships the generated stubs but not the protos, so reuse them.
        if (OUT / "qcat").is_dir() and any(OUT.rglob("*_pb2.py")):
            print(f"no .proto sources found; reusing generated stubs in {OUT}")
            return
        sys.exit(f"no .proto files found under {ROOT / 'qcat'}")

    try:
        from grpc_tools import protoc
    except ImportError:
        sys.exit("grpc_tools not found - install it with: pip install grpcio-tools")

    OUT.mkdir(parents=True, exist_ok=True)

    args = [
        "protoc",
        f"--proto_path={ROOT}",
        f"--python_out={OUT}",
        f"--pyi_out={OUT}",
        f"--grpc_python_out={OUT}",
        *protos,
    ]
    rc = protoc.main(args)
    if rc != 0:
        sys.exit(f"protoc failed with exit code {rc}")

    # Rewrite protoc's absolute imports to the installed package path.
    for path in list(OUT.rglob("*.py")) + list(OUT.rglob("*.pyi")):
        original = path.read_text()
        rewritten = _rewrite_imports(original)
        if rewritten != original:
            path.write_text(rewritten)

    # Make every generated directory a real package so setuptools ships it and
    # so the modules import under a single canonical name.
    for directory in [OUT, *(p for p in OUT.rglob("*") if p.is_dir())]:
        (directory / "__init__.py").touch()

    print(f"generated stubs for {len(protos)} protos -> {OUT}")


if __name__ == "__main__":
    main()
