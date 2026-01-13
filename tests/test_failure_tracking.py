"""
Tests for failure tracking feature.

Tests cover:
1. Database operations: log_failure(), get_failure_logs(), get_recent_failures(),
   delete_failure_log(), clear_old_failures()
2. Integration: Entity name resolution, multiple tags, empty/None filters, limit parameter
3. Edge cases: Logging without optional fields, querying with no results,
   deleting non-existent logs
"""

import pytest
from pathlib import Path
from datetime import datetime, timedelta
from codestore import CodeStore


@pytest.fixture
def temp_store(tmp_path):
    """Create a temporary CodeStore for testing."""
    db_path = tmp_path / "test.db"
    store = CodeStore(str(db_path))
    yield store
    store.close()


# =============================================================================
# Basic Database Operations
# =============================================================================

def test_log_failure_minimal(temp_store):
    """Test logging with just required field."""
    log_id = temp_store.log_failure("Tried approach X")
    assert log_id > 0

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    assert logs[0]['attempted_fix'] == "Tried approach X"


def test_log_failure_full(temp_store):
    """Test logging with all fields."""
    log_id = temp_store.log_failure(
        attempted_fix="Used .get()",
        context="KeyError fix",
        entity_name="process_data",
        file_path="processor.py",
        failure_reason="Still crashes",
        related_error="KeyError: 'missing_key'",
        tags=["bug", "keyerror"]
    )
    assert log_id > 0

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    log = logs[0]
    assert log['attempted_fix'] == "Used .get()"
    assert log['context'] == "KeyError fix"
    assert log['file_path'] == "processor.py"
    assert log['failure_reason'] == "Still crashes"
    assert log['related_error'] == "KeyError: 'missing_key'"
    assert "bug" in log['tags']
    assert "keyerror" in log['tags']


def test_log_failure_returns_incremental_ids(temp_store):
    """Test that log IDs are incremental."""
    id1 = temp_store.log_failure("First fix")
    id2 = temp_store.log_failure("Second fix")
    id3 = temp_store.log_failure("Third fix")

    assert id2 > id1
    assert id3 > id2


def test_log_failure_with_entity_name_only(temp_store):
    """Test logging with entity name but without entity_id."""
    log_id = temp_store.log_failure(
        attempted_fix="Refactored function",
        entity_name="my_function"
    )
    assert log_id > 0

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    assert logs[0]['entity_name'] == "my_function"


def test_log_failure_timestamp_is_set(temp_store):
    """Test that timestamp is automatically set."""
    log_id = temp_store.log_failure("Test fix")

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    # Timestamp should be a valid ISO format string
    timestamp = logs[0]['timestamp']
    assert timestamp is not None
    # Should be parseable
    datetime.fromisoformat(timestamp)


# =============================================================================
# Filtering Tests
# =============================================================================

def test_filter_by_file(temp_store):
    """Test filtering by file path."""
    temp_store.log_failure("Fix 1", file_path="file_a.py")
    temp_store.log_failure("Fix 2", file_path="file_b.py")
    temp_store.log_failure("Fix 3", file_path="file_a.py")

    logs = temp_store.get_failure_logs(file_path="file_a.py")
    assert len(logs) == 2
    for log in logs:
        assert "file_a.py" in log['file_path']


def test_filter_by_file_partial_match(temp_store):
    """Test filtering by partial file path."""
    temp_store.log_failure("Fix 1", file_path="src/utils/file_a.py")
    temp_store.log_failure("Fix 2", file_path="src/utils/file_b.py")
    temp_store.log_failure("Fix 3", file_path="tests/file_a.py")

    # Partial match should work
    logs = temp_store.get_failure_logs(file_path="file_a")
    assert len(logs) == 2


def test_filter_by_entity(temp_store):
    """Test filtering by entity name."""
    temp_store.log_failure("Fix 1", entity_name="func_a")
    temp_store.log_failure("Fix 2", entity_name="func_b")

    logs = temp_store.get_failure_logs(entity_name="func_a")
    assert len(logs) == 1
    assert logs[0]['entity_name'] == "func_a"


def test_filter_by_entity_partial_match(temp_store):
    """Test filtering by partial entity name."""
    temp_store.log_failure("Fix 1", entity_name="MyClass.method_a")
    temp_store.log_failure("Fix 2", entity_name="MyClass.method_b")
    temp_store.log_failure("Fix 3", entity_name="OtherClass.method_a")

    logs = temp_store.get_failure_logs(entity_name="MyClass")
    assert len(logs) == 2


