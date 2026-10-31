"""Lossless bounded rotation of the CFD lab JSONL before a Git checkpoint.

The active log stays small; immutable numbered archives retain all historical
observations in order. This changes storage only, not strategy or execution.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "state" / "cfd_lab_observations.jsonl"
ROTATE_AT = 12 * 1024 * 1024
CHUNK_MAX = 8 * 1024 * 1024
PREFIX = "cfd_lab_observations_archive_"


def _write_atomic(destination: Path, payload: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".lab-rotation-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, destination)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def rotate(path: Path = ACTIVE) -> dict:
    if not path.exists() or path.stat().st_size <= ROTATE_AT:
        return {"rotated": False}
    archives = sorted(path.parent.glob(PREFIX + "*.jsonl"))
    numbers = []
    for item in archives:
        suffix = item.stem.removeprefix(PREFIX)
        if suffix.isdecimal():
            numbers.append(int(suffix))
    next_number = max(numbers, default=0) + 1
    original_size = path.stat().st_size
    original_hash = hashlib.sha256()
    pieces = []
    pending = bytearray()
    with path.open("rb") as source:
        for line in source:
            if len(line) > CHUNK_MAX:
                raise ValueError("A single lab JSONL line exceeds archive chunk limit")
            original_hash.update(line)
            if len(pending) + len(line) > CHUNK_MAX:
                if not pending:
                    raise AssertionError("Empty archive chunk")
                dest = path.parent / f"{PREFIX}{next_number:06d}.jsonl"
                if dest.exists():
                    raise FileExistsError(dest)
                _write_atomic(dest, bytes(pending))
                pieces.append(dest)
                next_number += 1
                pending.clear()
            pending.extend(line)
    if not pieces:
        return {"rotated": False}
    # Check the exact byte stream before replacing the active file.
    verify_hash = hashlib.sha256()
    verify_size = 0
    for part in pieces:
        with part.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                verify_hash.update(chunk)
                verify_size += len(chunk)
    verify_hash.update(pending)
    verify_size += len(pending)
    if verify_size != original_size or verify_hash.digest() != original_hash.digest():
        raise RuntimeError("Lab rotation verification failed; active log unchanged")
    _write_atomic(path, bytes(pending))
    return {
        "rotated": True,
        "archives_created": len(pieces),
        "original_bytes": original_size,
        "active_bytes": len(pending),
        "sha256": original_hash.hexdigest(),
    }


if __name__ == "__main__":
    print(rotate())
