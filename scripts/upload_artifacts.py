#!/usr/bin/env python3
"""
upload_artifacts.py
===================

Erzeugt ein manifest.json und lädt alle DEMs + Masken auf einen Webspace hoch,
der per FTP, SFTP oder rsync erreichbar ist.

Verwendung:
    python scripts/upload_artifacts.py --protocol sftp \\
        --host ftp.example.de --user u12345 --remote-dir /flood-models \\
        --password "$(cat ~/.flood_pw)"

    # oder per rsync (am einfachsten):
    python scripts/upload_artifacts.py --protocol rsync \\
        --host user@webspace.example.de:/path/to/flood-models

    # oder mit lokalem Verzeichnis (zum Testen):
    python scripts/upload_artifacts.py --protocol local \\
        --local-target /tmp/flood-models-upload

Das Skript:
1. Sammelt alle Dateien unter ./dem-src/ und ./flood-masks/
2. Schreibt manifest.json mit SHA256-Hashes + Größen
3. Lädt alles auf das Ziel hoch
4. Bei erneutem Lauf: inkrementelles Hochladen (nur neue/geänderte Dateien)

Konfiguration per .env-Datei möglich:
    FLOOD_UPLOAD_HOST=...
    FLOOD_UPLOAD_USER=...
    FLOOD_UPLOAD_PASSWORD=...
    FLOOD_UPLOAD_REMOTE_DIR=/flood-models
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

try:
    import paramiko  # für SFTP
except ImportError:
    paramiko = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


REPO_ROOT = Path(__file__).resolve().parent.parent
DEM_DIR = REPO_ROOT / "dem-src"
MASK_DIR = REPO_ROOT / "flood-masks"
MANIFEST_NAME = "manifest.json"


# ----- Helpers ----------------------------------------------------------------

def sha256_of(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def gather_artifacts() -> list[Path]:
    files: list[Path] = []
    for root in (DEM_DIR, MASK_DIR):
        if root.exists():
            files.extend(sorted(p for p in root.rglob("*") if p.is_file()))
    return files


def build_manifest(files: Iterable[Path]) -> dict:
    entries = []
    total_bytes = 0
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        size = path.stat().st_size
        total_bytes += size
        entries.append({
            "path": rel,
            "size": size,
            "sha256": sha256_of(path),
        })
    return {
        "version": 1,
        "generator": "upload_artifacts.py",
        "files": entries,
        "total_bytes": total_bytes,
        "count": len(entries),
    }


def write_manifest(manifest: dict, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / MANIFEST_NAME
    with target.open("w") as f:
        json.dump(manifest, f, indent=2)
    return target


# ----- Upload-Strategien ------------------------------------------------------

def upload_local(staging_dir: Path, files: list[Path]) -> None:
    """Kopiert alles in ein lokales Verzeichnis (zum Testen)."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    for src in files:
        rel = src.relative_to(REPO_ROOT)
        dst = staging_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f"✅ Lokal kopiert nach {staging_dir}")


