"""Working-directory snapshots (with a sha256 manifest) and restore."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import UsageError

BACKUP_FORMAT = "lightrag-dedupe/backup@1"
MANIFEST = "manifest.json"
DATA_DIR = "data"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def default_backup_root(working_dir: Path) -> Path:
    """``<working_dir>.lightrag-dedupe-backups`` next to the working directory."""
    wd = working_dir.resolve()
    return wd.parent / f"{wd.name}.lightrag-dedupe-backups"


def _files(root: Path, skip: Path | None) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if skip is not None and skip in p.parents:
            continue
        out.append(p)
    return out


def create_backup(working_dir: str | Path, backup_root: str | Path | None = None) -> Path:
    """Copy every file of ``working_dir`` into a new time-stamped folder and write a manifest.

    Returns:
        The backup folder (pass it to :func:`restore_backup`).

    Raises:
        UsageError: ``working_dir`` is not a directory.
    """
    wd = Path(working_dir).resolve()
    if not wd.is_dir():
        raise UsageError("err.backup_no_dir", path=str(wd))
    root = Path(backup_root).resolve() if backup_root else default_backup_root(wd)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = root / stamp
    n = 1
    while dest.exists():
        n += 1
        dest = root / f"{stamp}-{n}"
    skip = root if wd in root.parents else None
    files: dict[str, str] = {}
    for src in _files(wd, skip):
        rel = src.relative_to(wd).as_posix()
        target = dest / DATA_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        files[rel] = _sha256(target)
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {"format": BACKUP_FORMAT, "source": str(wd), "files": files}
    (dest / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def read_manifest(backup_dir: str | Path) -> dict:
    p = Path(backup_dir) / MANIFEST
    if not p.is_file():
        raise UsageError("err.backup_manifest_missing", path=str(backup_dir))
    try:
        manifest = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise UsageError("err.backup_manifest_invalid", path=str(p), detail=str(exc)) from exc
    if manifest.get("format") != BACKUP_FORMAT or not isinstance(manifest.get("files"), dict):
        raise UsageError("err.backup_manifest_invalid", path=str(p), detail="format")
    return manifest


@dataclass(frozen=True)
class RestoreResult:
    working_dir: Path
    restored: int
    extra: list[str]  # files in the working dir that the backup does not know about
    pruned: bool


def restore_backup(
    backup_dir: str | Path,
    working_dir: str | Path | None = None,
    prune: bool = False,
) -> RestoreResult:
    """Verify every file against the manifest, then copy the snapshot back.

    Files created after the snapshot are left alone unless ``prune`` is true.

    Raises:
        UsageError: manifest missing or invalid, a backup file does not match its sha256,
            or no target directory is known.
    """
    bdir = Path(backup_dir)
    manifest = read_manifest(bdir)
    source = working_dir or manifest.get("source", "")
    if not source:
        raise UsageError("err.restore_no_target")
    target = Path(source).resolve()
    for rel, sha in manifest["files"].items():
        src = bdir / DATA_DIR / rel
        if not src.is_file() or _sha256(src) != sha:
            raise UsageError("err.backup_corrupt", name=rel)
    target.mkdir(parents=True, exist_ok=True)
    for rel in manifest["files"]:
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bdir / DATA_DIR / rel, dst)
    known = set(manifest["files"])
    extra = [p.relative_to(target).as_posix() for p in _files(target, None)]
    extra = [e for e in extra if e not in known]
    if prune:
        for rel in extra:
            (target / rel).unlink()
    return RestoreResult(target, len(known), extra, prune)
