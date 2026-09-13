#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path


CODE = Path(__file__).resolve().parents[1]
TARGET = CODE / "evaluation" / "source_manifest.sha256"
EXCLUDED = {TARGET, CODE / "evaluation" / "latest_quality.json"}


def main() -> int:
    lines = []
    for path in sorted(CODE.rglob("*")):
        if not path.is_file() or path in EXCLUDED or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(CODE).as_posix()}")
    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} source checksums to {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
