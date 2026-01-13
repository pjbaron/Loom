"""
todo_tools - LLM-friendly functions for managing work items (TODOs).

This module provides simple primitives that Claude Code can call to track
work items while debugging and developing. TODOs persist across sessions
and can be queried, combined, and completed.

Functions return either:
- Formatted strings ready for LLM consumption (get_todos, next_todo, etc.)
- Simple values for programmatic use (add_todo returns int ID)
"""

from typing import List, Optional, Union

from loom_base import _find_store, _log_usage


def add_todo(
    title: str,
    prompt: str,
    context: str = None,
    tags: list = None,
    critical: bool = False,
    priority: int = 0,
    entity: str = None,
    file: str = None,
    estimated_minutes: int = None
) -> int:
    """Add a new TODO to the queue. Returns the TODO id.

    Use this when you discover work that should be done later.

    Args:
        title: Short name for the task
        prompt: Full description of what needs to be done
        context: Additional context (why, how, related info)
        tags: List of tags like ["bug", "parser"]
        critical: If True, blocks subsequent work on failure
        priority: Higher = more urgent (default 0)
        entity: Related function/class name
        file: Related file path
        estimated_minutes: Time estimate in minutes

    Returns:
        The TODO id (int)

    Example:
        add_todo(
            "Fix edge case in parser",
            "The JSON parser doesn't handle escaped quotes in strings. "
            "Need to update parse_string() to handle \\\" sequences.",
            tags=["bug", "parser"]
        )
    """
    store = _find_store()
    if not store:
        raise RuntimeError("Could not find .loom/store.db. Run './loom ingest <path>' first.")

    try:
        # Handle tags: accept both list and comma-separated string
        tag_list = None
        if tags:
            if isinstance(tags, str):
                tag_list = [t.strip() for t in tags.split(',')]
            else:
                tag_list = list(tags)

        todo_id = store.add_todo(
            prompt=prompt,
            title=title,
            context=context,
            priority=priority,
            entity_name=entity,
            file_path=file,
            tags=tag_list,
            estimated_minutes=estimated_minutes,
            critical=critical
        )

        store.close()
        _log_usage("add_todo", title[:50] if title else prompt[:50], f"created #{todo_id}")
        return todo_id

    except Exception as e:
        store.close()
        raise


