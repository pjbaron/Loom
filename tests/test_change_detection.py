"""
Tests for change detection functionality.

Tests the ability to detect file changes since last ingest and
map those changes to affected entities and tests.
"""

import os
import tempfile
import time
import pytest
from pathlib import Path

from codestore import CodeStore


class TestFileTracking:
    """Tests for file mtime tracking during ingest."""

    def test_ingest_tracks_file_mtime(self, tmp_path):
        """Ingesting a file records its mtime."""
        # Create a test file
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Check file_tracking table has entry
        row = store.conn.execute(
            "SELECT * FROM file_tracking WHERE file_path = ?",
            (str(test_file),)
        ).fetchone()

        assert row is not None
        assert row['mtime'] > 0
        assert row['size'] > 0

    def test_ingest_tracks_entity_file_mapping(self, tmp_path):
        """Ingesting creates entity-to-file mappings."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass\ndef bar(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Check entity_files table
        rows = store.conn.execute(
            "SELECT * FROM entity_files WHERE file_path = ?",
            (str(test_file),)
        ).fetchall()

        # Should have 3 entries: module + 2 functions
        assert len(rows) == 3

    def test_ingest_creates_ingest_run(self, tmp_path):
        """Ingesting creates an ingest_run record."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Check ingest_runs table
        row = store.conn.execute(
            "SELECT * FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()

        assert row is not None
        assert row['status'] == 'completed'
        assert row['paths'] is not None

    def test_get_latest_ingest_run(self, tmp_path):
        """get_latest_ingest_run returns the most recent run."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        run = store.get_latest_ingest_run()

        assert run is not None
        assert run['status'] == 'completed'
        assert str(tmp_path) in run['paths']


class TestGetChangedFiles:
    """Tests for get_changed_files() method."""

    def test_no_changes_returns_empty(self, tmp_path):
        """When no files changed, returns empty list."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        changes = store.get_changed_files()
        assert changes == []

    def test_detects_modified_file(self, tmp_path):
        """Detects when a file has been modified."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Modify the file (need to wait for mtime to change)
        time.sleep(0.1)
        test_file.write_text("def foo(): return 42")

        changes = store.get_changed_files()

        assert len(changes) == 1
        assert changes[0][0] == str(test_file)
        assert changes[0][1] == 'modified'

    def test_detects_deleted_file(self, tmp_path):
        """Detects when a file has been deleted."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Delete the file
        test_file.unlink()

        changes = store.get_changed_files()

        assert len(changes) == 1
        assert changes[0][0] == str(test_file)
        assert changes[0][1] == 'deleted'

    def test_detects_added_file(self, tmp_path):
        """Detects when a new file is added to tracked directory."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Add a new file
        new_file = tmp_path / "new_module.py"
        new_file.write_text("def bar(): pass")

        changes = store.get_changed_files()

        assert len(changes) == 1
        assert changes[0][0] == str(new_file)
        assert changes[0][1] == 'added'

    def test_multiple_changes(self, tmp_path):
        """Detects multiple types of changes at once."""
        file1 = tmp_path / "module1.py"
        file2 = tmp_path / "module2.py"
        file1.write_text("def foo(): pass")
        file2.write_text("def bar(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Modify one, delete one, add one
        time.sleep(0.1)
        file1.write_text("def foo(): return 1")
        file2.unlink()
        file3 = tmp_path / "module3.py"
        file3.write_text("def baz(): pass")

        changes = store.get_changed_files()

        assert len(changes) == 3
        change_dict = {fp: ct for fp, ct in changes}
        assert change_dict[str(file1)] == 'modified'
        assert change_dict[str(file2)] == 'deleted'
        assert change_dict[str(file3)] == 'added'


class TestGetChangedEntities:
    """Tests for get_changed_entities() method."""

    def test_returns_entities_in_modified_file(self, tmp_path):
        """Returns entities defined in modified files."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass\ndef bar(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Modify the file
        time.sleep(0.1)
        test_file.write_text("def foo(): return 1\ndef bar(): return 2")

        entities = store.get_changed_entities()

        # Should have module + 2 functions
        assert len(entities) >= 2
        assert all(e['change_type'] == 'modified' for e in entities)

    def test_returns_entities_in_deleted_file(self, tmp_path):
        """Returns entities that were in deleted files."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Delete the file
        test_file.unlink()

        entities = store.get_changed_entities()

        # Should mark entities as deleted
        assert len(entities) >= 1
        assert all(e['change_type'] == 'deleted' for e in entities)

    def test_empty_when_no_changes(self, tmp_path):
        """Returns empty list when no files changed."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        entities = store.get_changed_entities()
        assert entities == []


class TestGetImpactedTests:
    """Tests for get_impacted_tests() method."""

    def test_finds_tests_for_changed_entities(self, tmp_path):
        """Finds tests that reference changed entities."""
        # Create source file
        src_file = tmp_path / "calculator.py"
        src_file.write_text("""
def add(a, b):
    '''Add two numbers.'''
    return a + b
""")

        # Create test file
        test_file = tmp_path / "test_calculator.py"
        test_file.write_text("""
from calculator import add

def test_add():
    assert add(1, 2) == 3
""")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Modify the source file
        time.sleep(0.1)
        src_file.write_text("""
def add(a, b):
    '''Add two numbers with better handling.'''
    return int(a) + int(b)
""")

        changed_entities = store.get_changed_entities()
        impacted_tests = store.get_impacted_tests(changed_entities)

        # Should find test_calculator
        assert len(impacted_tests) > 0
        assert any('test_calculator' in test for test in impacted_tests)

    def test_returns_empty_for_no_changes(self, tmp_path):
        """Returns empty list when no entities changed."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # No changes
        impacted = store.get_impacted_tests()
        assert impacted == []

    def test_deduplicates_tests(self, tmp_path):
        """Returns unique test entries even when multiple entities reference same test."""
        # Create source with multiple functions
        src_file = tmp_path / "math_ops.py"
        src_file.write_text("""
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
""")

        # Create test file that tests both
        test_file = tmp_path / "test_math.py"
        test_file.write_text("""
from math_ops import add, subtract

def test_add():
    assert add(1, 2) == 3

def test_subtract():
    assert subtract(5, 3) == 2
""")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        # Modify source
        time.sleep(0.1)
        src_file.write_text("""
def add(a, b):
    return int(a) + int(b)

def subtract(a, b):
    return int(a) - int(b)
""")

        changed = store.get_changed_entities()
        impacted = store.get_impacted_tests(changed)

        # Should be deduplicated
        test_math_count = sum(1 for t in impacted if 'test_math' in t)
        assert test_math_count <= 1


class TestIngestRunTracking:
    """Tests for ingest run lifecycle."""

    def test_ingest_run_has_correct_status(self, tmp_path):
        """Ingest run ends with correct status."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        run = store.get_latest_ingest_run()
        assert run['status'] == 'completed'
        assert run['ended_at'] is not None

    def test_ingest_run_tracks_stats(self, tmp_path):
        """Ingest run records statistics."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo(): pass\nclass Bar: pass")

        store = CodeStore()
        store.ingest_files(str(tmp_path))

        run = store.get_latest_ingest_run()
        stats = run['stats']

        assert stats['modules'] == 1
        assert stats['functions'] == 1
        assert stats['classes'] == 1

    def test_failed_ingest_marks_run_failed(self, tmp_path):
        """Failed ingest marks run as failed."""
        store = CodeStore()

        # Try to ingest nonexistent path
        try:
            store.ingest_files("/nonexistent/path")
        except ValueError:
            pass

        run = store.get_latest_ingest_run()
        assert run['status'] == 'failed'


class TestSchemaVersion:
    """Tests for schema migration."""

    def test_schema_version_is_3(self):
        """Database has schema version 3."""
        store = CodeStore()
        version = store._get_schema_version()
        assert version == 3

    def test_file_tracking_table_exists(self):
        """file_tracking table exists."""
        store = CodeStore()
        row = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='file_tracking'"
        ).fetchone()
        assert row is not None

    def test_ingest_runs_table_exists(self):
        """ingest_runs table exists."""
        store = CodeStore()
        row = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ingest_runs'"
        ).fetchone()
        assert row is not None

    def test_entity_files_table_exists(self):
        """entity_files table exists."""
        store = CodeStore()
        row = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entity_files'"
        ).fetchone()
        assert row is not None
