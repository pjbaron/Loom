#!/usr/bin/env python3
"""
graph_tools - Architecture and graph analysis functions for Claude Code.

This module provides tools for understanding codebase architecture:
- architecture: High-level codebase overview
- central_entities: Find most connected code
- orphan_entities: Find potentially dead code
- find_path: Find how two entities relate

All functions auto-discover the .loom/store.db database.
"""

from typing import Optional

from codestore import CodeStore

# Import shared utilities
from loom_base import _log_usage, _find_store, _find_entity_by_name


def architecture() -> str:
    """
    Get architecture overview.

    Provides a high-level view of the codebase structure including:
    - Entity counts by type
    - Relationship counts
    - Most connected entities
    - Module overview
    - Orphan entities (potential dead code)
    - Import graph summary

    Returns:
        Formatted architecture summary suitable for LLM consumption
    """
    _log_usage('architecture', '', '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."
    try:
        return store.get_architecture_summary()
    finally:
        store.close()


def central_entities(limit: int = 10) -> str:
    """
    Find most connected code.

    Identifies entities with the highest number of relationships
    (both incoming and outgoing), which typically represent core
    components of the codebase.

    Args:
        limit: Maximum number of entities to return (default 10)

    Returns:
        Formatted list of central entities with connection counts
    """
    _log_usage('central_entities', str(limit), '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."
    try:
        central = store.get_central_entities(limit)
        if not central:
            return "No connected entities found."

        lines = [f"Top {len(central)} Most Connected Entities:", ""]
        for i, entity in enumerate(central, 1):
            lines.append(
                f"{i}. {entity['name']} ({entity['kind']}): "
                f"{entity['connections']} connections"
            )
        return "\n".join(lines)
    finally:
        store.close()


def orphan_entities() -> str:
    """
    Find potentially dead code.

    Identifies entities that have no relationships with other entities,
    which may indicate unused or dead code that could be removed.

    Returns:
        Formatted list of orphan entities grouped by kind
    """
    _log_usage('orphan_entities', '', '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."
    try:
        orphans = store.get_orphans()
        if not orphans:
            return "No orphan entities found. All code is connected."

        # Group by kind
        by_kind: dict = {}
        for orphan in orphans:
            kind = orphan.get('kind', 'unknown')
            if kind not in by_kind:
                by_kind[kind] = []
            by_kind[kind].append(orphan)

        lines = [f"Found {len(orphans)} Orphan Entities (No Relationships):", ""]
        lines.append("These entities may be dead code or entry points.")
        lines.append("")

        for kind in sorted(by_kind.keys()):
            entities = by_kind[kind]
            lines.append(f"{kind.capitalize()}s ({len(entities)}):")
            for entity in entities[:20]:  # Limit per kind
                metadata = entity.get('metadata') or {}
                file_path = metadata.get('file_path', '')
                lineno = metadata.get('lineno', '')
                location = f" ({file_path}:{lineno})" if file_path else ""
                lines.append(f"  - {entity['name']}{location}")
            if len(entities) > 20:
                lines.append(f"  ... and {len(entities) - 20} more")
            lines.append("")

        return "\n".join(lines)
    finally:
        store.close()


def find_path(from_name: str, to_name: str) -> str:
    """
    Find how two entities relate.

    Searches for relationship paths between two entities using BFS,
    showing how code components are connected through the codebase.

    Args:
        from_name: Name of the starting entity (can be partial match)
        to_name: Name of the target entity (can be partial match)

    Returns:
        Formatted list of paths showing how entities connect
    """
    _log_usage('find_path', f'{from_name} -> {to_name}', '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."
    try:
        paths = store.get_path(from_name, to_name, max_depth=5)
        if not paths:
            return f"No path found between '{from_name}' and '{to_name}'."

        lines = [f"Paths from '{from_name}' to '{to_name}':", ""]

        for i, path in enumerate(paths[:5], 1):  # Show up to 5 paths
            # Format path with arrows
            path_str = " -> ".join(path)
            lines.append(f"{i}. {path_str}")
            lines.append(f"   Length: {len(path) - 1} hop(s)")
            lines.append("")

        if len(paths) > 5:
            lines.append(f"... and {len(paths) - 5} more path(s)")

        return "\n".join(lines)
    finally:
        store.close()
