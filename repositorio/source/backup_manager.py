"""Backup management module for ERP repositories and RPO snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


class BackupError(Exception):
    """Base exception for backup operations."""


class BackupCreationError(BackupError):
    """Raised when backup creation fails."""


class BackupRestoreError(BackupError):
    """Raised when backup restoration fails."""


class BackupIntegrityError(BackupError):
    """Raised when backup archive or manifest integrity check fails."""


@dataclass(frozen=True)
class BackupMetadata:
    """Metadata describing a created backup archive."""

    backup_id: str
    created_at: str
    archive_path: Path
    source_paths: list[str]
    files_count: int
    total_size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, str | int | list[str]]:
        data = asdict(self)
        data["archive_path"] = str(self.archive_path)
        return data


def calculate_sha256(file_path: Path) -> str:
    """Calculates SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as fp:
        while chunk := fp.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class BackupManager:
    """Manages compressed snapshots and restorations for ERP files and repositories."""

    MANIFEST_FILENAME = "backup_manifest.json"

    def __init__(self, backup_dir: str | Path = "C:/hoshu/backups") -> None:
        self.backup_dir = Path(backup_dir).resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(
        self,
        source_paths: Sequence[str | Path],
        prefix: str = "backup",
    ) -> BackupMetadata:
        """Creates a timestamped, compressed zip backup of the specified files or directories.

        Args:
            source_paths: List of file or directory paths to include in the backup.
            prefix: Filename prefix for the backup archive.

        Returns:
            BackupMetadata describing the generated backup.

        Raises:
            BackupCreationError: If paths do not exist or creation fails.
        """
        if not source_paths:
            raise BackupCreationError("Cannot create backup: No source paths provided.")

        resolved_sources: list[Path] = []
        for src in source_paths:
            p = Path(src).resolve()
            if not p.exists():
                raise BackupCreationError(f"Source path does not exist: {p}")
            resolved_sources.append(p)

        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        backup_id = f"{prefix}_{timestamp_str}"
        archive_path = self.backup_dir / f"{backup_id}.zip"

        files_to_pack: list[tuple[Path, str, str]] = []  # (absolute_path, arcname, original_str)
        total_size = 0

        for src in resolved_sources:
            if src.is_file():
                arcname = src.name
                files_to_pack.append((src, arcname, str(src)))
                total_size += src.stat().st_size
            elif src.is_dir():
                base_dir_name = src.name
                for root, _, filenames in os.walk(src):
                    for fname in filenames:
                        file_path = Path(root) / fname
                        rel_path = file_path.relative_to(src)
                        arcname = str(Path(base_dir_name) / rel_path).replace("\\", "/")
                        files_to_pack.append((file_path, arcname, str(file_path)))
                        total_size += file_path.stat().st_size

        if not files_to_pack:
            raise BackupCreationError(
                f"No files found to backup in specified source paths: {[str(p) for p in resolved_sources]}"
            )

        manifest_data = {
            "backup_id": backup_id,
            "created_at": now.isoformat(),
            "prefix": prefix,
            "source_paths": [str(p) for p in resolved_sources],
            "files": [
                {
                    "arcname": arcname,
                    "original_path": orig,
                    "size_bytes": abs_path.stat().st_size,
                    "sha256": calculate_sha256(abs_path),
                }
                for abs_path, arcname, orig in files_to_pack
            ],
        }

        # Create temporary archive first to ensure atomic completion
        temp_archive_path = self.backup_dir / f"{backup_id}.tmp.zip"

        try:
            with zipfile.ZipFile(
                temp_archive_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
            ) as zip_file:
                # Write manifest
                zip_file.writestr(
                    self.MANIFEST_FILENAME,
                    json.dumps(manifest_data, indent=2),
                )
                # Write files
                for abs_path, arcname, _ in files_to_pack:
                    zip_file.write(abs_path, arcname=arcname)

            # Atomic rename to final archive
            temp_archive_path.replace(archive_path)

        except Exception as exc:
            if temp_archive_path.exists():
                temp_archive_path.unlink(missing_ok=True)
            raise BackupCreationError(f"Failed to create backup archive: {exc}") from exc

        archive_sha256 = calculate_sha256(archive_path)

        return BackupMetadata(
            backup_id=backup_id,
            created_at=now.isoformat(),
            archive_path=archive_path,
            source_paths=[str(p) for p in resolved_sources],
            files_count=len(files_to_pack),
            total_size_bytes=total_size,
            sha256=archive_sha256,
        )

    def verify_backup(self, archive_path: str | Path) -> bool:
        """Verifies zip file integrity and manifest structure.

        Args:
            archive_path: Path to the backup archive.

        Returns:
            True if archive is valid.

        Raises:
            BackupIntegrityError: If archive is corrupted or manifest is invalid.
        """
        path = Path(archive_path).resolve()
        if not path.is_file():
            raise BackupIntegrityError(f"Backup archive not found: {path}")

        try:
            with zipfile.ZipFile(path, mode="r") as zip_file:
                # Test CRC checksums of files
                bad_file = zip_file.testzip()
                if bad_file:
                    raise BackupIntegrityError(
                        f"Backup archive corrupted: file '{bad_file}' failed CRC check."
                    )

                namelist = zip_file.namelist()
                if self.MANIFEST_FILENAME not in namelist:
                    raise BackupIntegrityError(
                        f"Backup archive missing required manifest '{self.MANIFEST_FILENAME}'."
                    )

                manifest_raw = zip_file.read(self.MANIFEST_FILENAME).decode("utf-8")
                manifest = json.loads(manifest_raw)

                if "backup_id" not in manifest or "files" not in manifest:
                    raise BackupIntegrityError("Backup manifest has missing required fields.")

        except (zipfile.BadZipFile, json.JSONDecodeError, OSError) as exc:
            raise BackupIntegrityError(f"Failed verifying backup archive: {exc}") from exc

        return True

    def restore_backup(
        self,
        archive_path: str | Path,
        target_dir: str | Path | None = None,
        verify_checksums: bool = True,
    ) -> list[Path]:
        """Restores files from a backup archive.

        Args:
            archive_path: Path to the zip archive.
            target_dir: Optional destination directory. If None, restores files to
                        their original paths recorded in the manifest.
            verify_checksums: If True, validates extracted file hashes against manifest.

        Returns:
            List of restored file Paths.

        Raises:
            BackupRestoreError: If restoration fails.
            BackupIntegrityError: If archive or checksum validation fails.
        """
        self.verify_backup(archive_path)
        path = Path(archive_path).resolve()
        restored_files: list[Path] = []

        try:
            with zipfile.ZipFile(path, mode="r") as zip_file:
                manifest_raw = zip_file.read(self.MANIFEST_FILENAME).decode("utf-8")
                manifest = json.loads(manifest_raw)
                files_manifest = {f["arcname"]: f for f in manifest.get("files", [])}

                target_path = Path(target_dir).resolve() if target_dir else None

                for arcname, f_info in files_manifest.items():
                    if target_path:
                        dest_file = target_path / arcname
                    else:
                        dest_file = Path(f_info["original_path"]).resolve()

                    dest_file.parent.mkdir(parents=True, exist_ok=True)

                    # Extract file content
                    with zip_file.open(arcname, "r") as src_fp, dest_file.open("wb") as dst_fp:
                        shutil.copyfileobj(src_fp, dst_fp)

                    if verify_checksums:
                        extracted_hash = calculate_sha256(dest_file)
                        if extracted_hash != f_info["sha256"]:
                            raise BackupIntegrityError(
                                f"Restored file '{dest_file}' checksum mismatch! Expected "
                                f"{f_info['sha256']}, got {extracted_hash}."
                            )

                    restored_files.append(dest_file)

        except BackupError:
            raise
        except Exception as exc:
            raise BackupRestoreError(f"Failed restoring backup '{path}': {exc}") from exc

        return restored_files

    def list_backups(self) -> list[Path]:
        """Returns all backup zip archives in the backup directory, newest first."""
        if not self.backup_dir.exists():
            return []
        archives = [p for p in self.backup_dir.glob("*.zip") if not p.name.endswith(".tmp.zip")]
        return sorted(archives, key=lambda p: p.stat().st_mtime, reverse=True)
