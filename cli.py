#!/usr/bin/env python3
"""
Loom CLI - Command-line interface for code analysis.

Usage:
    loom test [<path>] [--mode <mode>]     # Run tests with automatic tracing
    loom ingest <path> [--db <db_path>]
    loom analyze [--db <db_path>]
    loom query <text> [--db <db_path>]
    loom usages <entity_name> [--db <db_path>]
    loom impact <entity_name> [--db <db_path>]
    loom suggest-tests <entity_name> [--db <db_path>]
    loom trace show <run_id>               # Show trace details
    loom failure-log <message> [options]   # Log a failed fix attempt
    loom attempted-fixes [--entity <name>] [--file <path>]  # Query attempted fixes
    loom todo add <prompt> [options]       # Add a work item
    loom todo list [options]               # List pending TODOs
    loom todo next                         # Show next TODO to work on
    loom todo complete <id> [--result ...]# Mark a TODO as done
"""

import argparse
import subprocess
import sys
from pathlib import Path

from codestore import CodeStore
from validation import cmd_validate
from detection_tools import cmd_issues

# Optional: refactor module may not exist yet
try:
    from refactor import cmd_clusters
except ImportError:
    def cmd_clusters(args):
        """Placeholder for cluster analysis (not yet implemented)."""
        print("Error: clusters command not yet implemented (refactor.py missing)")
        return 1


def cmd_ingest(args):
    """Ingest Python files from a directory."""
    store = CodeStore(args.db)
    path = Path(args.path)

    if not path.exists():
        print(f"Error: Path does not exist: {path}", file=sys.stderr)
        return 1

    print(f"Ingesting files from {path}...")
    stats = store.ingest_files(str(path))

    print(f"  Modules:   {stats['modules']}")
    print(f"  Functions: {stats['functions']}")
    print(f"  Classes:   {stats['classes']}")
    if stats['errors']:
        print(f"  Errors:    {stats['errors']}")

    store.close()
    print(f"Saved to {args.db}")
    return 0


def cmd_analyze(args):
    """Run import and call analysis on ingested code."""
    store = CodeStore(args.db)

    print("Analyzing imports...")
    import_stats = store.analyze_imports()
    print(f"  Analyzed:     {import_stats['analyzed']} modules")
    print(f"  Imports:      {import_stats['imports_found']}")
    print(f"  Relationships: {import_stats['relationships_created']}")

    print("\nAnalyzing calls...")
    call_stats = store.analyze_calls()
    print(f"  Analyzed:     {call_stats['analyzed']} functions")
    print(f"  Calls:        {call_stats['calls_found']}")
    print(f"  Relationships: {call_stats['relationships_created']}")

    store.close()
    return 0


def cmd_query(args):
    """Search for entities by name, intent, or code content."""
    store = CodeStore(args.db)

    results = store.query(args.text)

    if not results:
        print(f"No results for '{args.text}'")
        store.close()
        return 0

    print(f"Found {len(results)} result(s) for '{args.text}':\n")

    for r in results:
        entity = r["entity"]
        matches = ", ".join(r["matches"])
        print(f"  [{entity['kind']}] {entity['name']}")
        print(f"    Matched in: {matches}")
        if entity.get("intent"):
            intent = entity["intent"][:60] + "..." if len(entity.get("intent", "")) > 60 else entity.get("intent", "")
            print(f"    Intent: {intent}")
        print()

    store.close()
    return 0


def _find_entity_by_name(store, name):
    """Find an entity by name, returning None if not found or ambiguous."""
    entities = store.find_entities(name=name)

    if not entities:
        print(f"Error: No entity found matching '{name}'", file=sys.stderr)
        return None

    if len(entities) > 1:
        # Try exact match first
        exact = [e for e in entities if e["name"] == name or e["name"].endswith(f".{name}")]
        if len(exact) == 1:
            return exact[0]

        print(f"Multiple entities match '{name}':", file=sys.stderr)
        for e in entities[:10]:
            print(f"  [{e['kind']}] {e['name']}", file=sys.stderr)
        if len(entities) > 10:
            print(f"  ... and {len(entities) - 10} more", file=sys.stderr)
        print("\nPlease use a more specific name.", file=sys.stderr)
        return None

    return entities[0]


def cmd_usages(args):
    """Find all usages of an entity."""
    store = CodeStore(args.db)

    entity = _find_entity_by_name(store, args.entity_name)
    if not entity:
        store.close()
        return 1

    print(f"Usages of [{entity['kind']}] {entity['name']}:\n")

    usages = store.find_usages(entity["id"])

    if not usages:
        print("  No usages found.")
        store.close()
        return 0

    # Group by relation type
    by_relation = {}
    for u in usages:
        rel = u["relation"]
        if rel not in by_relation:
            by_relation[rel] = []
        by_relation[rel].append(u)

    for rel, items in sorted(by_relation.items()):
        print(f"  {rel} ({len(items)}):")
        for item in items:
            e = item["entity"]
            print(f"    [{e['kind']}] {e['name']}")
        print()

    store.close()
    return 0


