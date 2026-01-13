#!/usr/bin/env python3
"""
knowledge_tools - Knowledge base functions for Claude Code.

This module provides tools for managing accumulated knowledge:
- add_finding: Record analysis findings
- add_intent: Document entity purposes
- add_hypothesis: Record debugging hypotheses
- resolve_hypothesis: Mark hypotheses as confirmed/refuted
- whats_known_about: Get all knowledge about an entity
- search_knowledge: Search all notes
- knowledge_stats: Get knowledge base statistics

All functions auto-discover the .loom/store.db database.
"""

from typing import Optional, List

from codestore import CodeStore

# Import shared utilities
from loom_base import _log_usage, _find_store


def add_finding(content: str, title: str = None, related_to: List[str] = None) -> str:
    """Record an analysis finding, optionally linked to entities."""
    _log_usage('add_finding', title or content[:50], '')
    cs = _find_store()
    if not cs:
        return "Error: No Loom database found. Run './loom ingest <path>' first."
    try:
        note_id = cs.add_note(content, note_type='analysis', title=title,
                              linked_entities=related_to, source='loom_tools')
        return note_id
    finally:
        cs.close()


def add_intent(entity_name: str, intent: str) -> str:
    """Document WHY an entity exists."""
    _log_usage('add_intent', entity_name, '')
    cs = _find_store()
    if not cs:
        return "Error: No Loom database found. Run './loom ingest <path>' first."
    try:
        note_id = cs.add_note(intent, note_type='intent', title=f'Intent: {entity_name}',
                              linked_entities=[entity_name], link_type='explains')
        return note_id
    finally:
        cs.close()


def add_hypothesis(hypothesis: str, related_to: List[str] = None) -> str:
    """Record a debugging hypothesis."""
    _log_usage('add_hypothesis', hypothesis[:50], '')
    cs = _find_store()
    if not cs:
        return "Error: No Loom database found. Run './loom ingest <path>' first."
    try:
        note_id = cs.add_note(hypothesis, note_type='hypothesis',
                              linked_entities=related_to, source='loom_tools')
        return note_id
    finally:
        cs.close()


def resolve_hypothesis(note_id: str, confirmed: bool, conclusion: str = None) -> bool:
    """Mark a hypothesis as confirmed or refuted."""
    _log_usage('resolve_hypothesis', note_id, 'confirmed' if confirmed else 'refuted')
    cs = _find_store()
    if not cs:
        return False
    try:
        status = 'confirmed' if confirmed else 'refuted'
        if conclusion:
            # Append conclusion to note content by updating it
            # For now, we just update the status since CodeStore doesn't have update_note_content
            pass
        return cs.update_note_status(note_id, status)
    finally:
        cs.close()


def whats_known_about(entity_name: str) -> str:
    """Get all notes/knowledge about an entity."""
    _log_usage('whats_known_about', entity_name, '')
    cs = _find_store()
    if not cs:
        return "Error: No Loom database found. Run './loom ingest <path>' first."
    try:
        notes = cs.get_entity_notes(entity_name)
        # Format nicely for LLM consumption
        if not notes:
            return f"No notes found about '{entity_name}'"
        lines = [f"## Knowledge about {entity_name}", ""]
        for note in notes:
            lines.append(f"### [{note['type']}] {note.get('title', 'Untitled')}")
            lines.append(f"Status: {note.get('status', 'active')}")
            lines.append(note['content'])
            lines.append("")
        return "\n".join(lines)
    finally:
        cs.close()


def search_knowledge(query: str) -> str:
    """Search all notes and findings."""
    _log_usage('search_knowledge', query, '')
    cs = _find_store()
    if not cs:
        return "Error: No Loom database found. Run './loom ingest <path>' first."
    try:
        # Try semantic search first
        try:
            results = cs.search_notes(query)
        except RuntimeError:
            # Fallback to simple text search if semantic search unavailable
            query_lower = query.lower()
            rows = cs.conn.execute(
                "SELECT * FROM notes WHERE LOWER(content) LIKE ? OR LOWER(title) LIKE ? ORDER BY created_at DESC LIMIT 20",
                (f'%{query_lower}%', f'%{query_lower}%')
            ).fetchall()
            results = [dict(row) for row in rows]

        if not results:
            return f"No notes found matching '{query}'"
        lines = [f"## Notes matching '{query}'", ""]
        for r in results:
            lines.append(f"### [{r['type']}] {r.get('title', 'Untitled')}")
            lines.append(r['content'][:200] + '...' if len(r['content']) > 200 else r['content'])
            lines.append("")
        return "\n".join(lines)
    finally:
        cs.close()


def knowledge_stats() -> str:
    """Get statistics about accumulated knowledge."""
    _log_usage('knowledge_stats', '', '')
    cs = _find_store()
    if not cs:
        return "Error: No Loom database found. Run './loom ingest <path>' first."
    try:
        stats = cs.get_note_stats()
        lines = ["## Knowledge Base Stats", ""]
        lines.append(f"Total notes: {stats['total']}")
        lines.append(f"Linked to entities: {stats['linked']}")
        lines.append("")
        lines.append("By type:")
        for t, c in stats['by_type'].items():
            lines.append(f"  {t}: {c}")
        lines.append("")
        lines.append("By status:")
        for s, c in stats['by_status'].items():
            lines.append(f"  {s}: {c}")
        return "\n".join(lines)
    finally:
        cs.close()
