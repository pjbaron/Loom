"""
Tests for TODO system feature.

Tests cover:
1. Basic CRUD operations
2. FIFO ordering
3. Status transitions
4. Combining TODOs
5. Reordering
6. Edge cases

The TODO system provides work item tracking that persists in the database,
allowing LLMs to track tasks, combine overlapping items, and complete them
as work progresses.
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
# 1. Basic CRUD Operations (8+ tests)
# =============================================================================

def test_add_todo_minimal(temp_store):
    """Test adding a TODO with just the required prompt field."""
    todo_id = temp_store.add_todo("Fix the authentication bug")
    assert todo_id > 0

    todo = temp_store.get_todo(todo_id)
    assert todo is not None
    assert todo['prompt'] == "Fix the authentication bug"
    assert todo['status'] == 'pending'


def test_add_todo_full(temp_store):
    """Test adding a TODO with all fields populated."""
    todo_id = temp_store.add_todo(
        prompt="Refactor the database connection pool to handle connection limits",
        title="Refactor DB pool",
        context="The current pool doesn't handle max connections properly",
        priority=5,
        entity_name="DatabasePool.connect",
        file_path="src/database/pool.py",
        tags=["refactor", "database", "performance"],
        metadata={"related_issue": "123", "assignee": "dev"},
        estimated_minutes=120,
        critical=True
    )
    assert todo_id > 0

    todo = temp_store.get_todo(todo_id)
    assert todo is not None
    assert todo['prompt'] == "Refactor the database connection pool to handle connection limits"
    assert todo['title'] == "Refactor DB pool"
    assert todo['context'] == "The current pool doesn't handle max connections properly"
    assert todo['priority'] == 5
    assert todo['entity_name'] == "DatabasePool.connect"
    assert todo['file_path'] == "src/database/pool.py"
    assert "refactor" in todo['tags']
    assert "database" in todo['tags']
    assert "performance" in todo['tags']
    assert todo['metadata']['related_issue'] == "123"
    assert todo['estimated_minutes'] == 120
    assert todo['critical'] is True
    assert todo['status'] == 'pending'


def test_get_todo_by_id(temp_store):
    """Test retrieving a single TODO by ID."""
    todo_id = temp_store.add_todo("First TODO")
    temp_store.add_todo("Second TODO")
    temp_store.add_todo("Third TODO")

    todo = temp_store.get_todo(todo_id)
    assert todo is not None
    assert todo['id'] == todo_id
    assert todo['prompt'] == "First TODO"


def test_get_todo_nonexistent(temp_store):
    """Test retrieving a TODO that doesn't exist returns None."""
    todo = temp_store.get_todo(99999)
    assert todo is None


def test_get_todos_filtering(temp_store):
    """Test filtering TODOs by various criteria."""
    temp_store.add_todo("Fix auth", tags=["bug", "auth"])
    temp_store.add_todo("Fix db", tags=["bug", "database"])
    temp_store.add_todo("Add feature", tags=["feature"])

    # Filter by tags
    todos = temp_store.get_todos(tags=["bug"])
    assert len(todos) == 2

    todos = temp_store.get_todos(tags=["auth"])
    assert len(todos) == 1
    assert todos[0]['prompt'] == "Fix auth"


def test_update_todo(temp_store):
    """Test updating a TODO's fields."""
    todo_id = temp_store.add_todo("Original prompt", title="Original title")

    success = temp_store.update_todo(
        todo_id,
        title="Updated title",
        prompt="Updated prompt",
        context="Added context",
        priority=10,
        tags=["new", "tags"],
        estimated_minutes=60,
        critical=True
    )
    assert success is True

    todo = temp_store.get_todo(todo_id)
    assert todo['title'] == "Updated title"
    assert todo['prompt'] == "Updated prompt"
    assert todo['context'] == "Added context"
    assert todo['priority'] == 10
    assert "new" in todo['tags']
    assert "tags" in todo['tags']
    assert todo['estimated_minutes'] == 60
    assert todo['critical'] is True
    assert todo['updated_at'] is not None


