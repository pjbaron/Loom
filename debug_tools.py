#!/usr/bin/env python3
"""
debug_tools - Debugging and trace analysis functions for Claude Code.

This module provides tools for debugging and runtime trace analysis:
- debug_context: Comprehensive debugging context for an error
- what_happened: Show recent executions of a function
- last_failure: Show the most recent failed trace run
- trace_context: Combine static and runtime info for debugging

All functions auto-discover the .loom/store.db database.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Set

from codestore import CodeStore

# Import shared utilities
from loom_base import (
    _log_usage,
    _find_store,
    _find_entity_by_name,
    _get_file_location,
    _get_code_preview,
    _kind_label,
)

# Import method lookup from core_tools
from core_tools import _find_method_by_class_dot_name


def _extract_names_from_error(error_message: str) -> List[str]:
    """
    Extract function/class names from an error message.

    Looks for patterns like:
    - Function 'foo_bar' not found
    - in <module> foo.bar
    - File "foo.py", line X, in bar_function
    - AttributeError: 'MyClass' object has no attribute 'method'
    """
    import re

    names = []

    # Pattern: File "...", line X, in function_name
    file_line_pattern = r'File "[^"]+", line \d+, in (\w+)'
    names.extend(re.findall(file_line_pattern, error_message))

    # Pattern: 'name' object or 'name' is not
    quote_pattern = r"'(\w+)'"
    names.extend(re.findall(quote_pattern, error_message))

    # Pattern: ClassName.method_name or module.function
    dot_pattern = r'\b(\w+\.\w+)\b'
    names.extend(re.findall(dot_pattern, error_message))

    # Pattern: simple word followed by () - likely function
    func_call_pattern = r'\b(\w+)\s*\('
    names.extend(re.findall(func_call_pattern, error_message))

    # Deduplicate while preserving order
    seen = set()
    unique_names = []
    for name in names:
        # Skip common noise words
        if name.lower() in ('object', 'type', 'none', 'true', 'false', 'self', 'cls',
                           'module', 'str', 'int', 'float', 'list', 'dict', 'set',
                           'file', 'line', 'in', 'is', 'not', 'has', 'no', 'the',
                           'and', 'or', 'for', 'if', 'else', 'def', 'class', 'return'):
            continue
        if name not in seen:
            seen.add(name)
            unique_names.append(name)

    return unique_names[:20]  # Limit to avoid too many lookups


def _build_call_chain(store: CodeStore, entity_id: int, max_depth: int = 5) -> List[dict]:
    """
    Build call chain from entity to its callers.

    Returns list of entities from deepest caller to the entity itself.
    """
    chain = []
    visited = set()

    def _find_path(eid: int, depth: int) -> bool:
        if depth > max_depth:
            return False
        if eid in visited:
            return False
        visited.add(eid)

        callers = store.get_callers(eid)
        if not callers:
            # This is a root caller
            entity = store.get_entity(eid)
            if entity:
                chain.append(entity)
            return True

        # Try to find a path through any caller
        for caller in callers:
            if _find_path(caller["id"], depth + 1):
                entity = store.get_entity(eid)
                if entity:
                    chain.append(entity)
                return True

        return False

    _find_path(entity_id, 0)
    return chain


def _format_value(value, max_length: int = 200) -> str:
    """Format a value for display, truncating if needed."""
    if value is None:
        return "None"

    # Convert to string representation
    try:
        s = repr(value)
    except Exception:
        s = str(value)

    if len(s) > max_length:
        return s[:max_length - 15] + "... [truncated]"
    return s


def _format_args(args, kwargs, max_per_arg: int = 100) -> str:
    """Format function arguments for display."""
    parts = []

    if args:
        for i, arg in enumerate(args):
            formatted = _format_value(arg, max_per_arg)
            parts.append(formatted)

    if kwargs:
        for key, value in kwargs.items():
            formatted = _format_value(value, max_per_arg)
            parts.append(f"{key}={formatted}")

    return ", ".join(parts) if parts else "(no arguments)"


def _format_timestamp(iso_str: str) -> str:
    """Format ISO timestamp for display."""
    if not iso_str:
        return "?"
    try:
        # Parse and format more readably
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_str[:19] if len(iso_str) >= 19 else iso_str


def _format_duration(duration_ms: float) -> str:
    """Format duration in human-readable form."""
    if duration_ms is None:
        return "?"
    if duration_ms < 1:
        return f"{duration_ms * 1000:.0f}μs"
    elif duration_ms < 1000:
        return f"{duration_ms:.1f}ms"
    else:
        return f"{duration_ms / 1000:.2f}s"


def debug_context(error_message: str, file_path: str = None) -> str:
    """
    Build comprehensive debugging context for an error.

    Automatically includes:
    1. Static analysis - what the code is, what calls it
    2. Recent traces - what happened when it ran
    3. Related hypotheses - what we think might be wrong
    4. Similar past failures - have we seen this before?

    This is the single function Claude Code should call after ./loom test fails.
    It returns everything needed to understand the failure in one block.

    Args:
        error_message: The error message or traceback to analyze
        file_path: Optional path to the file where the error occurred

    Returns:
        Comprehensive debug context ready for LLM consumption
    """
    _log_usage('debug_context', f'{file_path}: {error_message[:30]}', '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    output_lines = [
        "=" * 70,
        "DEBUG CONTEXT",
        "=" * 70,
        "",
        f"Error: {error_message[:200]}{'...' if len(error_message) > 200 else ''}",
        "",
    ]

    # Track entities we've found for deduplication
    found_entities = {}  # name -> entity
    error_location_entity = None

    # ===== SECTION 1: Extract Names and Find Entities =====

    # Parse error_message to extract function/class names
    extracted_names = _extract_names_from_error(error_message)

    # If file_path given, find that module and its relationships
    if file_path:
        path = Path(file_path)
        module_name = path.stem

        modules = store.find_entities(name=module_name, kind="module")
        if modules:
            module = modules[0]
            error_location_entity = module
            found_entities[module["name"]] = module

            children = store.find_related(module["id"], relation="contains", direction="outgoing")
            for child in children:
                found_entities[child["name"]] = child

    # For each extracted name, try to find matching entities
    for name in extracted_names:
        if name in found_entities:
            continue

        entity = _find_entity_by_name(store, name)
        if entity:
            found_entities[entity["name"]] = entity
            if error_location_entity is None:
                error_location_entity = entity

    # ===== SECTION 2: Runtime Trace Data (MOST IMPORTANT) =====

    trace_section_added = False
    most_recent_failure = None
    similar_failures = []

    try:
        # Get the most recent failed run
        failed_calls = store.get_failed_calls(limit=20)

        if failed_calls:
            # Find failures matching extracted names
            relevant_failures = []
            for call in failed_calls:
                func_name = call.get('function_name', '')
                func_short = func_name.split('.')[-1] if func_name else ''

                for name in extracted_names:
                    if name in func_name or name == func_short:
                        relevant_failures.append(call)
                        break
                else:
                    # Also check exception message similarity
                    exc_msg = call.get('exception_message', '')
                    exc_type = call.get('exception_type', '')
                    if exc_type and exc_type in error_message:
                        similar_failures.append(call)

            if relevant_failures:
                most_recent_failure = relevant_failures[0]
            elif failed_calls:
                # No match by name, but show most recent failure anyway
                most_recent_failure = failed_calls[0]

        if most_recent_failure:
            trace_section_added = True
            output_lines.append("-" * 70)
            output_lines.append("RUNTIME TRACE (from most recent failure)")
            output_lines.append("-" * 70)
            output_lines.append("")

            # Show the exception
            output_lines.append(f"Exception: {most_recent_failure.get('exception_type', '?')}")
            exc_msg = most_recent_failure.get('exception_message', '')
            output_lines.append(f"Message:   {exc_msg[:150]}{'...' if len(exc_msg) > 150 else ''}")
            output_lines.append("")

            # Show where it failed
            func_name = most_recent_failure.get('function_name', '?')
            file_loc = most_recent_failure.get('file_path', '?')
            line_num = most_recent_failure.get('line_number', '?')
            output_lines.append(f"Failed in: {func_name}")
            output_lines.append(f"Location:  {file_loc}:{line_num}")
            output_lines.append("")

            # Show arguments that caused the failure
            args_json = most_recent_failure.get('args_json')
            kwargs_json = most_recent_failure.get('kwargs_json')
            if args_json or kwargs_json:
                args = json.loads(args_json) if args_json else []
                kwargs = json.loads(kwargs_json) if kwargs_json else {}
                args_str = _format_args(args, kwargs, max_per_arg=80)
                output_lines.append(f"Arguments: {args_str}")
                output_lines.append("")

            # Build call stack from run
            run_id = most_recent_failure.get('run_id')
            if run_id:
                all_calls = store.get_calls_for_run(run_id, include_args=True)
                if all_calls:
                    # Build parent chain from the failed call
                    call_stack = []
                    current_call_id = most_recent_failure.get('call_id')
                    calls_by_id = {c['call_id']: c for c in all_calls}

                    current = calls_by_id.get(current_call_id)
                    while current:
                        call_stack.insert(0, current)
                        parent_id = current.get('parent_call_id')
                        current = calls_by_id.get(parent_id) if parent_id else None

                    if len(call_stack) > 1:
                        output_lines.append("Call Stack:")
                        for call in call_stack:
                            depth = call.get('depth', 0)
                            func = call.get('function_name', '?').split('.')[-1]
                            indent = "  " * depth
                            is_failed = call.get('call_id') == current_call_id
                            marker = " <-- FAILED HERE" if is_failed else ""

                            call_args = call.get('args', [])
                            call_kwargs = call.get('kwargs', {})
                            args_preview = _format_args(call_args, call_kwargs, max_per_arg=40)

                            output_lines.append(f"  {indent}{func}({args_preview}){marker}")
                        output_lines.append("")

            # Show traceback (abbreviated)
            tb = most_recent_failure.get('exception_traceback', '')
            if tb:
                output_lines.append("Traceback (key lines):")
                tb_lines = tb.strip().split('\n')
                # Show last 8 relevant lines, skip framework noise
                relevant_tb = [l for l in tb_lines if 'site-packages' not in l][-8:]
                for line in relevant_tb:
                    output_lines.append(f"  {line}")
                output_lines.append("")

    except Exception as e:
        # Don't break on trace errors
        pass

    # ===== SECTION 3: Static Analysis =====

    output_lines.append("-" * 70)
    output_lines.append("STATIC ANALYSIS")
    output_lines.append("-" * 70)
    output_lines.append("")

    if found_entities:
        output_lines.append("Relevant Code:")
        for name, entity in list(found_entities.items())[:8]:
            kind = _kind_label(entity["kind"])
            intent = entity.get("intent") or "No description"
            if len(intent) > 60:
                intent = intent[:57] + "..."
            file_loc = _get_file_location(entity)
            output_lines.append(f"  [{kind}] {entity['name'].split('.')[-1]}")
            output_lines.append(f"       {intent}")
            output_lines.append(f"       {file_loc}")
        output_lines.append("")

    # Call chain if we have an error location
    if error_location_entity and error_location_entity["kind"] in ("function", "method"):
        chain = _build_call_chain(store, error_location_entity["id"])
        if chain and len(chain) > 1:
            output_lines.append("Call Chain (static):")
            chain_names = [e["name"].split(".")[-1] for e in chain]
            output_lines.append(f"  {' -> '.join(chain_names)}")
            output_lines.append("")

        # Callers
        callers = store.get_callers(error_location_entity["id"])
        if callers:
            caller_names = [c["name"].split(".")[-1] for c in callers[:5]]
            output_lines.append(f"Called by: {', '.join(caller_names)}")
            output_lines.append("")

    # Impact if modified
    if error_location_entity:
        impact = store.impact_analysis(error_location_entity["id"])
        if impact["risk_score"] > 3:
            short_name = error_location_entity['name'].split('.')[-1]
            output_lines.append(f"Impact if '{short_name}' is modified:")
            output_lines.append(f"  Risk score: {impact['risk_score']} (entities affected)")
            if impact["direct_callers"]:
                caller_names = [c["name"].split(".")[-1] for c in impact["direct_callers"][:5]]
                output_lines.append(f"  Direct callers: {', '.join(caller_names)}")
            output_lines.append("")

    # ===== SECTION 4: Related Hypotheses =====

    hypotheses_found = []
    try:
        for name in extracted_names[:5]:
            notes = store.get_entity_notes(name)
            for note in notes:
                if note.get('type') == 'hypothesis' and note.get('status') == 'active':
                    hypotheses_found.append(note)
    except Exception:
        pass

    if hypotheses_found:
        output_lines.append("-" * 70)
        output_lines.append("RELATED HYPOTHESES")
        output_lines.append("-" * 70)
        output_lines.append("")

        for h in hypotheses_found[:3]:
            title = h.get('title', 'Untitled')
            content = h.get('content', '')[:100]
            note_id = h.get('id', '')[:8]
            output_lines.append(f"  [{note_id}...] {title}")
            output_lines.append(f"       {content}{'...' if len(h.get('content', '')) > 100 else ''}")
        output_lines.append("")

    # ===== SECTION 5: Similar Past Failures =====

    if similar_failures and len(similar_failures) > 1:
        output_lines.append("-" * 70)
        output_lines.append("SIMILAR PAST FAILURES")
        output_lines.append("-" * 70)
        output_lines.append("")

        # Group by exception type
        exc_types = {}
        for f in similar_failures[:10]:
            exc_type = f.get('exception_type', 'Unknown')
            if exc_type not in exc_types:
                exc_types[exc_type] = 0
            exc_types[exc_type] += 1

        for exc_type, count in exc_types.items():
            output_lines.append(f"  {exc_type}: {count} occurrence(s)")
        output_lines.append("")

    # ===== SECTION 6: Suggested Tests =====

    test_modules = set()
    for entity in list(found_entities.values())[:5]:
        tests = store.suggest_tests(entity["id"])
        test_modules.update(tests[:3])

    if test_modules:
        output_lines.append("-" * 70)
        output_lines.append("SUGGESTED TESTS")
        output_lines.append("-" * 70)
        output_lines.append("")

        for test_name in sorted(test_modules)[:5]:
            test_entities = store.find_entities(name=test_name, kind="module")
            if test_entities:
                metadata = test_entities[0].get("metadata") or {}
                file_loc = metadata.get("file_path", test_name)
                output_lines.append(f"  {file_loc}")
            else:
                output_lines.append(f"  {test_name}")
        output_lines.append("")

    # ===== SECTION 7: No Data Warning =====

    if not found_entities and not trace_section_added:
        output_lines.append("No matching code or trace data found.")
        output_lines.append("")
        output_lines.append("Suggestions:")
        output_lines.append("  - Run './loom ingest .' to index the codebase")
        output_lines.append("  - Run './loom test' to capture trace data on failures")
        output_lines.append("  - Check if the error references external libraries")
        output_lines.append("")

    # ===== Footer =====

    output_lines.append("=" * 70)
    output_lines.append("NEXT STEPS")
    output_lines.append("=" * 70)
    output_lines.append("")
    output_lines.append("1. Review the traceback and arguments above")
    output_lines.append("2. Check the code at the failed location")
    if extracted_names:
        first_name = extracted_names[0]
        output_lines.append(f"3. For more trace detail: what_happened('{first_name}')")
        output_lines.append(f"4. For full failure info: last_failure()")
    output_lines.append("5. Record hypothesis: ./loom hypothesis 'I think...'")
    output_lines.append("")

    store.close()
    return "\n".join(output_lines)


def what_happened(function_name: str, limit: int = 5) -> str:
    """
    Show recent executions of a function.

    Returns formatted history of calls including:
    - When it was called
    - What arguments it received
    - What it returned (or what exception it raised)
    - How long it took

    Args:
        function_name: Name of the function to look up (exact or partial match)
        limit: Maximum number of calls to show (default 5)

    Returns:
        Formatted execution history optimized for LLM consumption
    """
    _log_usage('what_happened', function_name, '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    try:
        # Try exact match first, then LIKE pattern
        calls = store.get_recent_calls(function_name, limit=limit, include_args=True)

        if not calls:
            # Try with wildcard
            calls = store.get_recent_calls(f"%{function_name}%", limit=limit, include_args=True)

        if not calls:
            return f"No trace data found for '{function_name}'.\n\nHint: Trace data is captured when code runs with @trace decorator and trace_run() context."

        lines = [
            f"## Execution History: {function_name}",
            f"Showing {len(calls)} most recent call(s)",
            ""
        ]

        for i, call in enumerate(calls, 1):
            func_name = call.get('function_name', '?')
            called_at = _format_timestamp(call.get('called_at'))
            duration = _format_duration(call.get('duration_ms'))

            # Format arguments
            args = call.get('args', [])
            kwargs = call.get('kwargs', {})
            args_str = _format_args(args, kwargs)

            lines.append(f"### Call {i}: {func_name}")
            lines.append(f"When: {called_at}")
            lines.append(f"Duration: {duration}")
            lines.append(f"Args: {args_str}")

            # Show result or exception
            if call.get('exception_type'):
                lines.append(f"RAISED: {call['exception_type']}: {call.get('exception_message', '')}")
                # Include relevant traceback lines (last 5)
                tb = call.get('exception_traceback', '')
                if tb:
                    tb_lines = tb.strip().split('\n')[-5:]
                    lines.append("Traceback (last 5 lines):")
                    for tb_line in tb_lines:
                        lines.append(f"  {tb_line}")
            else:
                return_val = call.get('return_value')
                lines.append(f"Returned: {_format_value(return_val)}")

            # Show location if available
            file_path = call.get('file_path')
            line_number = call.get('line_number')
            if file_path:
                lines.append(f"Location: {file_path}:{line_number or '?'}")

            lines.append("")

        return "\n".join(lines)
    finally:
        store.close()


def last_failure() -> str:
    """
    Show the call tree from the most recent failed trace run.

    Returns:
    - The exception that occurred
    - The function that raised it
    - The call stack leading to it
    - Arguments at each level
    """
    _log_usage('last_failure', '', '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    try:
        # Get most recent failed call
        failed_calls = store.get_failed_calls(limit=1)

        if not failed_calls:
            return "No failed executions found in trace history."

        failed_call = failed_calls[0]
        run_id = failed_call.get('run_id')

        lines = [
            "## Most Recent Failure",
            ""
        ]

        # Show the run context
        run = store.get_trace_run(run_id)
        if run:
            lines.append(f"Run: {run.get('command', 'unknown command')}")
            lines.append(f"Started: {_format_timestamp(run.get('started_at'))}")
            lines.append(f"Status: {run.get('status', '?')}")
            lines.append("")

        # Show the exception
        lines.append("### Exception")
        lines.append(f"Type: {failed_call.get('exception_type', '?')}")
        lines.append(f"Message: {failed_call.get('exception_message', '?')}")
        lines.append("")

        # Show the failing function
        lines.append("### Failed In")
        func_name = failed_call.get('function_name', '?')
        file_path = failed_call.get('file_path', '?')
        line_number = failed_call.get('line_number', '?')
        lines.append(f"Function: {func_name}")
        lines.append(f"Location: {file_path}:{line_number}")

        # Parse and show arguments
        args_json = failed_call.get('args_json')
        kwargs_json = failed_call.get('kwargs_json')
        args = []
        kwargs = {}
        if args_json:
            try:
                args = json.loads(args_json)
            except Exception:
                pass
        if kwargs_json:
            try:
                kwargs = json.loads(kwargs_json)
            except Exception:
                pass

        lines.append(f"Arguments: {_format_args(args, kwargs)}")
        lines.append("")

        # Build call stack from parent_call_id chain
        lines.append("### Call Stack")

        # Get all calls for this run to build the stack
        all_calls = store.get_calls_for_run(run_id, include_args=True)

        # Build parent chain from the failed call
        call_stack = []
        current_call_id = failed_call.get('call_id')
        calls_by_id = {c['call_id']: c for c in all_calls}

        # Start with the failed call and walk up
        current = calls_by_id.get(current_call_id)
        while current:
            call_stack.insert(0, current)
            parent_id = current.get('parent_call_id')
            current = calls_by_id.get(parent_id) if parent_id else None

        if not call_stack:
            # Fallback: just show calls ordered by depth
            call_stack = sorted(
                [c for c in all_calls if c.get('depth', 0) <= failed_call.get('depth', 0)],
                key=lambda c: c.get('depth', 0)
            )[-10:]  # Last 10 calls leading to failure

        for i, call in enumerate(call_stack):
            depth = call.get('depth', 0)
            func = call.get('function_name', '?').split('.')[-1]
            indent = "  " * depth

            call_args = call.get('args', [])
            call_kwargs = call.get('kwargs', {})
            args_preview = _format_args(call_args, call_kwargs, max_per_arg=50)

            is_failed = call.get('call_id') == failed_call.get('call_id')
            marker = " <-- FAILED" if is_failed else ""

            lines.append(f"{indent}{func}({args_preview}){marker}")

        lines.append("")

        # Show full traceback
        tb = failed_call.get('exception_traceback', '')
        if tb:
            lines.append("### Full Traceback")
            lines.append("```")
            lines.append(tb.strip())
            lines.append("```")

        return "\n".join(lines)
    finally:
        store.close()


def trace_context(function_name: str) -> str:
    """
    Build debugging context for a function from traces.

    Combines:
    - Static info from understand()
    - Recent execution history from traces
    - Any exceptions this function has raised

    Args:
        function_name: Name of the function to analyze

    Returns:
        Comprehensive debugging context optimized for LLM consumption
    """
    _log_usage('trace_context', function_name, '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    lines = [
        f"## Trace Context: {function_name}",
        ""
    ]

    try:
        # 1. Static info
        entity = _find_entity_by_name(store, function_name)
        if not entity and "." in function_name:
            entity = _find_method_by_class_dot_name(store, function_name)

        if entity:
            lines.append("### Static Analysis")
            lines.append(f"Type: {entity['kind']}")
            lines.append(f"Full name: {entity['name']}")
            lines.append(f"Location: {_get_file_location(entity)}")

            intent = entity.get('intent')
            if intent:
                lines.append(f"Purpose: {intent[:200]}{'...' if len(intent) > 200 else ''}")

            # Show callers
            callers = store.get_callers(entity['id'])
            if callers:
                caller_names = [c['name'].split('.')[-1] for c in callers[:5]]
                lines.append(f"Called by: {', '.join(caller_names)}")

            lines.append("")
        else:
            lines.append("### Static Analysis")
            lines.append(f"Entity '{function_name}' not found in static analysis.")
            lines.append("(May be from external library or not yet ingested)")
            lines.append("")

        # 2. Recent execution history
        calls = store.get_recent_calls(function_name, limit=5, include_args=True)
        if not calls:
            calls = store.get_recent_calls(f"%{function_name}%", limit=5, include_args=True)

        if calls:
            lines.append("### Recent Executions")

            success_count = sum(1 for c in calls if not c.get('exception_type'))
            fail_count = len(calls) - success_count

            lines.append(f"Last {len(calls)} calls: {success_count} succeeded, {fail_count} failed")

            # Show timing stats
            durations = [c.get('duration_ms') for c in calls if c.get('duration_ms') is not None]
            if durations:
                avg_duration = sum(durations) / len(durations)
                lines.append(f"Avg duration: {_format_duration(avg_duration)}")

            # Show most recent call details
            latest = calls[0]
            lines.append("")
            lines.append("Most recent call:")
            lines.append(f"  When: {_format_timestamp(latest.get('called_at'))}")
            lines.append(f"  Args: {_format_args(latest.get('args', []), latest.get('kwargs', {}))}")

            if latest.get('exception_type'):
                lines.append(f"  FAILED: {latest['exception_type']}: {latest.get('exception_message', '')}")
            else:
                lines.append(f"  Returned: {_format_value(latest.get('return_value'))}")

            lines.append("")
        else:
            lines.append("### Recent Executions")
            lines.append("No trace data available for this function.")
            lines.append("")

        # 3. Exception history
        # Get all failed calls for this function
        all_failed = store.get_failed_calls(limit=100)
        function_failures = [
            c for c in all_failed
            if function_name in c.get('function_name', '') or
               function_name == c.get('function_name', '').split('.')[-1]
        ][:5]

        if function_failures:
            lines.append("### Exception History")

            # Group by exception type
            exception_types = {}
            for call in function_failures:
                exc_type = call.get('exception_type', 'Unknown')
                if exc_type not in exception_types:
                    exception_types[exc_type] = []
                exception_types[exc_type].append(call)

            for exc_type, exc_calls in exception_types.items():
                lines.append(f"- {exc_type}: {len(exc_calls)} occurrence(s)")
                # Show most recent message for this type
                latest_msg = exc_calls[0].get('exception_message', '')
                if latest_msg:
                    lines.append(f"  Latest: {latest_msg[:100]}{'...' if len(latest_msg) > 100 else ''}")

            lines.append("")

        # Add debugging suggestions
        if function_failures or (calls and any(c.get('exception_type') for c in calls)):
            lines.append("### Debugging Suggestions")
            lines.append("- Review the exception tracebacks above")
            lines.append("- Check input validation for the arguments shown")
            lines.append("- Use what_happened() for detailed call-by-call analysis")
            if entity:
                lines.append(f"- Use what_breaks_if_i_change('{function_name}') to assess fix impact")

        return "\n".join(lines)
    finally:
        store.close()
