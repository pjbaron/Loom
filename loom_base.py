#!/usr/bin/env python3
"""
loom_base - Shared utilities for loom tools.

This module provides common functions used across all tool modules:
- _log_usage: Instrumentation logging
- _find_store: Database discovery
- _find_entity_by_name: Entity lookup
- _get_file_location: File path formatting
- _get_code_preview: Code preview extraction
- _kind_label: Entity kind formatting

All loom tool modules should import these from here.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from codestore import CodeStore

# Instrumentation toggle - set to False to disable usage logging
LOOM_INSTRUMENTATION = True

# Project context configuration
LOOM_CONFIG_DIR = Path.home() / ".config" / "loom"
ACTIVE_PROJECT_FILE = LOOM_CONFIG_DIR / "active_project"


def get_active_project() -> Optional[Path]:
    """
    Get the currently active project path from config.

    Returns None if no active project set or if the project no longer exists.
    """
    if not ACTIVE_PROJECT_FILE.exists():
        return None

    try:
        path_str = ACTIVE_PROJECT_FILE.read_text().strip()
        if not path_str:
            return None

        path = Path(path_str)
        # Verify the project database still exists
        if (path / ".loom" / "store.db").exists():
            return path
    except Exception:
        pass

    return None


def set_active_project(project_path: Path) -> None:
    """
    Set the active project path in config.

    Creates the config directory if it doesn't exist.
    """
    LOOM_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_PROJECT_FILE.write_text(str(project_path.resolve()))


def clear_active_project() -> None:
    """Clear the active project setting."""
    if ACTIVE_PROJECT_FILE.exists():
        ACTIVE_PROJECT_FILE.unlink()


def _log_usage(tool_name: str, query: str, result_summary: str) -> None:
    """
    Log tool usage to .loom/usage.log for instrumentation.

    Fails silently to never break actual functionality.
    """
    if not LOOM_INSTRUMENTATION:
        return

    try:
        # Find .loom directory by searching upward
        current = Path.cwd()
        loom_dir = None

        for directory in [current] + list(current.parents):
            candidate = directory / ".loom"
            if candidate.exists():
                loom_dir = candidate
                break

        if not loom_dir:
            # Create .loom in current directory if it doesn't exist
            loom_dir = current / ".loom"
            loom_dir.mkdir(exist_ok=True)

        log_path = loom_dir / "usage.log"

        # Format: {ISO timestamp}|{tool_name}|{query[:50]}|{result_summary[:100]}
        timestamp = datetime.now().isoformat()
        query_truncated = query[:50].replace('\n', ' ').replace('|', '/')
        result_truncated = result_summary[:100].replace('\n', ' ').replace('|', '/')

        log_line = f"{timestamp}|{tool_name}|{query_truncated}|{result_truncated}\n"

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        # Fail silently - instrumentation should never break functionality
        pass


def _find_store(project_path: Optional[str] = None) -> Optional[CodeStore]:
    """
    Find .loom/store.db with the following precedence:

    1. Explicit project_path argument (if provided, becomes active project)
    2. Active project from config (if set and valid)
    3. Search upward from cwd (original behavior)

    Args:
        project_path: Optional path to project directory. If provided,
                      sets this as the active project for future commands.
    """
    # 1. Explicit project path takes precedence
    if project_path:
        target = Path(project_path).resolve()
        db_path = target / ".loom" / "store.db"
        if db_path.exists():
            set_active_project(target)  # Set as active for future commands
            return CodeStore(str(db_path))
        return None

    # 2. Check active project from config
    active = get_active_project()
    if active:
        db_path = active / ".loom" / "store.db"
        if db_path.exists():
            return CodeStore(str(db_path))

    # 3. Fall back to upward search from cwd
    current = Path.cwd()
    for directory in [current] + list(current.parents):
        db_path = directory / ".loom" / "store.db"
        if db_path.exists():
            return CodeStore(str(db_path))

    return None


def _find_entity_by_name(store: CodeStore, name: str) -> Optional[dict]:
    """
    Find an entity by name, trying various strategies.

    Returns the best match or None.
    """
    # Try exact match first
    entities = store.find_entities(name=name)
    if entities:
        # Prefer exact match on full name
        for e in entities:
            if e["name"] == name:
                return e
        # Otherwise return first result (best fuzzy match)
        return entities[0]

    return None


def _get_file_location(entity: dict) -> str:
    """Get formatted file:line location string."""
    metadata = entity.get("metadata") or {}
    file_path = metadata.get("file_path", "")
    lineno = metadata.get("lineno", "")
    if file_path and lineno:
        return f"{file_path}:{lineno}"
    return file_path or "unknown"


def _get_code_preview(entity: dict, max_lines: int = 10) -> str:
    """Get first few lines of code for preview."""
    code = entity.get("code", "")
    if not code:
        return "(no code available)"
    lines = code.split("\n")[:max_lines]
    if len(entity.get("code", "").split("\n")) > max_lines:
        lines.append("...")
    return "\n".join(lines)


def _kind_label(kind: str) -> str:
    """Get display label for entity kind."""
    labels = {
        "function": "func",
        "method": "method",
        "class": "class",
        "module": "module",
        "variable": "var",
    }
    return labels.get(kind, kind)