def test_update_todo_nonexistent(temp_store):
    """Test updating a TODO that doesn't exist returns False."""
    success = temp_store.update_todo(99999, title="New title")
    assert success is False


def test_delete_todo(temp_store):
    """Test deleting a TODO."""
    todo_id = temp_store.add_todo("To be deleted")

    success = temp_store.delete_todo(todo_id)
    assert success is True

    todo = temp_store.get_todo(todo_id)
    assert todo is None


def test_delete_todo_nonexistent(temp_store):
    """Test deleting a TODO that doesn't exist returns False."""
    success = temp_store.delete_todo(99999)
    assert success is False


def test_get_next_todo(temp_store):
    """Test getting the next TODO to work on."""
    temp_store.add_todo("First task", priority=0)
    temp_store.add_todo("Second task", priority=5)
    temp_store.add_todo("Third task", priority=3)

    # Should get highest priority first
    next_todo = temp_store.get_next_todo(critical_first=False)
    assert next_todo is not None
    assert next_todo['prompt'] == "Second task"


def test_todo_stats(temp_store):
    """Test getting TODO statistics."""
    temp_store.add_todo("Pending 1")
    todo_id = temp_store.add_todo("Pending 2")
    temp_store.add_todo("Pending 3")

    temp_store.start_todo(todo_id)

    stats = temp_store.todo_stats()
    assert stats['pending'] == 2
    assert stats['in_progress'] == 1
    assert stats['completed'] == 0
    assert stats['total'] == 3


def test_add_todo_returns_incremental_ids(temp_store):
    """Test that TODO IDs are incremental."""
    id1 = temp_store.add_todo("First")
    id2 = temp_store.add_todo("Second")
    id3 = temp_store.add_todo("Third")

    assert id2 > id1
    assert id3 > id2


def test_add_todo_auto_generates_title(temp_store):
    """Test that title is auto-generated from prompt if not provided."""
    long_prompt = "A" * 100
    todo_id = temp_store.add_todo(long_prompt)

    todo = temp_store.get_todo(todo_id)
    assert todo['title'] == "A" * 50 + "..."

    short_prompt = "Short"
    todo_id2 = temp_store.add_todo(short_prompt)
    todo2 = temp_store.get_todo(todo_id2)
    assert todo2['title'] == "Short"


# =============================================================================
# 2. FIFO Ordering (5+ tests)
# =============================================================================

def test_todos_have_sequential_positions(temp_store):
    """Test that TODOs added in order get sequential positions."""
    id1 = temp_store.add_todo("First")
    id2 = temp_store.add_todo("Second")
    id3 = temp_store.add_todo("Third")

    todo1 = temp_store.get_todo(id1)
    todo2 = temp_store.get_todo(id2)
    todo3 = temp_store.get_todo(id3)

    assert todo1['position'] == 1
    assert todo2['position'] == 2
    assert todo3['position'] == 3


def test_get_todos_returns_in_position_order(temp_store):
    """Test that get_todos returns TODOs in position (FIFO) order."""
    temp_store.add_todo("First", priority=0)
    temp_store.add_todo("Second", priority=0)
    temp_store.add_todo("Third", priority=0)

    # With same priority, should be in position order
    todos = temp_store.get_todos()
    assert todos[0]['prompt'] == "First"
    assert todos[1]['prompt'] == "Second"
    assert todos[2]['prompt'] == "Third"


def test_get_next_todo_returns_lowest_position_same_priority(temp_store):
    """Test that get_next_todo returns the lowest position when priorities are equal."""
    temp_store.add_todo("First", priority=0)
    temp_store.add_todo("Second", priority=0)
    temp_store.add_todo("Third", priority=0)

    next_todo = temp_store.get_next_todo(critical_first=False)
    assert next_todo['prompt'] == "First"