def cmd_impact(args):
    """Analyze impact of changes to an entity."""
    store = CodeStore(args.db)

    entity = _find_entity_by_name(store, args.entity_name)
    if not entity:
        store.close()
        return 1

    print(f"Impact analysis for [{entity['kind']}] {entity['name']}:\n")

    result = store.impact_analysis(entity["id"])

    print(f"  Risk score: {result['risk_score']}")
    print()

    if result["direct_callers"]:
        print(f"  Direct callers ({len(result['direct_callers'])}):")
        for c in result["direct_callers"]:
            print(f"    [{c['kind']}] {c['name']}")
        print()
    else:
        print("  No direct callers.\n")

    if result["indirect_callers"]:
        print(f"  Indirect callers ({len(result['indirect_callers'])}):")
        for c in result["indirect_callers"]:
            print(f"    [{c['kind']}] {c['name']}")
        print()

    store.close()
    return 0


def cmd_suggest_tests(args):
    """Suggest relevant tests for an entity."""
    store = CodeStore(args.db)

    entity = _find_entity_by_name(store, args.entity_name)
    if not entity:
        store.close()
        return 1

    print(f"Suggested tests for [{entity['kind']}] {entity['name']}:\n")

    suggestions = store.suggest_tests(entity["id"])

    if not suggestions:
        print("  No relevant tests found.")
        store.close()
        return 0

    for name in suggestions:
        print(f"  {name}")

    store.close()
    return 0


def cmd_failure_log(args):
    """Log a failed fix attempt."""
    store = CodeStore(args.db)

    # Resolve entity_id if provided
    entity_id = None
    if args.entity:
        entity = _find_entity_by_name(store, args.entity)
        if entity:
            entity_id = entity["id"]

    # Parse tags
    tags = None
    if args.tags:
        tags = [t.strip() for t in args.tags.split(',')]

    # Log the failure
    failure_id = store.log_failure(
        attempted_fix=args.message,
        entity_id=entity_id,
        file_path=args.file,
        context=args.context,
        failure_reason=args.reason,
        related_error=args.error,
        tags=tags
    )

    print(f"Logged failure #{failure_id}")
    if entity_id:
        print(f"  Entity: {args.entity}")
    if args.file:
        print(f"  File: {args.file}")
    if args.context:
        print(f"  Context: {args.context}")
    if tags:
        print(f"  Tags: {', '.join(tags)}")

    store.close()
    return 0


def cmd_attempted_fixes(args):
    """Query attempted fixes for an entity or file."""
    store = CodeStore(args.db)

    # Determine query type
    entity_id = None
    if args.entity:
        entity = _find_entity_by_name(store, args.entity)
        if entity:
            entity_id = entity["id"]
        else:
            store.close()
            return 1

    # Parse tags
    tags = None
    if args.tags:
        tags = [t.strip() for t in args.tags.split(',')]

    # Query failures
    failures = store.get_failure_logs(
        entity_id=entity_id,
        file_path=args.file,
        tags=tags,
        context_search=args.search,
        limit=args.limit
    )

    if not failures:
        print("No attempted fixes found matching criteria.")
        store.close()
        return 0

    print(f"Found {len(failures)} attempted fix(es):\n")

    for f in failures:
        print(f"  #{f['id']} - {f['timestamp'][:19]}")
        print(f"    Attempted: {f['attempted_fix']}")
        if f.get('context'):
            print(f"    Context: {f['context']}")
        if f.get('failure_reason'):
            print(f"    Reason: {f['failure_reason']}")
        if f.get('related_error'):
            error_preview = f['related_error'][:80] + '...' if len(f['related_error']) > 80 else f['related_error']
            print(f"    Error: {error_preview}")
        if f.get('file_path'):
            print(f"    File: {f['file_path']}")
        if f.get('tags'):
            print(f"    Tags: {', '.join(f['tags'])}")
        print()

    store.close()
    return 0


def cmd_todo(args):
    """TODO subcommands dispatcher."""
    if args.todo_cmd == 'add':
        return cmd_todo_add(args)
    elif args.todo_cmd == 'list':
        return cmd_todo_list(args)
    elif args.todo_cmd == 'next':
        return cmd_todo_next(args)
    elif args.todo_cmd == 'show':
        return cmd_todo_show(args)
    elif args.todo_cmd == 'start':
        return cmd_todo_start(args)
    elif args.todo_cmd == 'complete' or args.todo_cmd == 'done':
        return cmd_todo_complete(args)
    elif args.todo_cmd == 'update' or args.todo_cmd == 'edit':
        return cmd_todo_update(args)
    elif args.todo_cmd == 'combine':
        return cmd_todo_combine(args)
    elif args.todo_cmd == 'move':
        return cmd_todo_move(args)
    elif args.todo_cmd == 'delete':
        return cmd_todo_delete(args)
    elif args.todo_cmd == 'stats':
        return cmd_todo_stats(args)
    elif args.todo_cmd == 'search':
        return cmd_todo_search(args)
    else:
        print(f"Unknown todo command: {args.todo_cmd}", file=sys.stderr)
        return 1


def cmd_todo_add(args):
    """Add a new TODO."""
    store = CodeStore(args.db)

    # Parse tags
    tags = None
    if args.tag:
        tags = [args.tag] if isinstance(args.tag, str) else list(args.tag)
    elif args.tags:
        tags = [t.strip() for t in args.tags.split(',')]

    # Title is the positional arg, prompt is the detailed description
    title = args.title
    prompt = args.prompt if args.prompt else title

    todo_id = store.add_todo(
        prompt=prompt,
        title=title,
        context=args.context,
        priority=args.priority if hasattr(args, 'priority') else 0,
        entity_name=args.entity if hasattr(args, 'entity') else None,
        file_path=args.file if hasattr(args, 'file') else None,
        tags=tags,
        critical=args.critical if hasattr(args, 'critical') else False
    )

    print(f"Added TODO #{todo_id}: {title}")
    if args.prompt and args.prompt != title:
        print(f"  Prompt: {args.prompt}")
    if hasattr(args, 'priority') and args.priority and args.priority > 0:
        print(f"  Priority: {args.priority}")
    if hasattr(args, 'critical') and args.critical:
        print(f"  Critical: YES")
    if tags:
        print(f"  Tags: {', '.join(tags)}")

    store.close()
    return 0