def add_todo_verbose(
    prompt: str,
    title: str = None,
    context: str = None,
    priority: int = 0,
    entity: str = None,
    file: str = None,
    tags: str = None,
    estimated_minutes: int = None,
    critical: bool = False
) -> str:
    """
    Add a new TODO work item to track. Returns formatted confirmation.

    Use this to record tasks that need to be done, either now or later.
    TODOs persist in the database and can be queried/completed later.

    Args:
        prompt: What needs to be done (the task description)
        title: Short name for display (optional, auto-generated from prompt)
        context: Why/how/related info (optional)
        priority: Higher = more urgent, default 0 (optional)
        entity: Related function/class name (optional)
        file: Related file path (optional)
        tags: Comma-separated tags like "bug,auth,urgent" (optional)
        estimated_minutes: Time estimate in minutes (optional)
        critical: If true, blocks subsequent work on failure (optional)

    Returns:
        Confirmation message with the TODO ID

    Example:
        add_todo_verbose("Fix the authentication bug in login()", context="Users can't log in with special chars")
        add_todo_verbose("Refactor database queries", priority=2, tags="performance,refactor")
        add_todo_verbose("Fix critical security hole", critical=True, estimated_minutes=30)
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        tag_list = [t.strip() for t in tags.split(',')] if tags else None

        todo_id = store.add_todo(
            prompt=prompt,
            title=title,
            context=context,
            priority=priority,
            entity_name=entity,
            file_path=file,
            tags=tag_list,
            estimated_minutes=estimated_minutes,
            critical=critical
        )

        store.close()

        lines = [f"Added TODO #{todo_id}"]
        if title:
            lines.append(f"  Title: {title}")
        if priority > 0:
            lines.append(f"  Priority: {priority}")
        if critical:
            lines.append(f"  Critical: YES (blocks subsequent work)")
        if estimated_minutes:
            lines.append(f"  Estimate: {estimated_minutes} minutes")
        if entity:
            lines.append(f"  Entity: {entity}")
        if file:
            lines.append(f"  File: {file}")
        if tags:
            lines.append(f"  Tags: {tags}")

        result = "\n".join(lines)
        _log_usage("add_todo", prompt[:50], f"created #{todo_id}")
        return result

    except Exception as e:
        store.close()
        return f"Error adding TODO: {e}"


def todos(
    status: str = None,
    entity: str = None,
    file: str = None,
    limit: int = 20,
    critical_only: bool = False
) -> str:
    """
    List current TODOs (pending and in-progress by default).

    Shows work items in priority order (highest first), then FIFO by position.

    Args:
        status: Filter by status: 'pending', 'in_progress', 'completed' (optional)
        entity: Filter by related entity name (optional)
        file: Filter by related file path (optional)
        limit: Maximum number to show (default 20)
        critical_only: Only show critical TODOs (optional)

    Returns:
        Formatted list of TODOs with IDs, prompts, and metadata

    Example:
        todos()                          # List all pending/in-progress
        todos(status="completed")        # List completed TODOs
        todos(entity="CodeStore")        # TODOs related to CodeStore
        todos(critical_only=True)        # Only critical items
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        include_completed = (status == 'completed')
        todo_list = store.list_todos(
            status=status,
            entity_name=entity,
            file_path=file,
            limit=limit,
            include_completed=include_completed,
            critical_only=critical_only
        )

        store.close()

        if not todo_list:
            result = f"No TODOs with status '{status}'" if status else "No pending TODOs. Queue is empty."
            _log_usage("todos", f"status={status}", "0 items")
            return result

        lines = [f"TODOs ({len(todo_list)} items):", ""]

        for todo in todo_list:
            status_icon = {
                'pending': '○',
                'in_progress': '◐',
                'completed': '●',
                'combined': '⊕'
            }.get(todo['status'], '?')

            # Build info tags
            info_tags = []
            if todo.get('priority', 0) > 0:
                info_tags.append(f"P{todo['priority']}")
            if todo.get('critical'):
                info_tags.append("CRITICAL")
            if todo.get('position'):
                info_tags.append(f"#{todo['position']}")

            info_str = f" [{', '.join(info_tags)}]" if info_tags else ""

            # Use title if available, otherwise first part of prompt
            display_text = todo.get('title') or todo['prompt']

            lines.append(f"{status_icon} #{todo['id']}{info_str}: {display_text}")

            # Show full prompt if title is different
            if todo.get('title') and todo['title'] != todo['prompt']:
                lines.append(f"   Prompt: {todo['prompt'][:100]}{'...' if len(todo['prompt']) > 100 else ''}")

            if todo.get('context'):
                context_preview = todo['context'][:80]
                if len(todo['context']) > 80:
                    context_preview += "..."
                lines.append(f"   Context: {context_preview}")

            if todo.get('estimated_minutes'):
                lines.append(f"   Estimate: {todo['estimated_minutes']} min")

            if todo.get('entity_name'):
                lines.append(f"   Entity: {todo['entity_name']}")

            if todo.get('file_path'):
                lines.append(f"   File: {todo['file_path']}")

            if todo.get('tags'):
                lines.append(f"   Tags: {', '.join(todo['tags'])}")

            lines.append("")

        result = "\n".join(lines)
        _log_usage("todos", f"status={status}", f"{len(todo_list)} items")
        return result

    except Exception as e:
        store.close()
        return f"Error listing TODOs: {e}"


def get_todos(status: str = 'pending', limit: int = 10) -> str:
    """Get formatted list of TODOs.

    Returns human-readable summary of the TODO queue.

    Args:
        status: Filter by status - 'pending', 'in_progress', 'completed' (default 'pending')
        limit: Maximum number of TODOs to return (default 10)

    Returns:
        Formatted string with TODO list

    Example:
        get_todos()                    # Get pending TODOs
        get_todos('in_progress')       # Get in-progress TODOs
        get_todos('completed', 5)      # Get last 5 completed
    """
    return todos(status=status, limit=limit)