def test_completing_todo_doesnt_affect_other_positions(temp_store):
    """Test that completing a TODO doesn't change other TODOs' positions."""
    id1 = temp_store.add_todo("First")
    id2 = temp_store.add_todo("Second")
    id3 = temp_store.add_todo("Third")

    # Complete the second TODO
    temp_store.start_todo(id2)
    temp_store.complete_todo(id2)

    # Other positions should remain unchanged
    todo1 = temp_store.get_todo(id1)
    todo3 = temp_store.get_todo(id3)

    assert todo1['position'] == 1
    assert todo3['position'] == 3


def test_priority_takes_precedence_over_position(temp_store):
    """Test that higher priority TODOs come before lower priority regardless of position."""
    temp_store.add_todo("Low priority first", priority=1)
    temp_store.add_todo("High priority second", priority=10)
    temp_store.add_todo("Medium priority third", priority=5)

    todos = temp_store.get_todos()
    assert todos[0]['prompt'] == "High priority second"
    assert todos[1]['prompt'] == "Medium priority third"
    assert todos[2]['prompt'] == "Low priority first"


def test_position_order_within_same_priority(temp_store):
    """Test that within same priority, position order is maintained."""
    temp_store.add_todo("First high", priority=5)
    temp_store.add_todo("Second high", priority=5)
    temp_store.add_todo("Third high", priority=5)
    temp_store.add_todo("First low", priority=1)

    todos = temp_store.get_todos()
    # High priority first
    assert todos[0]['prompt'] == "First high"
    assert todos[1]['prompt'] == "Second high"
    assert todos[2]['prompt'] == "Third high"
    # Then low priority
    assert todos[3]['prompt'] == "First low"


# =============================================================================
# 3. Status Transitions (5+ tests)
# =============================================================================

def test_start_todo_pending_to_in_progress(temp_store):
    """Test transitioning a TODO from pending to in_progress."""
    todo_id = temp_store.add_todo("Task to start")

    success = temp_store.start_todo(todo_id)
    assert success is True

    todo = temp_store.get_todo(todo_id)
    assert todo['status'] == 'in_progress'


def test_start_todo_sets_started_at_timestamp(temp_store):
    """Test that start_todo sets the started_at timestamp."""
    todo_id = temp_store.add_todo("Task to start")

    before = datetime.utcnow()
    temp_store.start_todo(todo_id)
    after = datetime.utcnow()

    todo = temp_store.get_todo(todo_id)
    started_at = datetime.fromisoformat(todo['started_at'])

    # The timestamp should be between before and after
    assert before <= started_at <= after


def test_complete_todo_in_progress_to_completed(temp_store):
    """Test transitioning a TODO from in_progress to completed."""
    todo_id = temp_store.add_todo("Task to complete")
    temp_store.start_todo(todo_id)

    success = temp_store.complete_todo(todo_id, notes="All done!")
    assert success is True

    todo = temp_store.get_todo(todo_id)
    assert todo['status'] == 'completed'


def test_complete_todo_sets_completed_at_timestamp(temp_store):
    """Test that complete_todo sets the completed_at timestamp."""
    todo_id = temp_store.add_todo("Task to complete")
    temp_store.start_todo(todo_id)

    before = datetime.utcnow()
    temp_store.complete_todo(todo_id)
    after = datetime.utcnow()

    todo = temp_store.get_todo(todo_id)
    completed_at = datetime.fromisoformat(todo['completed_at'])

    assert before <= completed_at <= after


def test_completion_notes_stored(temp_store):
    """Test that completion notes are stored when completing a TODO."""
    todo_id = temp_store.add_todo("Task to complete")
    temp_store.start_todo(todo_id)

    temp_store.complete_todo(todo_id, completion_notes="Fixed the issue by updating the config")

    todo = temp_store.get_todo(todo_id)
    assert todo['completion_notes'] == "Fixed the issue by updating the config"