def _format_age(created_at: str) -> str:
    """Format age as human-readable string (e.g., '2h', '3d', '30m')."""
    from datetime import datetime
    try:
        created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        now = datetime.utcnow()
        delta = now - created.replace(tzinfo=None)

        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            return f"{total_seconds // 60}m"
        elif total_seconds < 86400:
            return f"{total_seconds // 3600}h"
        else:
            return f"{total_seconds // 86400}d"
    except:
        return "?"


def cmd_todo_list(args):
    """List TODOs with formatted table output."""
    store = CodeStore(args.db)

    # Determine what to include
    include_completed = getattr(args, 'all', False) or (getattr(args, 'status', None) == 'completed')

    # Filter by tag if specified
    tags = None
    if hasattr(args, 'tag') and args.tag:
        tags = [args.tag] if isinstance(args.tag, str) else list(args.tag)

    todo_list = store.list_todos(
        status=getattr(args, 'status', None),
        entity_name=getattr(args, 'entity', None),
        file_path=getattr(args, 'file', None),
        tags=tags,
        limit=getattr(args, 'limit', 50),
        include_completed=include_completed
    )

    if not todo_list:
        print("No TODOs found.")
        store.close()
        return 0

    # Count by status
    pending_count = sum(1 for t in todo_list if t['status'] == 'pending')
    in_progress_count = sum(1 for t in todo_list if t['status'] == 'in_progress')

    status_summary = []
    if pending_count:
        status_summary.append(f"{pending_count} pending")
    if in_progress_count:
        status_summary.append(f"{in_progress_count} in progress")

    header = f"TODO Queue ({', '.join(status_summary) if status_summary else f'{len(todo_list)} items'})"
    print(header)
    print()

    # Table header
    print(f"  {'#':<3} {'ID':<5} {'Title':<32} {'Tags':<14} {'Age':<6}")
    print(f"  {'-'*3} {'-'*5} {'-'*32} {'-'*14} {'-'*6}")

    for i, todo in enumerate(todo_list, 1):
        # Position (queue order)
        pos = todo.get('position', i)

        # ID
        todo_id = todo['id']

        # Title (truncated)
        title = todo.get('title') or todo['prompt']
        if len(title) > 30:
            title = title[:27] + "..."

        # Status indicator
        if todo['status'] == 'in_progress':
            title = "▶ " + title[:28] if len(title) > 28 else "▶ " + title
        elif todo['status'] == 'completed':
            title = "✓ " + title[:28] if len(title) > 28 else "✓ " + title
        elif todo.get('critical'):
            title = "! " + title[:28] if len(title) > 28 else "! " + title

        # Tags
        tags_str = ""
        if todo.get('tags'):
            tags_str = "[" + ",".join(todo['tags'][:2]) + "]"
            if len(todo['tags']) > 2:
                tags_str = tags_str[:-1] + ",...]"
        if len(tags_str) > 12:
            tags_str = tags_str[:11] + "]"

        # Age
        age = _format_age(todo['created_at'])

        print(f"  {pos:<3} {todo_id:<5} {title:<32} {tags_str:<14} {age:<6}")

    print()

    # Show hint for next action
    if pending_count > 0:
        next_todo = next((t for t in todo_list if t['status'] == 'pending'), None)
        if next_todo:
            print(f"Use './loom todo next' to see details of #{next_todo['id']}")

    store.close()
    return 0


def _print_todo_details(todo):
    """Print detailed view of a TODO."""
    # Header with ID and title
    title = todo.get('title') or todo['prompt'][:50]
    print(f"TODO #{todo['id']}: {title}")
    print("=" * 60)

    # Status
    status_display = {
        'pending': 'Pending',
        'in_progress': 'In Progress',
        'completed': 'Completed',
        'combined': 'Combined'
    }.get(todo['status'], todo['status'])
    print(f"Status:    {status_display}")

    # Position
    if todo.get('position'):
        print(f"Position:  #{todo['position']} in queue")

    # Priority
    if todo.get('priority', 0) > 0:
        print(f"Priority:  {todo['priority']}")

    # Critical flag
    if todo.get('critical'):
        print(f"Critical:  YES (blocks subsequent work)")

    # Age
    age = _format_age(todo['created_at'])
    print(f"Created:   {todo['created_at'][:19]} ({age} ago)")

    # Started at
    if todo.get('started_at'):
        print(f"Started:   {todo['started_at'][:19]}")

    # Completed at
    if todo.get('completed_at'):
        print(f"Completed: {todo['completed_at'][:19]}")

    print()

    # Prompt (full task description)
    if todo.get('prompt'):
        print("Prompt:")
        print(f"  {todo['prompt']}")
        print()

    # Context
    if todo.get('context'):
        print("Context:")
        print(f"  {todo['context']}")
        print()

    # Related entity
    if todo.get('entity_name'):
        print(f"Entity:    {todo['entity_name']}")

    # Related file
    if todo.get('file_path'):
        print(f"File:      {todo['file_path']}")

    # Tags
    if todo.get('tags'):
        print(f"Tags:      [{', '.join(todo['tags'])}]")

    # Completion notes
    if todo.get('completion_notes'):
        print()
        print("Completion Notes:")
        print(f"  {todo['completion_notes']}")

    # Estimated time
    if todo.get('estimated_minutes'):
        print(f"Estimate:  {todo['estimated_minutes']} minutes")


