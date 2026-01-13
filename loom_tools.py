#!/usr/bin/env python3
"""
loom_tools - Simple functions for Claude Code to understand codebases.

This module provides primitives that Claude Code can call during debugging
and development to understand code before modifying it.

All functions return formatted strings ready for LLM consumption.

NOTE: Loom currently only supports Python codebases - it uses Python's ast module for parsing.

This is a facade module that re-exports functions from:
- loom_base: Shared utilities
- core_tools: Core query functions (understand, what_calls, etc.)
- debug_tools: Debug/trace functions (debug_context, last_failure, etc.)
- knowledge_tools: Knowledge base functions (add_finding, add_hypothesis, etc.)
- graph_tools: Architecture analysis functions (architecture, central_entities, etc.)
"""

from pathlib import Path

# Re-export base utilities (for internal use by other modules)
from loom_base import (
    LOOM_INSTRUMENTATION,
    _log_usage,
    _find_store,
    _find_entity_by_name,
    _get_file_location,
    _get_code_preview,
    _kind_label,
)

# Re-export core query tools
from core_tools import (
    understand,
    what_calls,
    what_breaks_if_i_change,
    which_tests,
    explain_module,
    explain_class,
    _find_method_by_class_dot_name,
    _format_entity_display_name,
)

# Re-export debug/trace tools
from debug_tools import (
    debug_context,
    what_happened,
    last_failure,
    trace_context,
    _extract_names_from_error,
    _build_call_chain,
    _format_value,
    _format_args,
    _format_timestamp,
    _format_duration,
)

# Re-export knowledge tools
from knowledge_tools import (
    add_finding,
    add_intent,
    add_hypothesis,
    resolve_hypothesis,
    whats_known_about,
    search_knowledge,
    knowledge_stats,
)

# Re-export graph/architecture tools
from graph_tools import (
    architecture,
    central_entities,
    orphan_entities,
    find_path,
)

# Re-export failure tracking tools
from failure_tools import (
    log_failed_attempt,
    what_have_we_tried,
    recent_failures,
)

# Re-export TODO/work item tracking tools
from todo_tools import (
    add_todo,
    add_todo_verbose,
    todos,
    get_todos,
    next_todo,
    start_todo,
    complete_todo,
    combine_todos,
    update_todo,
    search_todos,
    todo_stats,
    delete_todo,
    reorder_todo,
)


def usage_report() -> str:
    """
    Generate a summary report of Loom tool usage.

    Reads .loom/usage.log and returns:
    - Total calls per tool
    - Last 10 calls with timestamps

    Returns:
        Formatted usage report or 'No usage logged yet' if no log exists
    """
    try:
        # Find .loom directory by searching upward
        current = Path.cwd()
        log_path = None

        for directory in [current] + list(current.parents):
            candidate = directory / ".loom" / "usage.log"
            if candidate.exists():
                log_path = candidate
                break

        if not log_path or not log_path.exists():
            return "No usage logged yet"

        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            return "No usage logged yet"

        # Count calls per tool
        tool_counts = {}
        parsed_entries = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                timestamp, tool_name, query = parts[0], parts[1], parts[2]
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
                parsed_entries.append((timestamp, tool_name, query))

        output_lines = [
            "Loom Usage Report",
            "=" * 40,
            "",
            "Total calls per tool:",
        ]

        for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
            output_lines.append(f"  {tool}: {count}")

        output_lines.append("")
        output_lines.append("Last 10 calls:")

        for timestamp, tool_name, query in parsed_entries[-10:]:
            # Format timestamp more readably (just time portion if today)
            ts_short = timestamp.split("T")[1][:8] if "T" in timestamp else timestamp[:19]
            output_lines.append(f"  [{ts_short}] {tool_name}: {query}")

        return "\n".join(output_lines)

    except Exception as e:
        return f"Error reading usage log: {e}"