def test_cannot_start_completed_todo(temp_store):
    """Test that starting an already completed TODO fails."""
    todo_id = temp_store.add_todo("Task")
    temp_store.start_todo(todo_id)
    temp_store.complete_todo(todo_id)

    # Try to start a completed TODO
    success = temp_store.start_todo(todo_id)
    assert success is False

    todo = temp_store.get_todo(todo_id)
    assert todo['status'] == 'completed'


def test_cannot_start_already_started_todo(temp_store):
    """Test that starting an already in_progress TODO fails."""
    todo_id = temp_store.add_todo("Task")
    temp_store.start_todo(todo_id)

    # Try to start again
    success = temp_store.start_todo(todo_id)
    assert success is False


def test_complete_todo_with_result_in_metadata(temp_store):
    """Test that result is stored in metadata when completing."""
    todo_id = temp_store.add_todo("Task")
    temp_store.start_todo(todo_id)

    temp_store.complete_todo(todo_id, result="Successfully refactored", success=True)

    todo = temp_store.get_todo(todo_id)
    assert todo['metadata']['result'] == "Successfully refactored"
    assert todo['metadata']['success'] is True


def test_complete_todo_pending_directly(temp_store):
    """Test that a pending TODO can be completed directly."""
    todo_id = temp_store.add_todo("Quick task")

    # Complete without starting first
    success = temp_store.complete_todo(todo_id, notes="Done quickly")
    assert success is True

    todo = temp_store.get_todo(todo_id)
    assert todo['status'] == 'completed'


# =============================================================================
# 4. Combining TODOs (5+ tests)
# =============================================================================

def test_combine_two_todos(temp_store):
    """Test combining two TODOs into one."""
    id1 = temp_store.add_todo("Fix auth login", context="Login issues")
    id2 = temp_store.add_todo("Fix auth logout", context="Logout issues")

    success = temp_store.combine_todos(id1, [id2])
    assert success is True

    # The merged TODO should be marked as combined
    merged = temp_store.get_todo(id2)
    assert merged['status'] == 'combined'
    assert merged['combined_into'] == id1

    # The kept TODO should have merged context
    kept = temp_store.get_todo(id1)
    assert "Merged from #" in kept['context']
    assert "Fix auth logout" in kept['context']


def test_combine_multiple_todos(temp_store):
    """Test combining multiple TODOs into one."""
    id1 = temp_store.add_todo("Main task")
    id2 = temp_store.add_todo("Related task 1")
    id3 = temp_store.add_todo("Related task 2")
    id4 = temp_store.add_todo("Related task 3")

    success = temp_store.combine_todos(id1, [id2, id3, id4])
    assert success is True

    # All merged TODOs should be marked as combined
    for merged_id in [id2, id3, id4]:
        merged = temp_store.get_todo(merged_id)
        assert merged['status'] == 'combined'
        assert merged['combined_into'] == id1


def test_combined_todos_marked_correctly(temp_store):
    """Test that combined TODOs have correct status and combined_into field."""
    id1 = temp_store.add_todo("Survivor")
    id2 = temp_store.add_todo("To be merged")

    temp_store.combine_todos(id1, [id2])

    merged = temp_store.get_todo(id2)
    assert merged['status'] == 'combined'
    assert merged['combined_into'] == id1


def test_combined_into_points_to_survivor(temp_store):
    """Test that combined_into points to the surviving TODO."""
    id1 = temp_store.add_todo("Survivor TODO")
    id2 = temp_store.add_todo("Merged TODO 1")
    id3 = temp_store.add_todo("Merged TODO 2")

    temp_store.combine_todos(id1, [id2, id3])

    todo2 = temp_store.get_todo(id2)
    todo3 = temp_store.get_todo(id3)

    assert todo2['combined_into'] == id1
    assert todo3['combined_into'] == id1