def test_filter_by_tags(temp_store):
    """Test filtering by tags."""
    temp_store.log_failure("Fix 1", tags=["bug"])
    temp_store.log_failure("Fix 2", tags=["performance"])
    temp_store.log_failure("Fix 3", tags=["bug", "critical"])

    logs = temp_store.get_failure_logs(tags=["bug"])
    assert len(logs) == 2


def test_filter_by_multiple_tags(temp_store):
    """Test filtering by multiple tags (OR logic)."""
    temp_store.log_failure("Fix 1", tags=["bug"])
    temp_store.log_failure("Fix 2", tags=["performance"])
    temp_store.log_failure("Fix 3", tags=["critical"])
    temp_store.log_failure("Fix 4", tags=["bug", "critical"])

    # Should match logs with either "bug" OR "performance"
    logs = temp_store.get_failure_logs(tags=["bug", "performance"])
    assert len(logs) == 3


def test_filter_by_context_search(temp_store):
    """Test filtering by context search."""
    temp_store.log_failure("Fix 1", context="Working on authentication")
    temp_store.log_failure("Fix 2", context="Working on database")
    temp_store.log_failure("Fix database query", context="Other context")

    logs = temp_store.get_failure_logs(context_search="database")
    assert len(logs) == 2


def test_filter_combined(temp_store):
    """Test combining multiple filters."""
    temp_store.log_failure("Fix 1", file_path="auth.py", entity_name="login", tags=["bug"])
    temp_store.log_failure("Fix 2", file_path="auth.py", entity_name="logout", tags=["bug"])
    temp_store.log_failure("Fix 3", file_path="db.py", entity_name="query", tags=["bug"])

    # Combine file_path and entity_name filters
    logs = temp_store.get_failure_logs(file_path="auth.py", entity_name="login")
    assert len(logs) == 1
    assert logs[0]['attempted_fix'] == "Fix 1"


def test_filter_none_returns_all(temp_store):
    """Test that no filters returns all logs."""
    temp_store.log_failure("Fix 1")
    temp_store.log_failure("Fix 2")
    temp_store.log_failure("Fix 3")

    logs = temp_store.get_failure_logs()
    assert len(logs) == 3


def test_limit_parameter(temp_store):
    """Test limit parameter works correctly."""
    for i in range(10):
        temp_store.log_failure(f"Fix {i}")

    logs = temp_store.get_failure_logs(limit=5)
    assert len(logs) == 5


def test_limit_default(temp_store):
    """Test default limit is 50."""
    for i in range(60):
        temp_store.log_failure(f"Fix {i}")

    logs = temp_store.get_failure_logs()
    assert len(logs) == 50


def test_results_ordered_by_timestamp_desc(temp_store):
    """Test results are ordered by timestamp descending (most recent first)."""
    import time

    temp_store.log_failure("First fix")
    time.sleep(0.01)  # Small delay to ensure different timestamps
    temp_store.log_failure("Second fix")
    time.sleep(0.01)
    temp_store.log_failure("Third fix")

    logs = temp_store.get_failure_logs()
    assert logs[0]['attempted_fix'] == "Third fix"
    assert logs[2]['attempted_fix'] == "First fix"


# =============================================================================
# Recent Failures Tests
# =============================================================================

def test_recent_failures(temp_store):
    """Test getting recent failures."""
    temp_store.log_failure("Recent fix")
    logs = temp_store.get_recent_failures(days=1)
    assert len(logs) >= 1


def test_recent_failures_limit(temp_store):
    """Test recent failures respects limit."""
    for i in range(30):
        temp_store.log_failure(f"Fix {i}")

    logs = temp_store.get_recent_failures(days=7, limit=10)
    assert len(logs) == 10


def test_recent_failures_time_window(temp_store):
    """Test recent failures time window filtering.

    Note: This test creates logs with current timestamp. To properly test
    the time window, we'd need to insert old timestamps directly or mock datetime.
    """
    # All logs created now should be within any reasonable time window
    temp_store.log_failure("Recent fix 1")
    temp_store.log_failure("Recent fix 2")

    # With 1 day window, both should appear
    logs = temp_store.get_recent_failures(days=1)
    assert len(logs) == 2

    # With 0 days should still work (same day)
    logs_zero = temp_store.get_recent_failures(days=0)
    # May or may not include depending on time precision
    # At minimum, should not error
    assert isinstance(logs_zero, list)