def cmd_todo_next(args):
    """Show the next TODO to work on (highest priority pending, FIFO)."""
    store = CodeStore(args.db)

    todo = store.get_next_todo()

    if not todo:
        print("No pending TODOs. Queue is empty.")
        store.close()
        return 0

    _print_todo_details(todo)

    print()
    print(f"Commands:")
    print(f"  ./loom todo start {todo['id']}         - Mark as in-progress")
    print(f"  ./loom todo done {todo['id']}          - Mark as completed")
    print(f"  ./loom todo done {todo['id']} --notes 'How it was resolved'")

    store.close()
    return 0


def cmd_todo_show(args):
    """Show details of a specific TODO."""
    store = CodeStore(args.db)

    todo = store.get_todo(args.id)

    if not todo:
        print(f"TODO #{args.id} not found.", file=sys.stderr)
        store.close()
        return 1

    _print_todo_details(todo)

    store.close()
    return 0


def cmd_todo_start(args):
    """Mark a TODO as in-progress."""
    store = CodeStore(args.db)

    success = store.start_todo(args.id)

    if success:
        print(f"Started TODO #{args.id}")
    else:
        print(f"Could not start TODO #{args.id} - not found or not pending", file=sys.stderr)
        store.close()
        return 1

    store.close()
    return 0


def cmd_todo_complete(args):
    """Mark a TODO as completed."""
    store = CodeStore(args.db)

    # Support both --result and --notes
    notes = getattr(args, 'notes', None) or getattr(args, 'result', None)

    success = store.complete_todo(args.id, result=notes, notes=notes)

    if not success:
        print(f"Could not complete TODO #{args.id} - not found", file=sys.stderr)
        store.close()
        return 1

    print(f"Completed TODO #{args.id}")
    if notes:
        print(f"  Notes: {notes}")

    # Show next TODO
    next_item = store.get_next_todo()
    if next_item:
        title = next_item.get('title') or next_item['prompt'][:50]
        print(f"\nNext up: #{next_item['id']} - {title}")

    store.close()
    return 0


def cmd_todo_update(args):
    """Update a TODO's fields (edit command)."""
    store = CodeStore(args.db)

    # Parse tags from --tag (repeatable) or --tags (comma-separated)
    tags = None
    if hasattr(args, 'tag') and args.tag:
        tags = [args.tag] if isinstance(args.tag, str) else list(args.tag)
    elif hasattr(args, 'tags') and args.tags:
        tags = [t.strip() for t in args.tags.split(',')]

    success = store.update_todo(
        args.id,
        title=getattr(args, 'title', None),
        prompt=getattr(args, 'prompt', None),
        context=getattr(args, 'context', None),
        priority=getattr(args, 'priority', None),
        tags=tags
    )

    if success:
        print(f"Updated TODO #{args.id}")
    else:
        print(f"Could not update TODO #{args.id} - not found or no changes", file=sys.stderr)
        store.close()
        return 1

    store.close()
    return 0


def cmd_todo_move(args):
    """Move a TODO to a new position in the queue."""
    store = CodeStore(args.db)

    # Parse position - support 'top', 'bottom', or numeric
    position = args.position
    if position == 'top':
        position = 1
    elif position == 'bottom':
        # Get the max position
        cursor = store.conn.execute("SELECT MAX(position) FROM todos WHERE status = 'pending'")
        max_pos = cursor.fetchone()[0]
        position = (max_pos or 0) + 1
    else:
        try:
            position = int(position)
        except ValueError:
            print(f"Invalid position: {args.position}. Use a number, 'top', or 'bottom'.", file=sys.stderr)
            store.close()
            return 1

    success = store.reorder_todo(args.id, position)

    if success:
        if args.position == 'top':
            print(f"Moved TODO #{args.id} to top of queue")
        elif args.position == 'bottom':
            print(f"Moved TODO #{args.id} to bottom of queue")
        else:
            print(f"Moved TODO #{args.id} to position {position}")
    else:
        print(f"Could not move TODO #{args.id} - not found", file=sys.stderr)
        store.close()
        return 1

    store.close()
    return 0


def cmd_todo_combine(args):
    """Combine multiple TODOs into one."""
    store = CodeStore(args.db)

    # args.ids is a list of IDs - first one is the one to keep
    if len(args.ids) < 2:
        print("Error: Need at least 2 TODO IDs to combine", file=sys.stderr)
        store.close()
        return 1

    keep_id = args.ids[0]
    merge_ids = args.ids[1:]

    # Get new title if provided
    new_title = getattr(args, 'title', None)
    new_prompt = getattr(args, 'prompt', None)

    success = store.combine_todos(keep_id, merge_ids, new_prompt=new_prompt, new_title=new_title)

    if success:
        merge_str = ", ".join(f"#{mid}" for mid in merge_ids)
        print(f"Combined TODOs {merge_str} into #{keep_id}")
        if new_title:
            print(f"  New title: {new_title}")
    else:
        print(f"Could not combine - TODO #{keep_id} not found", file=sys.stderr)
        store.close()
        return 1

    store.close()
    return 0