def test_survivor_has_merged_context(temp_store):
    """Test that the survivor TODO has context from merged TODOs."""
    id1 = temp_store.add_todo("Main task", context="Original context")
    id2 = temp_store.add_todo("Task to merge", context="Merge context 1")
    id3 = temp_store.add_todo("Another task", context="Merge context 2")

    temp_store.combine_todos(id1, [id2, id3])

    kept = temp_store.get_todo(id1)
    assert "Original context" in kept['context']
    assert "Merge context 1" in kept['context']
    assert "Merge context 2" in kept['context']
    assert "Task to merge" in kept['context']
    assert "Another task" in kept['context']


def test_combine_with_new_prompt(temp_store):
    """Test combining TODOs with a new combined prompt."""
    id1 = temp_store.add_todo("Fix bug A")
    id2 = temp_store.add_todo("Fix bug B")

    temp_store.combine_todos(id1, [id2], new_prompt="Fix all auth bugs")

    kept = temp_store.get_todo(id1)
    assert kept['prompt'] == "Fix all auth bugs"


def test_combine_with_new_title(temp_store):
    """Test combining TODOs with a new title."""
    id1 = temp_store.add_todo("Task 1", title="First")
    id2 = temp_store.add_todo("Task 2", title="Second")

    temp_store.combine_todos(id1, [id2], new_title="Combined Tasks")

    kept = temp_store.get_todo(id1)
    assert kept['title'] == "Combined Tasks"


def test_merge_todos_convenience_method(temp_store):
    """Test the merge_todos convenience method."""
    id1 = temp_store.add_todo("Task 1")
    id2 = temp_store.add_todo("Task 2")
    id3 = temp_store.add_todo("Task 3")

    survivor_id = temp_store.merge_todos([id1, id2, id3], combined_title="All tasks")
    assert survivor_id == id1

    # First survives, others merged
    assert temp_store.get_todo(id1)['status'] == 'pending'
    assert temp_store.get_todo(id2)['status'] == 'combined'
    assert temp_store.get_todo(id3)['status'] == 'combined'


def test_merge_todos_requires_at_least_two(temp_store):
    """Test that merge_todos requires at least 2 TODO IDs."""
    id1 = temp_store.add_todo("Task 1")

    with pytest.raises(ValueError, match="at least 2 TODO IDs"):
        temp_store.merge_todos([id1])


# =============================================================================
# 5. Reordering (4+ tests)
# =============================================================================

def test_reorder_to_specific_position(temp_store):
    """Test moving a TODO to a specific position."""
    id1 = temp_store.add_todo("First")
    id2 = temp_store.add_todo("Second")
    id3 = temp_store.add_todo("Third")

    # Move third to position 1
    success = temp_store.reorder_todo(id3, 1)
    assert success is True

    todo3 = temp_store.get_todo(id3)
    assert todo3['position'] == 1


def test_reorder_to_top(temp_store):
    """Test moving a TODO to the top (position 1)."""
    id1 = temp_store.add_todo("First")
    id2 = temp_store.add_todo("Second")
    id3 = temp_store.add_todo("Third")

    temp_store.reorder_todo(id3, 1)

    todo3 = temp_store.get_todo(id3)
    assert todo3['position'] == 1


def test_reorder_to_bottom(temp_store):
    """Test moving a TODO to the bottom."""
    id1 = temp_store.add_todo("First")
    id2 = temp_store.add_todo("Second")
    id3 = temp_store.add_todo("Third")

    # Move first to position 3
    temp_store.reorder_todo(id1, 3)

    todo1 = temp_store.get_todo(id1)
    assert todo1['position'] == 3


def test_reorder_shifts_other_positions(temp_store):
    """Test that reordering properly shifts other TODOs' positions."""
    id1 = temp_store.add_todo("First")
    id2 = temp_store.add_todo("Second")
    id3 = temp_store.add_todo("Third")

    # Original positions: 1, 2, 3
    # Move third (pos 3) to position 1
    temp_store.reorder_todo(id3, 1)

    # After: third should be 1, first should be 2, second should be 3
    todo1 = temp_store.get_todo(id1)
    todo2 = temp_store.get_todo(id2)
    todo3 = temp_store.get_todo(id3)

    assert todo3['position'] == 1
    assert todo1['position'] == 2
    assert todo2['position'] == 3


