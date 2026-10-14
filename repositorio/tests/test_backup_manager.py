"""Unit tests for source/backup_manager.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.backup_manager import (
    BackupCreationError,
    BackupIntegrityError,
    BackupManager,
    calculate_sha256,
)


class TestBackupManager(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_dir.name)
        self.backup_dir = self.root_path / "backups"
        self.manager = BackupManager(backup_dir=self.backup_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_and_verify_single_file_backup(self) -> None:
        """Tests backup creation and verification for a single RPO repository file."""
        rpo_file = self.root_path / "ttm.rpo"
        rpo_file.write_bytes(b"TOTVS RPO REPOSITORY BINARY CONTENT DATA 12345")

        metadata = self.manager.create_backup(
            source_paths=[rpo_file],
            prefix="rpo_snapshot",
        )

        self.assertTrue(metadata.archive_path.exists())
        self.assertEqual(metadata.files_count, 1)
        self.assertEqual(metadata.total_size_bytes, len(rpo_file.read_bytes()))
        self.assertTrue(metadata.backup_id.startswith("rpo_snapshot_"))
        self.assertEqual(metadata.sha256, calculate_sha256(metadata.archive_path))

        # Verify integrity
        self.assertTrue(self.manager.verify_backup(metadata.archive_path))

    def test_create_backup_directory_tree(self) -> None:
        """Tests backup of directory tree containing multiple files."""
        repo_dir = self.root_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "custom.rpo").write_text("custom rpo code")
        sub_dir = repo_dir / "sub"
        sub_dir.mkdir()
        (sub_dir / "config.ini").write_text("server=localhost\nport=1234")

        metadata = self.manager.create_backup(source_paths=[repo_dir])

        self.assertEqual(metadata.files_count, 2)
        self.assertTrue(metadata.archive_path.exists())

    def test_restore_backup_to_original_path_rollback(self) -> None:
        """Tests rollback scenario: original file is changed/corrupted and restored."""
        target_file = self.root_path / "production.rpo"
        target_file.write_text("ORIGINAL CLEAN PRODUCTION REPOSITORY")

        # Create backup snapshot
        metadata = self.manager.create_backup(source_paths=[target_file])

        # Simulate corruptive patch or modification
        target_file.write_text("CORRUPTED MODIFIED CONTENT BY FAILED PATCH")
        self.assertEqual(target_file.read_text(), "CORRUPTED MODIFIED CONTENT BY FAILED PATCH")

        # Rollback / restore
        restored = self.manager.restore_backup(metadata.archive_path)

        self.assertEqual(len(restored), 1)
        self.assertEqual(target_file.read_text(), "ORIGINAL CLEAN PRODUCTION REPOSITORY")

    def test_restore_backup_to_target_dir(self) -> None:
        """Tests extracting backup contents into a separate destination directory."""
        src_file = self.root_path / "source.txt"
        src_file.write_text("Hello backup world")

        metadata = self.manager.create_backup(source_paths=[src_file])

        restore_dest = self.root_path / "restored_folder"
        restored = self.manager.restore_backup(
            metadata.archive_path,
            target_dir=restore_dest,
        )

        self.assertEqual(len(restored), 1)
        expected_file = restore_dest / "source.txt"
        self.assertTrue(expected_file.exists())
        self.assertEqual(expected_file.read_text(), "Hello backup world")

    def test_create_backup_non_existent_source_raises_error(self) -> None:
        non_existent = self.root_path / "does_not_exist.rpo"
        with self.assertRaises(BackupCreationError):
            self.manager.create_backup(source_paths=[non_existent])

    def test_create_backup_empty_paths_raises_error(self) -> None:
        with self.assertRaises(BackupCreationError):
            self.manager.create_backup(source_paths=[])

    def test_verify_non_existent_archive_raises_error(self) -> None:
        with self.assertRaises(BackupIntegrityError):
            self.manager.verify_backup(self.root_path / "ghost.zip")

    def test_verify_corrupted_archive_raises_error(self) -> None:
        corrupt_zip = self.backup_dir / "corrupted.zip"
        corrupt_zip.write_bytes(b"PK\x03\x04this is not a valid zip archive header")

        with self.assertRaises(BackupIntegrityError):
            self.manager.verify_backup(corrupt_zip)

    def test_list_backups_sorted(self) -> None:
        src = self.root_path / "item.txt"
        src.write_text("data")

        m1 = self.manager.create_backup([src], prefix="b1")
        m2 = self.manager.create_backup([src], prefix="b2")

        backups = self.manager.list_backups()
        self.assertGreaterEqual(len(backups), 2)
        # Should contain both created archives
        archive_names = [p.name for p in backups]
        self.assertIn(m1.archive_path.name, archive_names)
        self.assertIn(m2.archive_path.name, archive_names)


if __name__ == "__main__":
    unittest.main()