def test_recent_failures_with_old_record(temp_store):
    """Test that recent_failures excludes old records by inserting old timestamp directly."""
    # Insert a record with old timestamp directly
    old_timestamp = (datetime.utcnow() - timedelta(days=10)).isoformat()
    temp_store.conn.execute(
        """
        INSERT INTO failure_logs (timestamp, attempted_fix)
        VALUES (?, ?)
        """,
        (old_timestamp, "Old fix")
    )
    temp_store.conn.commit()

    # Insert a recent record
    temp_store.log_failure("Recent fix")

    # With 7 day window, only recent should appear
    logs = temp_store.get_recent_failures(days=7)
    assert len(logs) == 1
    assert logs[0]['attempted_fix'] == "Recent fix"


# =============================================================================
# Delete Tests
# =============================================================================

def test_delete_failure_log(temp_store):
    """Test deleting a failure log."""
    log_id = temp_store.log_failure("To be deleted")
    assert temp_store.delete_failure_log(log_id)

    logs = temp_store.get_failure_logs()
    assert len(logs) == 0


def test_delete_failure_log_nonexistent(temp_store):
    """Test deleting a non-existent failure log returns False."""
    result = temp_store.delete_failure_log(99999)
    assert result is False


def test_delete_failure_log_only_deletes_specified(temp_store):
    """Test that delete only removes the specified log."""
    id1 = temp_store.log_failure("Keep this")
    id2 = temp_store.log_failure("Delete this")
    id3 = temp_store.log_failure("Keep this too")

    temp_store.delete_failure_log(id2)

    logs = temp_store.get_failure_logs()
    assert len(logs) == 2
    attempted_fixes = [log['attempted_fix'] for log in logs]
    assert "Keep this" in attempted_fixes
    assert "Keep this too" in attempted_fixes
    assert "Delete this" not in attempted_fixes


# =============================================================================
# Clear Old Failures Tests
# =============================================================================

def test_clear_old_failures(temp_store):
    """Test clearing old failures.

    Need to insert old records directly to test this properly.
    """
    # Insert old records directly
    old_timestamp = (datetime.utcnow() - timedelta(days=40)).isoformat()
    temp_store.conn.execute(
        """
        INSERT INTO failure_logs (timestamp, attempted_fix)
        VALUES (?, ?)
        """,
        (old_timestamp, "Old fix 1")
    )
    temp_store.conn.execute(
        """
        INSERT INTO failure_logs (timestamp, attempted_fix)
        VALUES (?, ?)
        """,
        (old_timestamp, "Old fix 2")
    )
    temp_store.conn.commit()

    # Add a recent record
    temp_store.log_failure("Recent fix")

    # Clear logs older than 30 days
    count = temp_store.clear_old_failures(days=30)
    assert count == 2

    # Only recent fix should remain
    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    assert logs[0]['attempted_fix'] == "Recent fix"


def test_clear_old_failures_returns_count(temp_store):
    """Test that clear_old_failures returns correct count."""
    # Insert old records directly
    old_timestamp = (datetime.utcnow() - timedelta(days=100)).isoformat()
    for i in range(5):
        temp_store.conn.execute(
            """
            INSERT INTO failure_logs (timestamp, attempted_fix)
            VALUES (?, ?)
            """,
            (old_timestamp, f"Old fix {i}")
        )
    temp_store.conn.commit()

    count = temp_store.clear_old_failures(days=30)
    assert count == 5


def test_clear_old_failures_no_old_records(temp_store):
    """Test clear_old_failures when no old records exist."""
    temp_store.log_failure("Recent fix")

    count = temp_store.clear_old_failures(days=30)
    assert count == 0

    # Log should still exist
    logs = temp_store.get_failure_logs()
    assert len(logs) == 1


def test_clear_old_failures_custom_days(temp_store):
    """Test clear_old_failures with custom days parameter."""
    # Insert record from 15 days ago
    old_timestamp = (datetime.utcnow() - timedelta(days=15)).isoformat()
    temp_store.conn.execute(
        """
        INSERT INTO failure_logs (timestamp, attempted_fix)
        VALUES (?, ?)
        """,
        (old_timestamp, "15 day old fix")
    )
    temp_store.conn.commit()

    # Clear with 20 day threshold - should not delete
    count = temp_store.clear_old_failures(days=20)
    assert count == 0

    # Clear with 10 day threshold - should delete
    count = temp_store.clear_old_failures(days=10)
    assert count == 1