def test_reorder_down_shifts_others_up(temp_store):
    """Test that moving a TODO down shifts others up."""
    id1 = temp_store.add_todo("First")
    id2 = temp_store.add_todo("Second")
    id3 = temp_store.add_todo("Third")

    # Original positions: 1, 2, 3
    # Move first (pos 1) to position 3
    temp_store.reorder_todo(id1, 3)

    # After: second should be 1, third should be 2, first should be 3
    todo1 = temp_store.get_todo(id1)
    todo2 = temp_store.get_todo(id2)
    todo3 = temp_store.get_todo(id3)

    assert todo2['position'] == 1
    assert todo3['position'] == 2
    assert todo1['position'] == 3


def test_reorder_nonexistent_todo(temp_store):
    """Test that reordering a non-existent TODO returns False."""
    success = temp_store.reorder_todo(99999, 1)
    assert success is False


def test_reorder_same_position_no_change(temp_store):
    """Test that reordering to the same position returns True without changes."""
    id1 = temp_store.add_todo("First")

    todo_before = temp_store.get_todo(id1)
    success = temp_store.reorder_todo(id1, todo_before['position'])
    assert success is True

    todo_after = temp_store.get_todo(id1)
    assert todo_after['position'] == todo_before['position']


# =============================================================================
# 6. Edge Cases (5+ tests)
# =============================================================================

def test_empty_queue_get_todos(temp_store):
    """Test get_todos on empty queue returns empty list."""
    todos = temp_store.get_todos()
    assert todos == []


def test_empty_queue_get_next_todo(temp_store):
    """Test get_next_todo on empty queue returns None."""
    next_todo = temp_store.get_next_todo()
    assert next_todo is None


def test_invalid_todo_id_get_todo(temp_store):
    """Test get_todo with invalid ID returns None."""
    todo = temp_store.get_todo(-1)
    assert todo is None

    todo = temp_store.get_todo(0)
    assert todo is None

    todo = temp_store.get_todo(999999)
    assert todo is None


def test_tags_filtering_with_multiple_tags(temp_store):
    """Test filtering with multiple tags uses OR logic."""
    temp_store.add_todo("Bug fix", tags=["bug"])
    temp_store.add_todo("Feature", tags=["feature"])
    temp_store.add_todo("Bug and feature", tags=["bug", "feature"])
    temp_store.add_todo("Performance", tags=["performance"])

    # Should match any TODO with bug OR feature
    todos = temp_store.list_todos(tags=["bug", "feature"])
    assert len(todos) == 3


def test_very_long_prompt(temp_store):
    """Test handling of very long prompts."""
    long_prompt = "A" * 10000
    todo_id = temp_store.add_todo(long_prompt)

    todo = temp_store.get_todo(todo_id)
    assert todo['prompt'] == long_prompt


def test_very_long_context(temp_store):
    """Test handling of very long context."""
    long_context = "B" * 10000
    todo_id = temp_store.add_todo("Test", context=long_context)

    todo = temp_store.get_todo(todo_id)
    assert todo['context'] == long_context


def test_special_characters_in_prompt(temp_store):
    """Test handling of special characters in prompt."""
    special_prompt = "Fix `obj.method()` but got 'error' with \"quotes\" and\nnewlines"
    todo_id = temp_store.add_todo(special_prompt)

    todo = temp_store.get_todo(todo_id)
    assert todo['prompt'] == special_prompt


def test_unicode_in_fields(temp_store):
    """Test handling of unicode characters in fields."""
    todo_id = temp_store.add_todo(
        prompt="Fix unicode bug",
        context="Error in: 日本語 한국어 العربية"
    )

    todo = temp_store.get_todo(todo_id)
    assert "日本語" in todo['context']
    assert "한국어" in todo['context']
    assert "العربية" in todo['context']