def cmd_todo_delete(args):
    """Delete a TODO."""
    store = CodeStore(args.db)

    success = store.delete_todo(args.id)

    if success:
        print(f"Deleted TODO #{args.id}")
    else:
        print(f"Could not delete TODO #{args.id} - not found", file=sys.stderr)
        store.close()
        return 1

    store.close()
    return 0


def cmd_todo_stats(args):
    """Show TODO statistics."""
    store = CodeStore(args.db)

    stats = store.get_todo_stats()

    print("TODO Statistics")
    print("=" * 30)
    print(f"Total:       {stats['total']}")
    print(f"Pending:     {stats['pending']}")
    print(f"In Progress: {stats['in_progress']}")
    print(f"Completed:   {stats['completed']}")

    store.close()
    return 0


def cmd_todo_search(args):
    """Search TODOs."""
    store = CodeStore(args.db)

    results = store.search_todos(args.query, limit=args.limit)

    if not results:
        print(f"No TODOs matching '{args.query}'")
        store.close()
        return 0

    print(f"TODOs matching '{args.query}' ({len(results)} found):\n")

    for todo in results:
        status_icon = {
            'pending': '○',
            'in_progress': '◐',
        }.get(todo['status'], '?')

        print(f"  {status_icon} #{todo['id']}: {todo['prompt']}")
        if todo.get('context'):
            context_preview = todo['context'][:60]
            if len(todo['context']) > 60:
                context_preview += "..."
            print(f"     {context_preview}")
        print()

    store.close()
    return 0


def cmd_test(args):
    """Run tests with automatic Loom tracing.

    This is the single command for testing with smart trace collection.
    Defaults to failure-focused mode for minimal overhead on passing tests.
    """
    # Build pytest command
    pytest_args = ['pytest', '--loom-trace']

    # Add mode (default to 'fail' for low overhead)
    mode = getattr(args, 'mode', 'fail') or 'fail'
    pytest_args.extend(['--loom-mode', mode])

    # Add database path
    db_path = getattr(args, 'db', '.loom/store.db') or '.loom/store.db'
    pytest_args.extend(['--loom-db', db_path])

    # Add test path(s)
    if hasattr(args, 'path') and args.path:
        pytest_args.append(args.path)

    # Pass through any extra pytest args
    if hasattr(args, 'pytest_args') and args.pytest_args:
        pytest_args.extend(args.pytest_args)

    # Run pytest
    try:
        result = subprocess.run(pytest_args)
        return result.returncode
    except FileNotFoundError:
        print("Error: pytest not found. Install with: pip install pytest", file=sys.stderr)
        return 1


def cmd_trace(args):
    """Trace subcommands dispatcher."""
    if args.trace_cmd == 'show':
        return cmd_trace_show(args)
    elif args.trace_cmd == 'list':
        return cmd_trace_list(args)
    else:
        print(f"Unknown trace command: {args.trace_cmd}", file=sys.stderr)
        return 1


def cmd_trace_show(args):
    """Show details of a trace run."""
    store = CodeStore(args.db)

    # Find the run by prefix
    run_id = args.run_id
    cursor = store.conn.execute(
        "SELECT * FROM trace_runs WHERE run_id LIKE ?",
        (f"{run_id}%",)
    )
    runs = cursor.fetchall()

    if not runs:
        print(f"No trace run found matching: {run_id}", file=sys.stderr)
        store.close()
        return 1

    if len(runs) > 1:
        print(f"Multiple runs match '{run_id}':", file=sys.stderr)
        for r in runs[:5]:
            print(f"  {r['run_id'][:8]} - {r['command']}", file=sys.stderr)
        store.close()
        return 1

    run = dict(runs[0])
    full_run_id = run['run_id']

    print(f"\nTrace Run: {full_run_id[:8]}...")
    print(f"  Command:  {run['command']}")
    print(f"  Status:   {run['status']}")
    print(f"  Started:  {run['started_at']}")
    print(f"  Ended:    {run['ended_at']}")
    if run['exit_code'] is not None:
        print(f"  Exit:     {run['exit_code']}")

    # Get call statistics
    stats = store.conn.execute("""
        SELECT
            COUNT(*) as total_calls,
            COUNT(exception_type) as failed_calls,
            AVG(duration_ms) as avg_duration,
            MAX(duration_ms) as max_duration
        FROM trace_calls WHERE run_id = ?
    """, (full_run_id,)).fetchone()

    print(f"\nCalls:")
    print(f"  Total:    {stats['total_calls']}")
    print(f"  Failed:   {stats['failed_calls']}")
    if stats['avg_duration']:
        print(f"  Avg time: {stats['avg_duration']:.2f}ms")
        print(f"  Max time: {stats['max_duration']:.2f}ms")

    # Show failed calls if any
    if stats['failed_calls'] > 0:
        print(f"\nFailed Calls:")
        failed = store.get_failed_calls(run_id=full_run_id, limit=10)
        for call in failed:
            func = call.get('function_name', '?')
            if '.' in func:
                func = func.rsplit('.', 1)[-1]
            exc = call.get('exception_type', '?')
            msg = call.get('exception_message', '')[:50]
            print(f"  {func}() -> {exc}: {msg}")

    # Show slowest calls
    slowest = store.conn.execute("""
        SELECT function_name, duration_ms, file_path, line_number
        FROM trace_calls
        WHERE run_id = ? AND duration_ms IS NOT NULL
        ORDER BY duration_ms DESC
        LIMIT 5
    """, (full_run_id,)).fetchall()

    if slowest:
        print(f"\nSlowest Calls:")
        for call in slowest:
            func = call['function_name']
            if '.' in func:
                func = func.rsplit('.', 1)[-1]
            print(f"  {call['duration_ms']:.1f}ms - {func}()")

    store.close()
    return 0