# =============================================================================
# Entity Resolution Integration Tests
# =============================================================================

def test_entity_name_resolution_with_existing_entity(temp_store):
    """Test that entity_id is resolved from entity_name when entity exists."""
    # Add an entity to the store
    entity_id = temp_store.add_entity(
        name="my_function",
        kind="function",
        code="def my_function(): pass"
    )

    # Log failure with entity_name
    log_id = temp_store.log_failure(
        attempted_fix="Tried to fix function",
        entity_name="my_function"
    )

    # Verify the log was created with entity reference
    cursor = temp_store.conn.execute(
        "SELECT entity_id, entity_name FROM failure_logs WHERE id = ?",
        (log_id,)
    )
    row = cursor.fetchone()

    # entity_id should be resolved
    assert row['entity_id'] == entity_id
    assert row['entity_name'] == "my_function"


def test_entity_name_resolution_partial_match(temp_store):
    """Test entity resolution with partial name match."""
    # Add entities
    entity_id = temp_store.add_entity(
        name="module.MyClass.my_method",
        kind="method",
        code="def my_method(self): pass"
    )

    # Log failure with partial name - query() uses LIKE matching
    log_id = temp_store.log_failure(
        attempted_fix="Tried to fix method",
        entity_name="my_method"
    )

    # Check if entity_id was resolved
    cursor = temp_store.conn.execute(
        "SELECT entity_id, entity_name FROM failure_logs WHERE id = ?",
        (log_id,)
    )
    row = cursor.fetchone()

    # entity_name should be stored as provided
    assert row['entity_name'] == "my_method"
    # entity_id may be resolved via partial match in query()


def test_entity_name_no_resolution_when_not_found(temp_store):
    """Test that entity_id is null when entity_name doesn't match any entity."""
    # Log failure with entity_name that doesn't exist
    log_id = temp_store.log_failure(
        attempted_fix="Tried something",
        entity_name="nonexistent_function"
    )

    # Check entity_id
    cursor = temp_store.conn.execute(
        "SELECT entity_id, entity_name FROM failure_logs WHERE id = ?",
        (log_id,)
    )
    row = cursor.fetchone()

    # entity_id should be null, entity_name should be stored
    assert row['entity_id'] is None
    assert row['entity_name'] == "nonexistent_function"


# =============================================================================
# Edge Cases
# =============================================================================

def test_logging_without_optional_fields(temp_store):
    """Test logging with only required field (attempted_fix)."""
    log_id = temp_store.log_failure("Minimal log entry")

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    log = logs[0]

    assert log['attempted_fix'] == "Minimal log entry"
    assert log['context'] is None
    assert log['entity_name'] is None
    assert log['file_path'] is None
    assert log['failure_reason'] is None
    assert log['related_error'] is None
    assert log['tags'] == []


def test_querying_with_no_results(temp_store):
    """Test querying when no logs exist."""
    logs = temp_store.get_failure_logs()
    assert logs == []


def test_querying_with_no_matching_results(temp_store):
    """Test querying when no logs match the filter."""
    temp_store.log_failure("Fix A", file_path="file_a.py")
    temp_store.log_failure("Fix B", file_path="file_b.py")

    logs = temp_store.get_failure_logs(file_path="nonexistent.py")
    assert logs == []


def test_querying_by_entity_with_no_matching_results(temp_store):
    """Test querying by entity when no logs match."""
    temp_store.log_failure("Fix A", entity_name="func_a")

    logs = temp_store.get_failure_logs(entity_name="nonexistent_func")
    assert logs == []


def test_deleting_nonexistent_logs(temp_store):
    """Test deleting logs that don't exist."""
    # Delete with ID that was never created
    result = temp_store.delete_failure_log(12345)
    assert result is False


def test_empty_tags_list(temp_store):
    """Test logging with empty tags list."""
    log_id = temp_store.log_failure("Fix", tags=[])

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    assert logs[0]['tags'] == []


def test_single_tag(temp_store):
    """Test logging with single tag."""
    log_id = temp_store.log_failure("Fix", tags=["important"])

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    assert logs[0]['tags'] == ["important"]