def test_empty_tags_list(temp_store):
    """Test adding TODO with empty tags list."""
    todo_id = temp_store.add_todo("Test", tags=[])

    todo = temp_store.get_todo(todo_id)
    assert todo['tags'] == []


def test_null_optional_fields(temp_store):
    """Test that optional fields are properly handled when None."""
    todo_id = temp_store.add_todo("Minimal TODO")

    todo = temp_store.get_todo(todo_id)
    assert todo['context'] is None
    assert todo['entity_name'] is None
    assert todo['file_path'] is None
    assert todo['estimated_minutes'] is None
    assert todo['critical'] is False
    assert todo['tags'] == []
    assert todo['metadata'] == {}


def test_combine_nonexistent_keep_id(temp_store):
    """Test combining with non-existent keep_id returns False."""
    id1 = temp_store.add_todo("Task")

    success = temp_store.combine_todos(99999, [id1])
    assert success is False


def test_search_todos(temp_store):
    """Test searching TODOs by prompt or context."""
    temp_store.add_todo("Fix authentication bug", context="Login issues")
    temp_store.add_todo("Refactor database", context="Performance improvements")
    temp_store.add_todo("Add new feature", context="User requested authentication flow")

    # Search in prompt
    results = temp_store.search_todos("authentication")
    assert len(results) == 2  # One in prompt, one in context


def test_search_todos_empty_results(temp_store):
    """Test search with no matches returns empty list."""
    temp_store.add_todo("Test task")

    results = temp_store.search_todos("nonexistent")
    assert results == []


def test_clear_completed_todos(temp_store):
    """Test clearing old completed TODOs."""
    # Add and complete a TODO
    todo_id = temp_store.add_todo("Old task")
    temp_store.complete_todo(todo_id)

    # Insert an old completed record directly
    old_timestamp = (datetime.utcnow() - timedelta(days=40)).isoformat()
    temp_store.conn.execute(
        """
        UPDATE todos SET completed_at = ? WHERE id = ?
        """,
        (old_timestamp, todo_id)
    )
    temp_store.conn.commit()

    # Add a recent completed TODO
    recent_id = temp_store.add_todo("Recent task")
    temp_store.complete_todo(recent_id)

    # Clear TODOs older than 30 days
    count = temp_store.clear_completed_todos(days_old=30)
    assert count == 1

    # Recent TODO should still exist
    assert temp_store.get_todo(recent_id) is not None


def test_list_todos_include_completed(temp_store):
    """Test listing TODOs including completed ones."""
    temp_store.add_todo("Pending task")
    completed_id = temp_store.add_todo("Completed task")
    temp_store.complete_todo(completed_id)

    # Without include_completed
    todos = temp_store.list_todos()
    assert len(todos) == 1

    # With include_completed
    todos = temp_store.list_todos(include_completed=True)
    assert len(todos) == 2


def test_list_todos_by_status(temp_store):
    """Test listing TODOs filtered by status."""
    temp_store.add_todo("Pending")
    in_progress_id = temp_store.add_todo("In progress")
    temp_store.start_todo(in_progress_id)
    completed_id = temp_store.add_todo("Completed")
    temp_store.complete_todo(completed_id)

    pending = temp_store.list_todos(status='pending')
    assert len(pending) == 1
    assert pending[0]['prompt'] == "Pending"

    in_progress = temp_store.list_todos(status='in_progress')
    assert len(in_progress) == 1
    assert in_progress[0]['prompt'] == "In progress"

    completed = temp_store.list_todos(status='completed')
    assert len(completed) == 1
    assert completed[0]['prompt'] == "Completed"


def test_list_todos_critical_only(temp_store):
    """Test listing only critical TODOs."""
    temp_store.add_todo("Normal task")
    temp_store.add_todo("Critical task", critical=True)
    temp_store.add_todo("Another normal")

    critical = temp_store.list_todos(critical_only=True)
    assert len(critical) == 1
    assert critical[0]['prompt'] == "Critical task"


