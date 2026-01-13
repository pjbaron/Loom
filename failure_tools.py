#!/usr/bin/env python3
"""
failure_tools - Convenience functions for tracking failed fix attempts.

This module provides high-level functions for logging and querying failed fixes
to help developers avoid repeating unsuccessful approaches.

Functions:
    log_failed_attempt: Log a failed fix attempt
    what_have_we_tried: Get a summary of what fixes have been attempted
    recent_failures: Get recent failure attempts
"""

from typing import List, Optional

from loom_base import _find_store, _log_usage


def log_failed_attempt(
    attempted_fix: str,
    context: str = None,
    entity: str = None,
    file: str = None,
    reason: str = None,
    error: str = None,
    tags: list = None,
    store_path: str = ".loom/store.db"
) -> int:
    """
    Log a failed fix attempt.

    This function records information about a fix that didn't work, making it
    easier to avoid repeating the same unsuccessful approaches.

    Args:
        attempted_fix: Description of what was tried (required)
        context: What was being worked on (e.g., "KeyError in process_data")
        entity: Name of the function/class being fixed
        file: File path being worked on
        reason: Why it didn't work
        error: Related error message
        tags: List of tags for categorization
        store_path: Path to the Loom database (default: .loom/store.db)

    Returns:
        ID of the created failure log entry

    Example:
        log_failed_attempt(
            "Tried using .get() instead of []",
            context="KeyError in process_data",
            file="data_processor.py",
            reason="Still got KeyError on missing keys"
        )
    """
    from codestore import CodeStore

    # Try to find existing store first, fall back to specified path
    store = _find_store()
    if store is None:
        store = CodeStore(store_path)

    try:
        failure_id = store.log_failure(
            attempted_fix=attempted_fix,
            context=context,
            entity_name=entity,
            file_path=file,
            failure_reason=reason,
            related_error=error,
            tags=tags or []
        )

        # Log usage for instrumentation
        _log_usage(
            "log_failed_attempt",
            attempted_fix[:50],
            f"Logged failure #{failure_id}"
        )

        return failure_id
    finally:
        store.close()


def what_have_we_tried(
    entity: str = None,
    file: str = None,
    tags: list = None,
    limit: int = 20,
    store_path: str = ".loom/store.db"
) -> str:
    """
    Get a summary of what fixes have been attempted.

    Use this to check what approaches have already been tried for a given
    entity or file, helping to avoid repeating unsuccessful fixes.

    Args:
        entity: Filter by entity name
        file: Filter by file path
        tags: Filter by tags (any match)
        limit: Maximum number of results (default 20)
        store_path: Path to the Loom database (default: .loom/store.db)

    Returns:
        Formatted string describing the failed attempts

    Example:
        print(what_have_we_tried(file="data_processor.py"))
        print(what_have_we_tried(entity="process_data"))
    """
    from codestore import CodeStore

    # Try to find existing store first, fall back to specified path
    store = _find_store()
    if store is None:
        store = CodeStore(store_path)

    try:
        logs = store.get_failure_logs(
            entity_name=entity,
            file_path=file,
            tags=tags,
            limit=limit
        )

        if not logs:
            result = "No failed attempts found."
            _log_usage(
                "what_have_we_tried",
                entity or file or "all",
                result
            )
            return result

        lines = [f"\nFound {len(logs)} failed attempts:\n"]

        for i, log in enumerate(logs, 1):
            # Build header with timestamp and entity info
            header = f"{i}. [{log['timestamp'][:19]}]"
            if log.get('entity_name'):
                header += f" {log['entity_name']}"
            if log.get('file_path'):
                header += f" ({log['file_path']})"
            lines.append(header)

            # Add the attempted fix
            lines.append(f"   Tried: {log['attempted_fix']}")

            # Add failure reason if available
            if log.get('failure_reason'):
                lines.append(f"   Failed: {log['failure_reason']}")

            # Add context if available
            if log.get('context'):
                lines.append(f"   Context: {log['context']}")

            # Add tags if available
            if log.get('tags') and len(log['tags']) > 0:
                lines.append(f"   Tags: {', '.join(log['tags'])}")

            lines.append("")

        result = "\n".join(lines)

        _log_usage(
            "what_have_we_tried",
            entity or file or "all",
            f"Found {len(logs)} failures"
        )

        return result
    finally:
        store.close()


def recent_failures(
    days: int = 7,
    limit: int = 10,
    store_path: str = ".loom/store.db"
) -> str:
    """
    Get recent failure attempts.

    Shows failures from the last N days, useful for reviewing what's been
    tried during an active debugging session.

    Args:
        days: Number of days to look back (default 7)
        limit: Maximum number of results (default 10)
        store_path: Path to the Loom database (default: .loom/store.db)

    Returns:
        Formatted string describing recent failures

    Example:
        print(recent_failures(days=1))  # Just today
        print(recent_failures(days=7, limit=20))  # Last week
    """
    from codestore import CodeStore

    # Try to find existing store first, fall back to specified path
    store = _find_store()
    if store is None:
        store = CodeStore(store_path)

    try:
        logs = store.get_recent_failures(days=days, limit=limit)

        if not logs:
            result = f"No failures in the last {days} day(s)."
            _log_usage(
                "recent_failures",
                f"{days} days",
                result
            )
            return result

        lines = [f"\nRecent failures (last {days} day(s)):\n"]

        for i, log in enumerate(logs, 1):
            lines.append(f"{i}. {log['attempted_fix']}")
            lines.append(f"   {log['timestamp'][:19]}")
            if log.get('file_path'):
                lines.append(f"   {log['file_path']}")
            if log.get('entity_name'):
                lines.append(f"   Entity: {log['entity_name']}")
            if log.get('failure_reason'):
                lines.append(f"   Reason: {log['failure_reason']}")
            lines.append("")

        result = "\n".join(lines)

        _log_usage(
            "recent_failures",
            f"{days} days",
            f"Found {len(logs)} failures"
        )

        return result
    finally:
        store.close()
