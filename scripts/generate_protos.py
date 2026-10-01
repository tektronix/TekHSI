"""Regenerate gRPC stubs from normalizedvector.proto."""

from __future__ import annotations

import shutil
import subprocess
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO_SRC = ROOT / "normalizedvector.proto"
PROTO_BUILD = ROOT / "TekHighspeedServer.proto"
OUT_DIR = ROOT / "src" / "tekhsi"
STUB_BASE = "_tek_highspeed_server_pb2"


def main() -> int:
    shutil.copy2(PROTO_SRC, PROTO_BUILD)
    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{ROOT}",
        f"--python_out={OUT_DIR}",
        f"--grpc_python_out={OUT_DIR}",
        f"--pyi_out={OUT_DIR}",
        PROTO_BUILD.name,
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)

    for suffix in (".py", "_grpc.py", ".pyi"):
        generated = OUT_DIR / f"TekHighspeedServer_pb2{suffix}"
        target = OUT_DIR / f"{STUB_BASE}{suffix}"
        generated.replace(target)

    grpc_file = OUT_DIR / f"{STUB_BASE}_grpc.py"
    text = grpc_file.read_text(encoding="utf-8")
    text = text.replace(
        "import TekHighspeedServer_pb2 as TekHighspeedServer__pb2",
        "import tekhsi._tek_highspeed_server_pb2 as TekHighspeedServer__pb2",
    )
    grpc_file.write_text(text, encoding="utf-8")
    PROTO_BUILD.unlink(missing_ok=True)
    print(f"Generated stubs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