def cmd_trace_list(args):
    """List recent trace runs."""
    store = CodeStore(args.db)

    cursor = store.conn.execute("""
        SELECT run_id, command, status, started_at,
               (SELECT COUNT(*) FROM trace_calls WHERE trace_calls.run_id = trace_runs.run_id) as call_count
        FROM trace_runs
        ORDER BY started_at DESC
        LIMIT ?
    """, (args.limit,))

    runs = cursor.fetchall()

    if not runs:
        print("No trace runs found.")
        store.close()
        return 0

    print(f"\nRecent Trace Runs:\n")
    for run in runs:
        status_icon = "" if run['status'] == 'completed' else ""
        cmd = run['command'][:40] + '...' if len(run['command']) > 40 else run['command']
        print(f"  {run['run_id'][:8]} {status_icon} {cmd}")
        print(f"           {run['started_at']} ({run['call_count']} calls)")

    store.close()
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="loom",
        description="Loom - Code analysis and graph-based code representation"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Common arguments for all subparsers
    db_help = "Database file path (default: .loom/store.db)"

    # test - the main testing command
    p_test = subparsers.add_parser("test", help="Run tests with automatic Loom tracing")
    p_test.add_argument("path", nargs="?", help="Test path (file or directory)")
    p_test.add_argument("--mode", choices=["fail", "full"], default="fail",
                        help="Tracing mode: fail (only on failure, default) or full (always)")
    p_test.add_argument("--db", default=".loom/store.db", help=db_help)
    p_test.add_argument("pytest_args", nargs="*", help="Additional pytest arguments")

    # trace - trace management commands
    p_trace = subparsers.add_parser("trace", help="Manage trace runs")
    trace_sub = p_trace.add_subparsers(dest="trace_cmd", help="Trace commands")

    p_trace_show = trace_sub.add_parser("show", help="Show trace run details")
    p_trace_show.add_argument("run_id", help="Trace run ID (or prefix)")
    p_trace_show.add_argument("--db", default=".loom/store.db", help=db_help)

    p_trace_list = trace_sub.add_parser("list", help="List recent trace runs")
    p_trace_list.add_argument("--limit", type=int, default=10, help="Number of runs to show")
    p_trace_list.add_argument("--db", default=".loom/store.db", help=db_help)

    # ingest
    p_ingest = subparsers.add_parser("ingest", help="Ingest Python files from a directory")
    p_ingest.add_argument("path", help="Directory path to ingest")
    p_ingest.add_argument("--db", default=".loom/store.db", help=db_help)

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Run import and call analysis")
    p_analyze.add_argument("--db", default=".loom/store.db", help=db_help)

    # query
    p_query = subparsers.add_parser("query", help="Search for entities")
    p_query.add_argument("text", help="Search text")
    p_query.add_argument("--db", default=".loom/store.db", help=db_help)

    # usages
    p_usages = subparsers.add_parser("usages", help="Find usages of an entity")
    p_usages.add_argument("entity_name", help="Entity name to find usages for")
    p_usages.add_argument("--db", default=".loom/store.db", help=db_help)

    # impact
    p_impact = subparsers.add_parser("impact", help="Analyze impact of changes to an entity")
    p_impact.add_argument("entity_name", help="Entity name to analyze")
    p_impact.add_argument("--db", default=".loom/store.db", help=db_help)

    # suggest-tests
    p_suggest = subparsers.add_parser("suggest-tests", help="Suggest relevant tests for an entity")
    p_suggest.add_argument("entity_name", help="Entity name to find tests for")
    p_suggest.add_argument("--db", default=".loom/store.db", help=db_help)

    # clusters - file cohesion analysis for refactoring
    p_clusters = subparsers.add_parser("clusters", help="Analyze file clusters for refactoring")
    p_clusters.add_argument("file_path", help="File path to analyze (e.g., codestore.py)")
    p_clusters.add_argument("--db", default=".loom/store.db", help=db_help)
    p_clusters.add_argument("--json", action="store_true", help="Output as JSON only")
    p_clusters.add_argument("--json-file", help="Write JSON output to file")

    # failure-log - log a failed fix attempt
    p_failure_log = subparsers.add_parser("failure-log", help="Log a failed fix attempt")
    p_failure_log.add_argument("message", help="Description of what was tried")
    p_failure_log.add_argument("--entity", help="Entity name this relates to")
    p_failure_log.add_argument("--file", help="File path being worked on")
    p_failure_log.add_argument("--context", help="What was being attempted (function name, error type, etc.)")
    p_failure_log.add_argument("--reason", help="Why it didn't work")
    p_failure_log.add_argument("--error", help="Related error message")
    p_failure_log.add_argument("--tags", help="Comma-separated tags for categorization")
    p_failure_log.add_argument("--db", default=".loom/store.db", help=db_help)

    # attempted-fixes - query what's been tried
    p_attempted = subparsers.add_parser("attempted-fixes", help="Query attempted fixes for an entity or file")
    p_attempted.add_argument("--entity", help="Filter by entity name")
    p_attempted.add_argument("--file", help="Filter by file path")
    p_attempted.add_argument("--tags", help="Filter by tags (comma-separated, any match)")
    p_attempted.add_argument("--search", help="Search in context and attempted fix text")
    p_attempted.add_argument("--limit", type=int, default=50, help="Maximum results to show")
    p_attempted.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo - work item management
    p_todo = subparsers.add_parser("todo", help="Manage work items (TODOs)",
        description="""
TODO Management Commands:

  add <title>              Add a new TODO
  list                     List TODOs (default: pending, ordered by position)
  next                     Show next TODO (the one to work on)
  show <id>                Show details of a specific TODO
  start <id>               Start working on a TODO
  done <id>                Complete a TODO
  combine <id1> <id2>...   Combine multiple TODOs
  move <id> <position>     Reorder (move to position, 'top', or 'bottom')
  edit <id>                Edit a TODO
  delete <id>              Delete a TODO
  stats                    Quick statistics
  search <query>           Search TODOs

Examples:
  ./loom todo add "Fix the parser bug"
  ./loom todo add "Title" --prompt "Detailed instructions..." --tag bug --critical
  ./loom todo list --all
  ./loom todo done 42 --notes "Fixed by adding null check"
  ./loom todo move 42 top
  ./loom todo combine 1 2 3 --title "Combined task"
""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    todo_sub = p_todo.add_subparsers(dest="todo_cmd", help="TODO commands")

    # todo add - title as positional, prompt as optional detailed description
    p_todo_add = todo_sub.add_parser("add", help="Add a new TODO",
        description="Add a new TODO. The title is a short description, prompt is for detailed instructions.")
    p_todo_add.add_argument("title", help="Short title for the TODO")
    p_todo_add.add_argument("--prompt", help="Detailed instructions (defaults to title if not specified)")
    p_todo_add.add_argument("--context", help="Additional context (why, how, related info)")
    p_todo_add.add_argument("--priority", type=int, default=0, help="Priority level (higher = more urgent)")
    p_todo_add.add_argument("--tag", action="append", help="Add a tag (can be used multiple times)")
    p_todo_add.add_argument("--tags", help="Comma-separated tags (alternative to --tag)")
    p_todo_add.add_argument("--critical", action="store_true", help="Mark as critical (blocks subsequent work)")
    p_todo_add.add_argument("--entity", help="Related entity name")
    p_todo_add.add_argument("--file", help="Related file path")
    p_todo_add.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo list - with formatted table output
    p_todo_list = todo_sub.add_parser("list", help="List TODOs (default: pending, ordered by position)")
    p_todo_list.add_argument("--status", choices=["pending", "in_progress", "completed"], help="Filter by status")
    p_todo_list.add_argument("--tag", action="append", help="Filter by tag")
    p_todo_list.add_argument("--all", action="store_true", help="Include completed/combined TODOs")
    p_todo_list.add_argument("--entity", help="Filter by entity")
    p_todo_list.add_argument("--file", help="Filter by file")
    p_todo_list.add_argument("--limit", type=int, default=50, help="Maximum results")
    p_todo_list.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo next - show full details of next TODO
    p_todo_next = todo_sub.add_parser("next", help="Show next TODO to work on (highest priority pending)")
    p_todo_next.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo show - show details of a specific TODO
    p_todo_show = todo_sub.add_parser("show", help="Show details of a specific TODO")
    p_todo_show.add_argument("id", type=int, help="TODO ID to show")
    p_todo_show.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo start
    p_todo_start = todo_sub.add_parser("start", help="Start working on a TODO")
    p_todo_start.add_argument("id", type=int, help="TODO ID to start")
    p_todo_start.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo done (alias: complete) - with --notes
    p_todo_done = todo_sub.add_parser("done", help="Complete a TODO")
    p_todo_done.add_argument("id", type=int, help="TODO ID to complete")
    p_todo_done.add_argument("--notes", help="How it was resolved")
    p_todo_done.add_argument("--result", help="Alias for --notes")
    p_todo_done.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo complete (same as done)
    p_todo_complete = todo_sub.add_parser("complete", help="Complete a TODO (alias for 'done')")
    p_todo_complete.add_argument("id", type=int, help="TODO ID to complete")
    p_todo_complete.add_argument("--notes", help="How it was resolved")
    p_todo_complete.add_argument("--result", help="Alias for --notes")
    p_todo_complete.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo edit (alias: update)
    p_todo_edit = todo_sub.add_parser("edit", help="Edit a TODO")
    p_todo_edit.add_argument("id", type=int, help="TODO ID to edit")
    p_todo_edit.add_argument("--title", help="New title")
    p_todo_edit.add_argument("--prompt", help="New detailed prompt")
    p_todo_edit.add_argument("--context", help="New context")
    p_todo_edit.add_argument("--priority", type=int, help="New priority")
    p_todo_edit.add_argument("--tag", action="append", help="Set tags (replaces existing)")
    p_todo_edit.add_argument("--tags", help="Comma-separated tags (replaces existing)")
    p_todo_edit.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo update (same as edit)
    p_todo_update = todo_sub.add_parser("update", help="Update a TODO (alias for 'edit')")
    p_todo_update.add_argument("id", type=int, help="TODO ID to update")
    p_todo_update.add_argument("--title", help="New title")
    p_todo_update.add_argument("--prompt", help="New detailed prompt")
    p_todo_update.add_argument("--context", help="New context")
    p_todo_update.add_argument("--priority", type=int, help="New priority")
    p_todo_update.add_argument("--tag", action="append", help="Set tags (replaces existing)")
    p_todo_update.add_argument("--tags", help="Comma-separated tags (replaces existing)")
    p_todo_update.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo combine - multiple IDs as positional, --title for combined title
    p_todo_combine = todo_sub.add_parser("combine", help="Combine multiple TODOs into one")
    p_todo_combine.add_argument("ids", type=int, nargs="+", help="TODO IDs to combine (first one is kept)")
    p_todo_combine.add_argument("--title", help="New title for combined TODO")
    p_todo_combine.add_argument("--prompt", help="New combined prompt")
    p_todo_combine.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo move - move to position (number, 'top', or 'bottom')
    p_todo_move = todo_sub.add_parser("move", help="Move a TODO to a new position")
    p_todo_move.add_argument("id", type=int, help="TODO ID to move")
    p_todo_move.add_argument("position", help="New position (number, 'top', or 'bottom')")
    p_todo_move.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo delete
    p_todo_delete = todo_sub.add_parser("delete", help="Delete a TODO")
    p_todo_delete.add_argument("id", type=int, help="TODO ID to delete")
    p_todo_delete.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo stats
    p_todo_stats = todo_sub.add_parser("stats", help="Show TODO statistics")
    p_todo_stats.add_argument("--db", default=".loom/store.db", help=db_help)

    # todo search
    p_todo_search = todo_sub.add_parser("search", help="Search TODOs by text")
    p_todo_search.add_argument("query", help="Search text")
    p_todo_search.add_argument("--limit", type=int, default=20, help="Maximum results")
    p_todo_search.add_argument("--db", default=".loom/store.db", help=db_help)

    # validate - cross-language validation
    p_validate = subparsers.add_parser("validate", help="Validate code for cross-reference issues",
        description="""
Cross-language code validation.

Checks for:
  - DOM references: JS getElementById/querySelector calls that reference
    non-existent HTML element IDs
  - Imports: Relative import statements that point to missing files
  - Methods: getFoo()/setFoo() calls when only foo property exists
  - Syntax: JS syntax errors via esprima AST parsing (requires: pip install esprima)
    Also detects duplicates, dangerous patterns (eval/with/debugger)

Reports:
  - ERRORS: Verifiable issues that must be fixed
  - WARNINGS: Patterns that cannot be verified statically (LLM should review)

Examples:
  ./loom validate                    # Run all validations
  ./loom validate --check dom        # Only check DOM references
  ./loom validate --check syntax     # Only check JS syntax
  ./loom validate --level warn       # Show warnings too
  ./loom validate --json             # Output as JSON (for CI)
""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p_validate.add_argument("--check", choices=["all", "dom", "imports", "methods", "syntax", "exports"], default="all",
                            help="What to validate: all, dom, imports, methods, syntax, exports (default: all)")
    p_validate.add_argument("--level", choices=["error", "warn", "all"], default="error",
                            help="Minimum issue level to show (default: error)")
    p_validate.add_argument("--json", action="store_true", help="Output as JSON")
    p_validate.add_argument("--verbose", "-v", action="store_true", help="Show detailed issue info")
    p_validate.add_argument("--db", default=".loom/store.db", help=db_help)

    # issues - incomplete code detection
    p_issues = subparsers.add_parser("issues", help="Detect incomplete code and wiring issues",
        description="""
Detect incomplete code.

Detects:
  - TODO/FIXME/STUB comments indicating incomplete code
  - Callbacks that are checked but never assigned (wiring issues)
  - Dead code: methods defined but never called (via call graph)
  - Setup/init methods that are never invoked (likely bugs)

These complement the validate command by finding deeper issues.

Output Formats:
  - Default: Human-readable grouped by category
  - --json: Full JSON with all details
  - --critical-issues: CRITICAL_ISSUES.json format for task_runner.py

Examples:
  ./loom issues                    # Find all detectable issues
  ./loom issues --check todo       # Only find TODO comments
  ./loom issues --check callback   # Only find unassigned callbacks
  ./loom issues --check dead_code  # Only find dead code
  ./loom issues --level all        # Include low-priority issues
  ./loom issues --json             # Output as JSON
  ./loom issues --critical-issues  # Output for task_runner.py integration
""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p_issues.add_argument("--check", choices=["all", "todo", "callback", "dead_code"], default="all",
                          help="What to detect: all, todo, callback, dead_code (default: all)")
    p_issues.add_argument("--level", choices=["high", "all"], default="high",
                          help="Include low-priority issues (default: high = critical/high/medium only)")
    p_issues.add_argument("--json", action="store_true", help="Output as JSON")
    p_issues.add_argument("--critical-issues", action="store_true", dest="critical_issues",
                          help="Output in CRITICAL_ISSUES.json format for task_runner.py")
    p_issues.add_argument("--db", default=".loom/store.db", help=db_help)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "test": cmd_test,
        "trace": cmd_trace,
        "ingest": cmd_ingest,
        "analyze": cmd_analyze,
        "query": cmd_query,
        "usages": cmd_usages,
        "impact": cmd_impact,
        "suggest-tests": cmd_suggest_tests,
        "clusters": cmd_clusters,
        "failure-log": cmd_failure_log,
        "attempted-fixes": cmd_attempted_fixes,
        "todo": cmd_todo,
        "validate": cmd_validate,
        "issues": cmd_issues,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