def next_todo() -> str:
    """
    Get the next TODO to work on (highest priority pending, FIFO).

    Use this to see what should be done next. Returns the single
    most important pending TODO. Critical TODOs are prioritized.

    Returns:
        The next TODO with full details, or message if queue is empty

    Example:
        next_todo()  # What should I work on next?
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        todo = store.get_next_todo()
        store.close()

        if not todo:
            _log_usage("next_todo", "", "queue empty")
            return "No pending TODOs. Queue is empty."

        # Build header with title or prompt
        header = todo.get('title') or todo['prompt']
        lines = [f"Next TODO: #{todo['id']} - {header}"]

        if todo.get('critical'):
            lines.append("  ** CRITICAL - Blocks subsequent work on failure **")

        if todo.get('title') and todo['title'] != todo['prompt']:
            lines.append(f"  Prompt: {todo['prompt']}")

        if todo.get('priority', 0) > 0:
            lines.append(f"  Priority: {todo['priority']}")

        if todo.get('position'):
            lines.append(f"  Position: #{todo['position']} in queue")

        if todo.get('estimated_minutes'):
            lines.append(f"  Estimate: {todo['estimated_minutes']} minutes")

        if todo.get('context'):
            lines.append(f"  Context: {todo['context']}")

        if todo.get('entity_name'):
            lines.append(f"  Entity: {todo['entity_name']}")

        if todo.get('file_path'):
            lines.append(f"  File: {todo['file_path']}")

        if todo.get('tags'):
            lines.append(f"  Tags: {', '.join(todo['tags'])}")

        lines.append("")
        lines.append(f"Use start_todo({todo['id']}) to mark as in-progress")
        lines.append(f"Use complete_todo({todo['id']}) when done")

        result = "\n".join(lines)
        _log_usage("next_todo", "", f"#{todo['id']}")
        return result

    except Exception as e:
        store.close()
        return f"Error getting next TODO: {e}"


def start_todo(todo_id: int) -> str:
    """
    Mark a TODO as in-progress.

    Call this when you start working on a TODO.

    Args:
        todo_id: The TODO ID to start

    Returns:
        Confirmation message

    Example:
        start_todo(5)  # Start working on TODO #5
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        success = store.start_todo(todo_id)
        store.close()

        if success:
            _log_usage("start_todo", str(todo_id), "started")
            return f"Started TODO #{todo_id}"
        else:
            _log_usage("start_todo", str(todo_id), "not found")
            return f"Could not start TODO #{todo_id} - not found or not pending"

    except Exception as e:
        store.close()
        return f"Error starting TODO: {e}"


def complete_todo(todo_id: int, notes: str = None, result: str = None) -> str:
    """Mark a TODO as completed.

    Call this when you finish a TODO. Optionally record what was done.

    Args:
        todo_id: The TODO ID to complete
        notes: Optional note about what was done/outcome
        result: Alias for notes (for backwards compatibility)

    Returns:
        Confirmation message and the next TODO if any

    Example:
        complete_todo(5)                              # Done with TODO #5
        complete_todo(5, notes="Fixed by adding null check")  # With notes
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        # Support both 'notes' and 'result' params
        completion_notes = notes or result

        success = store.complete_todo(todo_id, result=completion_notes)

        if not success:
            store.close()
            _log_usage("complete_todo", str(todo_id), "not found")
            return f"Could not complete TODO #{todo_id} - not found"

        # Get the next TODO to suggest
        next_item = store.get_next_todo()
        store.close()

        lines = [f"Completed TODO #{todo_id}"]
        if completion_notes:
            lines.append(f"  Notes: {completion_notes}")

        if next_item:
            lines.append("")
            lines.append(f"Next up: #{next_item['id']} - {next_item['prompt']}")

        _log_usage("complete_todo", str(todo_id), "completed")
        return "\n".join(lines)

    except Exception as e:
        store.close()
        return f"Error completing TODO: {e}"


def combine_todos(keep_id: int, merge_ids: str, new_prompt: str = None) -> str:
    """
    Combine overlapping TODOs into one.

    Use when multiple TODOs are about the same thing or can be done together.
    The merged TODOs' context is preserved in the kept TODO.

    Args:
        keep_id: The TODO ID to keep
        merge_ids: Comma-separated IDs to merge into keep_id (e.g., "2,3,5")
        new_prompt: Optional new combined prompt

    Returns:
        Confirmation message

    Example:
        combine_todos(1, "2,3")  # Merge #2 and #3 into #1
        combine_todos(1, "2,3", new_prompt="Fix all auth issues")
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        merge_id_list = [int(x.strip()) for x in merge_ids.split(',')]

        success = store.combine_todos(keep_id, merge_id_list, new_prompt=new_prompt)
        store.close()

        if success:
            _log_usage("combine_todos", f"{keep_id} <- {merge_ids}", "combined")
            return f"Combined TODOs {merge_ids} into #{keep_id}"
        else:
            _log_usage("combine_todos", f"{keep_id} <- {merge_ids}", "not found")
            return f"Could not combine - TODO #{keep_id} not found"

    except ValueError as e:
        store.close()
        return f"Invalid ID format: {e}"
    except Exception as e:
        store.close()
        return f"Error combining TODOs: {e}"