def help() -> str:
    """List all available loom_tools functions and their purposes."""
    return """Loom Tools - Code Understanding Primitives for Claude Code

Available functions:

DEBUGGING:
1. debug_context(error_message: str, file_path: str = None) -> str
   THE primary debugging tool. Call this after ./loom test fails.
   Automatically includes: trace data, call stack, static analysis, hypotheses, similar failures.
   Returns everything needed to understand a failure in one block.
   Example: debug_context("AttributeError: 'NoneType' object has no attribute 'id'")

2. what_happened(function_name: str, limit: int = 5) -> str
   Show recent executions of a function from runtime traces.
   Shows: when called, arguments, return values/exceptions, duration.
   Example: what_happened("process_request")

3. last_failure() -> str
   Show the call tree from the most recent failed trace run.
   Shows: exception, failing function, call stack with args, full traceback.
   Example: last_failure()

4. trace_context(function_name: str) -> str
   Combined static + runtime analysis for a function.
   Shows: code info, recent executions, exception history, debugging suggestions.
   Example: trace_context("validate_user")

STATIC ANALYSIS:
5. understand(query: str) -> str
   Semantic search for code matching a natural language query.
   Example: understand("authentication logic")

6. what_calls(name: str) -> str
   Find all functions that call a given entity.
   Example: what_calls("validate_user")

7. what_breaks_if_i_change(name: str) -> str
   Impact analysis showing blast radius of changes.
   Example: what_breaks_if_i_change("process_request")

8. which_tests(name: str) -> str
   Find relevant test files for an entity.
   Example: which_tests("DatabaseConnection")

9. explain_module(name: str) -> str
   Get structured overview of a module's contents.
   Example: explain_module("codestore")

10. explain_class(name: str) -> str
    Get detailed overview of a class and all its methods.
    Example: explain_class("CodeStore")

All functions auto-discover the .loom/store.db database.
Run './loom ingest <path>' to create the database first.

Note: what_calls() and what_breaks_if_i_change() support 'ClassName.method_name'
format for looking up methods (e.g., what_calls("CodeStore.get_entity")).

KNOWLEDGE MANAGEMENT:
- add_finding(content, title=None, related_to=None): Record an analysis finding
- add_intent(entity_name, intent): Document WHY an entity exists
- add_hypothesis(hypothesis, related_to=None): Record a debugging hypothesis
- resolve_hypothesis(note_id, confirmed, conclusion=None): Mark hypothesis as confirmed/refuted
- whats_known_about(entity_name): Get all notes about an entity
- search_knowledge(query): Search all notes
- knowledge_stats(): Get statistics about accumulated knowledge

ARCHITECTURE ANALYSIS:
- architecture(): Get high-level codebase overview
- central_entities(limit=10): Find most connected code
- orphan_entities(): Find potentially dead code
- find_path(from_name, to_name): Find how two entities relate

FAILURE TRACKING:
- log_failed_attempt(attempted_fix, context=None, entity=None, file=None, reason=None):
  Record a failed fix attempt to avoid repeating unsuccessful approaches
- what_have_we_tried(entity=None, file=None, limit=20):
  Get a summary of what fixes have been attempted for an entity or file
- recent_failures(days=7, limit=10):
  Get recent failure attempts from the last N days

TODO/WORK ITEM TRACKING (Simple API for LLM use):
- add_todo(title, prompt, context=None, tags=None, critical=False) -> int:
  Add a new TODO to the queue. Returns the TODO id.
  Example: id = add_todo("Fix parser bug", "Handle escaped quotes in strings", tags=["bug"])

- get_todos(status='pending', limit=10) -> str:
  Get formatted list of TODOs.
  Example: print(get_todos())

- next_todo() -> str:
  Get the next TODO to work on (highest priority, FIFO).
  Example: print(next_todo())

- complete_todo(todo_id, notes=None) -> str:
  Mark a TODO as completed.
  Example: complete_todo(5, notes="Fixed by adding null check")

- todo_stats() -> str:
  Get quick stats on TODO queue.
  Example: print(todo_stats())

Additional TODO functions:
- todos(status=None, entity=None, file=None, limit=20): Full-featured TODO listing
- start_todo(todo_id): Mark a TODO as in-progress
- combine_todos(keep_id, merge_ids, new_prompt=None): Combine overlapping TODOs
- update_todo(todo_id, prompt=None, context=None, priority=None, tags=None): Update fields
- search_todos(query, limit=10): Search TODOs by text
- delete_todo(todo_id): Delete a TODO
- reorder_todo(todo_id, new_position): Move TODO in queue

RUNTIME TRACING:
To capture trace data, decorate functions with @trace and run within trace_run():
    from tracer import trace, trace_run

    @trace
    def my_function(x): ...

    with trace_run(command="my_script.py"):
        my_function(42)
"""


# For backwards compatibility, also expose the _get_codestore alias
def _get_codestore():
    """Get CodeStore instance, same as _find_store but with clearer name for notes API."""
    return _find_store()


# Export all public functions
__all__ = [
    # Core query tools
    'understand',
    'what_calls',
    'what_breaks_if_i_change',
    'which_tests',
    'explain_module',
    'explain_class',
    # Debug/trace tools
    'debug_context',
    'what_happened',
    'last_failure',
    'trace_context',
    # Knowledge tools
    'add_finding',
    'add_intent',
    'add_hypothesis',
    'resolve_hypothesis',
    'whats_known_about',
    'search_knowledge',
    'knowledge_stats',
    # Graph/architecture tools
    'architecture',
    'central_entities',
    'orphan_entities',
    'find_path',
    # Failure tracking tools
    'log_failed_attempt',
    'what_have_we_tried',
    'recent_failures',
    # TODO/work item tracking tools
    'add_todo',
    'add_todo_verbose',
    'todos',
    'get_todos',
    'next_todo',
    'start_todo',
    'complete_todo',
    'combine_todos',
    'update_todo',
    'search_todos',
    'todo_stats',
    'delete_todo',
    'reorder_todo',
    # Meta tools
    'usage_report',
    'help',
]