def test_many_tags(temp_store):
    """Test logging with many tags."""
    many_tags = ["bug", "critical", "database", "performance", "security"]
    log_id = temp_store.log_failure("Fix", tags=many_tags)

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    for tag in many_tags:
        assert tag in logs[0]['tags']


def test_special_characters_in_attempted_fix(temp_store):
    """Test logging with special characters in attempted_fix."""
    special_text = "Tried: `obj.method()` but got 'error' with \"quotes\" and\nnewlines"
    log_id = temp_store.log_failure(special_text)

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    assert logs[0]['attempted_fix'] == special_text


def test_unicode_in_fields(temp_store):
    """Test logging with unicode characters."""
    log_id = temp_store.log_failure(
        attempted_fix="Tried unicode fix",
        context="Error in"
    )

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    assert "" in logs[0]['context']


def test_very_long_attempted_fix(temp_store):
    """Test logging with very long attempted_fix text."""
    long_text = "A" * 10000
    log_id = temp_store.log_failure(long_text)

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    assert logs[0]['attempted_fix'] == long_text


def test_very_long_error_message(temp_store):
    """Test logging with very long error message."""
    long_error = "Error: " + "X" * 10000
    log_id = temp_store.log_failure(
        attempted_fix="Fix",
        related_error=long_error
    )

    logs = temp_store.get_failure_logs()
    assert len(logs) == 1
    assert logs[0]['related_error'] == long_error


# =============================================================================
# Regression Tests
# =============================================================================

def test_multiple_logs_same_entity(temp_store):
    """Test multiple failure logs for the same entity."""
    for i in range(5):
        temp_store.log_failure(
            attempted_fix=f"Attempt {i}",
            entity_name="problematic_function"
        )

    logs = temp_store.get_failure_logs(entity_name="problematic_function")
    assert len(logs) == 5


def test_multiple_logs_same_file(temp_store):
    """Test multiple failure logs for the same file."""
    for i in range(5):
        temp_store.log_failure(
            attempted_fix=f"Attempt {i}",
            file_path="buggy_file.py"
        )

    logs = temp_store.get_failure_logs(file_path="buggy_file.py")
    assert len(logs) == 5


def test_concurrent_operations(temp_store):
    """Test that operations don't interfere with each other."""
    # Create logs
    id1 = temp_store.log_failure("Fix 1", tags=["a"])
    id2 = temp_store.log_failure("Fix 2", tags=["b"])
    id3 = temp_store.log_failure("Fix 3", tags=["c"])

    # Query while we have data
    all_logs = temp_store.get_failure_logs()
    assert len(all_logs) == 3

    # Delete one
    temp_store.delete_failure_log(id2)

    # Query again
    remaining = temp_store.get_failure_logs()
    assert len(remaining) == 2

    # Filter by tag
    tag_a = temp_store.get_failure_logs(tags=["a"])
    assert len(tag_a) == 1

    tag_b = temp_store.get_failure_logs(tags=["b"])
    assert len(tag_b) == 0  # Deleted


def test_filter_by_entity_id(temp_store):
    """Test filtering by entity_id directly."""
    # Add entity
    entity_id = temp_store.add_entity(
        name="test_function",
        kind="function",
        code="def test_function(): pass"
    )

    # Log failures with entity_id directly
    temp_store.log_failure("Fix 1", entity_id=entity_id)
    temp_store.log_failure("Fix 2", entity_id=entity_id)
    temp_store.log_failure("Fix 3")  # No entity

    # Filter by entity_id
    logs = temp_store.get_failure_logs(entity_id=entity_id)
    assert len(logs) == 2


def test_entity_id_takes_precedence_over_entity_name(temp_store):
    """Test that entity_id filter takes precedence over entity_name."""
    # Add entities
    entity1_id = temp_store.add_entity(name="func1", kind="function", code="def func1(): pass")
    entity2_id = temp_store.add_entity(name="func2", kind="function", code="def func2(): pass")

    # Log with entity_id
    temp_store.log_failure("Fix 1", entity_id=entity1_id, entity_name="func1")
    temp_store.log_failure("Fix 2", entity_id=entity2_id, entity_name="func2")

    # Filter by entity_id (should ignore entity_name in filter)
    logs = temp_store.get_failure_logs(entity_id=entity1_id, entity_name="func2")
    assert len(logs) == 1
    assert "Fix 1" in logs[0]['attempted_fix']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