def upload_rsync(remote_target: str, files: list[Path], manifest_path: Path) -> None:
    """
    remote_target Beispiel: 'user@host:/path/to/flood-models'
    rsync überträgt alles in einem Rutsch; --checksum prüft Inhaltsgleichheit.
    """
    # wir packen alles in ein temporäres Staging-Dir, das die Zielstruktur spiegelt
    staging = Path("/tmp/flood-models-staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for src in files:
        rel = src.relative_to(REPO_ROOT)
        dst = staging / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copy2(manifest_path, staging / MANIFEST_NAME)

    cmd = [
        "rsync", "-av", "--checksum", "--progress",
        f"{staging}/", f"{remote_target}/",
    ]
    print("→", " ".join(cmd))
    subprocess.run(cmd, check=True)
    shutil.rmtree(staging, ignore_errors=True)


def upload_sftp(host: str, user: str, password: str,
                remote_dir: str, files: list[Path],
                manifest_path: Path) -> None:
    if paramiko is None:
        sys.exit("SFTP benötigt 'pip install paramiko'")
    transport = paramiko.Transport((host, 22))
    transport.connect(username=user, password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    try:
        sftp.chdir(remote_dir)
    except IOError:
        # anlegen
        for part in remote_dir.strip("/").split("/"):
            try:
                sftp.chdir(part)
            except IOError:
                sftp.mkdir(part)
                sftp.chdir(part)

    all_files = list(files) + [manifest_path]
    for src in all_files:
        rel = src.relative_to(REPO_ROOT).as_posix() if src != manifest_path else MANIFEST_NAME
        # Verzeichnisstruktur anlegen
        parts = rel.split("/")
        for i in range(1, len(parts)):
            sub = "/".join(parts[:i])
            try:
                sftp.stat(sub)
            except IOError:
                sftp.mkdir(sub)
        sftp.put(str(src), rel)
        print(f"  uploaded: {rel} ({src.stat().st_size:,} bytes)")

    sftp.close()
    transport.close()


def upload_ftp(host: str, user: str, password: str,
               remote_dir: str, files: list[Path],
               manifest_path: Path) -> None:
    from ftplib import FTP, error_perm
    ftp = FTP(host)
    ftp.login(user, password)

    def ensure_dir(path: str):
        try:
            ftp.cwd(path)
        except error_perm:
            ftp.mkd(path)
            ftp.cwd(path)

    for part in remote_dir.strip("/").split("/"):
        if part:
            ensure_dir(part)

    all_files = list(files) + [manifest_path]
    for src in all_files:
        rel = src.relative_to(REPO_ROOT).as_posix() if src != manifest_path else MANIFEST_NAME
        # Pfad-Komponenten einzeln anlegen
        parts = rel.split("/")
        cwd = remote_dir
        for p in parts[:-1]:
            cwd = f"{cwd}/{p}"
            ensure_dir(cwd.lstrip("/"))
        with src.open("rb") as f:
            ftp.storbinary(f"STOR {rel}", f)
        print(f"  uploaded: {rel} ({src.stat().st_size:,} bytes)")

    ftp.quit()


# ----- Main -------------------------------------------------------------------

def main() -> int:
    if load_dotenv is not None:
        load_dotenv(REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--protocol", choices=("local", "rsync", "sftp", "ftp"), default="rsync")
    parser.add_argument("--host", default=os.environ.get("FLOOD_UPLOAD_HOST"))
    parser.add_argument("--user", default=os.environ.get("FLOOD_UPLOAD_USER"))
    parser.add_argument("--password", default=os.environ.get("FLOOD_UPLOAD_PASSWORD"))
    parser.add_argument("--remote-dir", default=os.environ.get("FLOOD_UPLOAD_REMOTE_DIR", "/flood-models"))
    parser.add_argument("--rsync-target", default=os.environ.get("FLOOD_UPLOAD_RSYNC"),
                        help="z.B. 'user@host:/path/to/flood-models'")
    parser.add_argument("--local-target", help="für --protocol local")
    args = parser.parse_args()

    files = gather_artifacts()
    if not files:
        sys.exit(f"Keine Artefakte unter {DEM_DIR} oder {MASK_DIR} gefunden.")

    total_mb = sum(p.stat().st_size for p in files) / 1024 / 1024
    print(f"Gefunden: {len(files)} Dateien, {total_mb:.1f} MB")

    manifest = build_manifest(files)
    manifest_path = REPO_ROOT / MANIFEST_NAME
    write_manifest(manifest, REPO_ROOT)
    print(f"Manifest geschrieben: {manifest_path} ({manifest['count']} Dateien, "
          f"{manifest['total_bytes'] / 1024 / 1024:.1f} MB)")

    if args.protocol == "local":
        if not args.local_target:
            sys.exit("--local-target fehlt")
        upload_local(Path(args.local_target), files + [manifest_path])
    elif args.protocol == "rsync":
        if not args.rsync_target:
            sys.exit("--rsync-target fehlt (z.B. user@host:/pfad)")
        upload_rsync(args.rsync_target, files, manifest_path)
    elif args.protocol == "sftp":
        if not (args.host and args.user and args.password):
            sys.exit("--host/--user/--password fehlen für SFTP")
        upload_sftp(args.host, args.user, args.password, args.remote_dir, files, manifest_path)
    elif args.protocol == "ftp":
        if not (args.host and args.user and args.password):
            sys.exit("--host/--user/--password fehlen für FTP")
        upload_ftp(args.host, args.user, args.password, args.remote_dir, files, manifest_path)

    print("\n✅ Fertig. Setze auf Render die Env-Variable:")
    print(f"   FLOOD_REMOTE_BASE_URL=https://<dein-space>/flood-models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