def update_todo(
    todo_id: int,
    title: str = None,
    prompt: str = None,
    context: str = None,
    priority: int = None,
    tags: str = None,
    estimated_minutes: int = None,
    critical: bool = None
) -> str:
    """
    Update a TODO's fields.

    Args:
        todo_id: The TODO ID to update
        title: New short title (optional)
        prompt: New task description (optional)
        context: New context (optional)
        priority: New priority level (optional)
        tags: New comma-separated tags (optional)
        estimated_minutes: New time estimate (optional)
        critical: Whether this blocks subsequent work (optional)

    Returns:
        Confirmation message

    Example:
        update_todo(5, priority=3)  # Make TODO #5 more urgent
        update_todo(5, context="Now blocking release")
        update_todo(5, critical=True)  # Mark as critical
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        tag_list = [t.strip() for t in tags.split(',')] if tags else None

        success = store.update_todo(
            todo_id,
            title=title,
            prompt=prompt,
            context=context,
            priority=priority,
            tags=tag_list,
            estimated_minutes=estimated_minutes,
            critical=critical
        )
        store.close()

        if success:
            _log_usage("update_todo", str(todo_id), "updated")
            return f"Updated TODO #{todo_id}"
        else:
            _log_usage("update_todo", str(todo_id), "not found")
            return f"Could not update TODO #{todo_id} - not found or no changes"

    except Exception as e:
        store.close()
        return f"Error updating TODO: {e}"


def search_todos(query: str, limit: int = 10) -> str:
    """
    Search TODOs by prompt or context text.

    Args:
        query: Search text
        limit: Maximum results (default 10)

    Returns:
        Matching TODOs

    Example:
        search_todos("authentication")
        search_todos("refactor")
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        results = store.search_todos(query, limit=limit)
        store.close()

        if not results:
            _log_usage("search_todos", query, "0 matches")
            return f"No TODOs matching '{query}'"

        lines = [f"TODOs matching '{query}' ({len(results)} found):", ""]

        for todo in results:
            status_icon = {
                'pending': '○',
                'in_progress': '◐',
            }.get(todo['status'], '?')

            lines.append(f"{status_icon} #{todo['id']}: {todo['prompt']}")
            if todo.get('context'):
                context_preview = todo['context'][:60]
                if len(todo['context']) > 60:
                    context_preview += "..."
                lines.append(f"   {context_preview}")
            lines.append("")

        result = "\n".join(lines)
        _log_usage("search_todos", query, f"{len(results)} matches")
        return result

    except Exception as e:
        store.close()
        return f"Error searching TODOs: {e}"


def todo_stats() -> str:
    """
    Get statistics about TODOs.

    Returns:
        Summary of TODO counts by status

    Example:
        todo_stats()  # How many TODOs do we have?
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        stats = store.get_todo_stats()
        store.close()

        lines = [
            "TODO Statistics",
            "=" * 30,
            f"Total:       {stats['total']}",
            f"Pending:     {stats['pending']}",
            f"In Progress: {stats['in_progress']}",
            f"Completed:   {stats['completed']}",
        ]

        result = "\n".join(lines)
        _log_usage("todo_stats", "", f"{stats['total']} total")
        return result

    except Exception as e:
        store.close()
        return f"Error getting stats: {e}"


def delete_todo(todo_id: int) -> str:
    """
    Delete a TODO.

    Use sparingly - prefer completing TODOs or combining duplicates.

    Args:
        todo_id: The TODO ID to delete

    Returns:
        Confirmation message

    Example:
        delete_todo(5)  # Remove TODO #5
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        success = store.delete_todo(todo_id)
        store.close()

        if success:
            _log_usage("delete_todo", str(todo_id), "deleted")
            return f"Deleted TODO #{todo_id}"
        else:
            _log_usage("delete_todo", str(todo_id), "not found")
            return f"Could not delete TODO #{todo_id} - not found"

    except Exception as e:
        store.close()
        return f"Error deleting TODO: {e}"


def reorder_todo(todo_id: int, new_position: int) -> str:
    """
    Move a TODO to a new position in the queue.

    Use this to reorder the FIFO queue manually. Position 1 is first.

    Args:
        todo_id: The TODO ID to move
        new_position: The new position (1 = first in queue)

    Returns:
        Confirmation message

    Example:
        reorder_todo(5, 1)  # Move TODO #5 to front of queue
        reorder_todo(3, 10) # Move TODO #3 to position 10
    """
    store = _find_store()
    if not store:
        return "Error: Could not find .loom/store.db. Run './loom ingest <path>' first."

    try:
        success = store.reorder_todo(todo_id, new_position)
        store.close()

        if success:
            _log_usage("reorder_todo", f"{todo_id} -> {new_position}", "reordered")
            return f"Moved TODO #{todo_id} to position {new_position}"
        else:
            _log_usage("reorder_todo", str(todo_id), "not found")
            return f"Could not reorder TODO #{todo_id} - not found"

    except Exception as e:
        store.close()
        return f"Error reordering TODO: {e}"