def test_list_todos_by_entity_name(temp_store):
    """Test listing TODOs filtered by entity name."""
    temp_store.add_todo("Fix function", entity_name="my_function")
    temp_store.add_todo("Fix class", entity_name="MyClass")
    temp_store.add_todo("No entity")

    todos = temp_store.list_todos(entity_name="my_function")
    assert len(todos) == 1
    assert todos[0]['entity_name'] == "my_function"


def test_list_todos_by_file_path(temp_store):
    """Test listing TODOs filtered by file path."""
    temp_store.add_todo("Fix auth", file_path="src/auth.py")
    temp_store.add_todo("Fix db", file_path="src/database.py")
    temp_store.add_todo("No file")

    todos = temp_store.list_todos(file_path="auth")
    assert len(todos) == 1
    assert "auth" in todos[0]['file_path']


def test_get_next_todo_critical_first(temp_store):
    """Test that critical TODOs are returned first when critical_first=True."""
    temp_store.add_todo("Normal high priority", priority=10)
    temp_store.add_todo("Critical low priority", priority=1, critical=True)

    # With critical_first=True (default)
    next_todo = temp_store.get_next_todo(critical_first=True)
    assert next_todo['prompt'] == "Critical low priority"

    # With critical_first=False
    next_todo = temp_store.get_next_todo(critical_first=False)
    assert next_todo['prompt'] == "Normal high priority"


def test_created_at_timestamp_set(temp_store):
    """Test that created_at timestamp is automatically set."""
    before = datetime.utcnow()
    todo_id = temp_store.add_todo("Test")
    after = datetime.utcnow()

    todo = temp_store.get_todo(todo_id)
    created_at = datetime.fromisoformat(todo['created_at'])

    assert before <= created_at <= after


def test_update_todo_no_changes(temp_store):
    """Test that update_todo with no fields returns False."""
    todo_id = temp_store.add_todo("Test")

    success = temp_store.update_todo(todo_id)
    assert success is False


def test_update_todo_sets_updated_at(temp_store):
    """Test that update_todo sets the updated_at timestamp."""
    todo_id = temp_store.add_todo("Test")

    todo_before = temp_store.get_todo(todo_id)
    assert todo_before['updated_at'] is None

    before = datetime.utcnow()
    temp_store.update_todo(todo_id, title="Updated")
    after = datetime.utcnow()

    todo_after = temp_store.get_todo(todo_id)
    updated_at = datetime.fromisoformat(todo_after['updated_at'])

    assert before <= updated_at <= after


def test_limit_parameter(temp_store):
    """Test limit parameter in list_todos."""
    for i in range(20):
        temp_store.add_todo(f"Task {i}")

    todos = temp_store.list_todos(limit=5)
    assert len(todos) == 5


def test_metadata_preserved_on_complete(temp_store):
    """Test that existing metadata is preserved when completing."""
    todo_id = temp_store.add_todo("Test", metadata={"original": "data"})
    temp_store.complete_todo(todo_id, result="Done")

    todo = temp_store.get_todo(todo_id)
    assert todo['metadata']['original'] == "data"
    assert todo['metadata']['result'] == "Done"


def test_combined_todos_not_in_default_list(temp_store):
    """Test that combined TODOs are not shown in default listing."""
    id1 = temp_store.add_todo("Survivor")
    id2 = temp_store.add_todo("To be merged")

    temp_store.combine_todos(id1, [id2])

    todos = temp_store.get_todos()
    assert len(todos) == 1
    assert todos[0]['id'] == id1


def test_completed_todos_not_in_default_list(temp_store):
    """Test that completed TODOs are not shown in default listing."""
    temp_store.add_todo("Pending")
    completed_id = temp_store.add_todo("Completed")
    temp_store.complete_todo(completed_id)

    todos = temp_store.get_todos()
    assert len(todos) == 1
    assert todos[0]['prompt'] == "Pending"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
