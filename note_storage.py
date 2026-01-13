"""
note_storage - Mixin class for knowledge base / notes operations.

This module is extracted from codestore.py to reduce file size.
It provides all note management functionality for tracking analysis,
hypotheses, intents, and other knowledge about the codebase.
"""

import json
import uuid
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Union


class NoteMixin:
    """
    Mixin class providing note storage operations.

    This mixin expects the following attributes on the class:
    - self.conn: sqlite3 connection with Row factory
    - self.query: method for searching entities by name
    - self.get_note: method to retrieve notes (used for self-referential calls)
    - self.get_calls_for_run: method to get trace calls
    - self.get_trace_run: method to get trace run info

    Usage:
        class CodeStore(NoteMixin, ...):
            ...
    """

    def _resolve_entity_id(self, entity_ref: str) -> Optional[int]:
        """
        Resolve an entity reference (name or ID) to an entity ID.

        Args:
            entity_ref: Entity name or ID string

        Returns:
            Entity ID as int, or None if not found
        """
        # Try as integer ID first
        try:
            entity_id = int(entity_ref)
            # Verify it exists
            row = self.conn.execute(
                "SELECT id FROM entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if row:
                return entity_id
        except (ValueError, TypeError):
            pass

        # Try as name using query method
        results = self.query(entity_ref)
        if not results:
            return None

        # Find exact match or use first result
        for r in results:
            if r['entity']['name'] == entity_ref:
                return r['entity']['id']

        return results[0]['entity']['id']

    def add_note(
        self,
        content: str,
        note_type: str = 'analysis',
        title: str = None,
        source: str = None,
        linked_entities: List[str] = None,
        link_type: str = 'about'
    ) -> str:
        """
        Add a note, optionally linked to entities.

        Args:
            content: The main note content
            note_type: Type of note ('analysis', 'intent', 'hypothesis', 'todo', 'decision', 'bug')
            title: Optional title for the note
            source: Origin of the note (file path, session id, or 'manual')
            linked_entities: List of entity names or IDs to link to
            link_type: Type of link ('about', 'affects', 'explains', 'tests')

        Returns:
            The generated note ID (UUID string)
        """
        note_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()

        self.conn.execute(
            "INSERT INTO notes (id, type, title, content, created_at, source, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (note_id, note_type, title, content, created_at, source, 'active')
        )

        # Link to entities if provided
        if linked_entities:
            for entity_ref in linked_entities:
                entity_id = None

                # Check if it's already an integer ID
                if isinstance(entity_ref, int):
                    entity_id = entity_ref
                elif isinstance(entity_ref, str) and entity_ref.isdigit():
                    entity_id = int(entity_ref)
                else:
                    # Query by name - could be simple 'CodeStore' or qualified 'codestore.CodeStore'
                    results = self.query(entity_ref)
                    if results:
                        # Find exact match first
                        for r in results:
                            if r['entity']['name'] == entity_ref:
                                entity_id = r['entity']['id']
                                break
                        # Fall back to first result if no exact match
                        if entity_id is None:
                            entity_id = results[0]['entity']['id']

                if entity_id is not None:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO note_links (note_id, entity_id, link_type) VALUES (?, ?, ?)",
                        (note_id, str(entity_id), link_type)
                    )

        self.conn.commit()
        return note_id

    def get_notes(
        self,
        entity_name: str = None,
        note_type: str = None,
        status: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Retrieve notes, optionally filtered.

        Args:
            entity_name: Filter to notes linked to this entity
            note_type: Filter by note type
            status: Filter by status
            limit: Maximum number of notes to return

        Returns:
            List of note dicts with keys: id, type, title, content, created_at, source, status
        """
        if entity_name:
            # First resolve the entity name to ID
            results = self.query(entity_name)
            if not results:
                return []

            # Find exact match or use first result
            entity_id = None
            for r in results:
                if r['entity']['name'] == entity_name:
                    entity_id = r['entity']['id']
                    break
            if entity_id is None:
                entity_id = results[0]['entity']['id']

            # Query notes linked to this entity
            query = """
                SELECT DISTINCT n.* FROM notes n
                JOIN note_links nl ON n.id = nl.note_id
                WHERE nl.entity_id = ?
            """
            params = [str(entity_id)]

            if note_type:
                query += " AND n.type = ?"
                params.append(note_type)
            if status:
                query += " AND n.status = ?"
                params.append(status)

            query += " ORDER BY n.created_at DESC LIMIT ?"
            params.append(limit)

            rows = self.conn.execute(query, params).fetchall()
        else:
            # Query all notes with optional filters
            query = "SELECT * FROM notes WHERE 1=1"
            params = []

            if note_type:
                query += " AND type = ?"
                params.append(note_type)
            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = self.conn.execute(query, params).fetchall()

        return [dict(row) for row in rows]

    def update_note_status(self, note_id: str, status: str) -> bool:
        """
        Update note status (for hypothesis tracking).

        Args:
            note_id: The ID of the note to update
            status: New status ('active', 'confirmed', 'refuted')

        Returns:
            True if the note was updated, False if not found
        """
        cursor = self.conn.execute(
            "UPDATE notes SET status = ? WHERE id = ?",
            (status, note_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_entity_notes(self, entity_name: str) -> List[Dict]:
        """
        Get all notes linked to a specific entity.

        Args:
            entity_name: The name of the entity (simple or fully qualified)

        Returns:
            List of note dicts linked to the entity
        """
        # Resolve entity name to ID
        results = self.query(entity_name)
        if not results:
            return []

        # Find exact match or use first result
        entity_id = None
        for r in results:
            if r['entity']['name'] == entity_name:
                entity_id = r['entity']['id']
                break
        if entity_id is None:
            entity_id = results[0]['entity']['id']

        # Query notes linked to this entity with link type info
        rows = self.conn.execute(
            """
            SELECT n.*, nl.link_type FROM notes n
            JOIN note_links nl ON n.id = nl.note_id
            WHERE nl.entity_id = ?
            ORDER BY n.created_at DESC
            """,
            (str(entity_id),)
        ).fetchall()

        return [dict(row) for row in rows]

    def get_note(self, note_id: str) -> Optional[Dict]:
        """
        Get a single note by ID.

        Args:
            note_id: The ID of the note to retrieve

        Returns:
            Note dict if found, None otherwise
        """
        row = self.conn.execute(
            "SELECT * FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_note(
        self,
        note_id: str,
        content: str = None,
        title: str = None,
        add_entities: List[str] = None,
        remove_entities: List[str] = None
    ) -> bool:
        """
        Update an existing note's content, title, or entity links.

        Args:
            note_id: The ID of the note to update
            content: New content (if provided)
            title: New title (if provided)
            add_entities: Entity names/IDs to link to this note
            remove_entities: Entity names/IDs to unlink from this note

        Returns:
            True if the note was updated, False if not found
        """
        # Check if note exists
        existing = self.get_note(note_id)
        if not existing:
            return False

        # Update content and/or title if provided
        updates = []
        params = []
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if title is not None:
            updates.append("title = ?")
            params.append(title)

        if updates:
            params.append(note_id)
            self.conn.execute(
                f"UPDATE notes SET {', '.join(updates)} WHERE id = ?",
                params
            )

        # Remove entity links if specified
        if remove_entities:
            for entity_ref in remove_entities:
                entity_id = self._resolve_entity_id(entity_ref)
                if entity_id is not None:
                    self.conn.execute(
                        "DELETE FROM note_links WHERE note_id = ? AND entity_id = ?",
                        (note_id, str(entity_id))
                    )

        # Add entity links if specified
        if add_entities:
            for entity_ref in add_entities:
                entity_id = self._resolve_entity_id(entity_ref)
                if entity_id is not None:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO note_links (note_id, entity_id, link_type) VALUES (?, ?, ?)",
                        (note_id, str(entity_id), 'about')
                    )

        self.conn.commit()
        return True

    def consolidate_notes(
        self,
        note_ids: List[str],
        new_title: str,
        summarize: bool = False
    ) -> str:
        """
        Merge multiple notes into one. Original notes are deleted.

        If summarize=True, content is concatenated with headers showing
        the original note titles/types.

        Args:
            note_ids: List of note IDs to merge
            new_title: Title for the consolidated note
            summarize: If True, add headers for each note's content

        Returns:
            The ID of the new consolidated note
        """
        # Collect all notes and their entity links
        notes = []
        all_entity_ids = set()

        for note_id in note_ids:
            note = self.get_note(note_id)
            if note:
                notes.append(note)
                # Get entity links
                links = self.conn.execute(
                    "SELECT entity_id FROM note_links WHERE note_id = ?",
                    (note_id,)
                ).fetchall()
                for link in links:
                    all_entity_ids.add(link[0])

        if not notes:
            raise ValueError("No valid notes found to consolidate")

        # Build consolidated content
        if summarize:
            content_parts = []
            for note in notes:
                header = f"## {note.get('title') or note['type'].upper()}"
                content_parts.append(header)
                content_parts.append(note['content'])
                content_parts.append("")  # Blank line between sections
            consolidated_content = "\n".join(content_parts).strip()
        else:
            # Simple concatenation with separators
            consolidated_content = "\n\n---\n\n".join(
                note['content'] for note in notes
            )

        # Determine the type for the consolidated note
        # Use 'analysis' as default, or the most common type
        types = Counter(note['type'] for note in notes)
        consolidated_type = types.most_common(1)[0][0] if types else 'analysis'

        # Create the new consolidated note
        new_note_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()

        self.conn.execute(
            "INSERT INTO notes (id, type, title, content, created_at, source, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_note_id, consolidated_type, new_title, consolidated_content, created_at, 'consolidation', 'active')
        )

        # Re-create all entity links for the new note
        for entity_id in all_entity_ids:
            self.conn.execute(
                "INSERT OR IGNORE INTO note_links (note_id, entity_id, link_type) VALUES (?, ?, ?)",
                (new_note_id, entity_id, 'about')
            )

        # Delete the original notes and their links
        for note_id in note_ids:
            self.conn.execute("DELETE FROM note_links WHERE note_id = ?", (note_id,))
            self.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))

        self.conn.commit()
        return new_note_id

    def delete_note(self, note_id: str) -> bool:
        """
        Delete a note and its entity links.

        Args:
            note_id: The ID of the note to delete

        Returns:
            True if the note was deleted, False if not found
        """
        # Check if note exists
        existing = self.get_note(note_id)
        if not existing:
            return False

        # Delete entity links first
        self.conn.execute("DELETE FROM note_links WHERE note_id = ?", (note_id,))

        # Delete the note
        self.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))

        self.conn.commit()
        return True

    def get_note_stats(self) -> Dict:
        """
        Get counts of notes by type and status.

        Returns:
            Dict with:
            - by_type: Dict mapping note types to counts
            - by_status: Dict mapping statuses to counts
            - total: Total number of notes
            - linked: Number of notes with at least one entity link
        """
        # Count by type
        type_rows = self.conn.execute(
            "SELECT type, COUNT(*) as count FROM notes GROUP BY type"
        ).fetchall()
        by_type = {row['type']: row['count'] for row in type_rows}

        # Count by status
        status_rows = self.conn.execute(
            "SELECT status, COUNT(*) as count FROM notes GROUP BY status"
        ).fetchall()
        by_status = {row['status']: row['count'] for row in status_rows}

        # Total count
        total = self.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]

        # Count notes with links
        linked = self.conn.execute(
            "SELECT COUNT(DISTINCT note_id) FROM note_links"
        ).fetchone()[0]

        return {
            'by_type': by_type,
            'by_status': by_status,
            'total': total,
            'linked': linked
        }

    def search_notes(self, query: str, note_type: str = None, limit: int = 10) -> List[Dict]:
        """
        Semantic search over notes.

        Uses the embedding model to find notes semantically similar to the query.

        Args:
            query: Natural language query (e.g., "duplicate results bug")
            note_type: Optional filter by note type ('analysis', 'bug', 'todo', etc.)
            limit: Maximum number of results to return (default 10)

        Returns:
            List of note dicts with additional 'score' and 'distance' fields,
            sorted by relevance (highest score first).

        Raises:
            RuntimeError: If sqlite-vec is not available or no embeddings exist
        """
        if not self._vec_available:
            raise RuntimeError(
                "sqlite-vec is not available; cannot perform semantic search"
            )

        # Check if note embeddings exist
        try:
            count = self.conn.execute("SELECT COUNT(*) FROM vec_notes").fetchone()[0]
        except Exception:
            count = 0

        if count == 0:
            raise RuntimeError(
                "No note embeddings found. Run generate_embeddings() first."
            )

        # Lazy-load the embedding model
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed; cannot perform semantic search"
                )

        # Generate embedding for query
        query_embedding = self._embedding_model.encode(query)

        # Query sqlite-vec for similar embeddings
        rows = self.conn.execute(
            """
            SELECT rowid, distance
            FROM vec_notes
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (query_embedding.tobytes(), limit * 2)
        ).fetchall()

        # Build note_rowid_map if not already populated
        if not hasattr(self, '_note_rowid_map') or not self._note_rowid_map:
            self._note_rowid_map = {}
            note_rows = self.conn.execute("SELECT id FROM notes").fetchall()
            for idx, note_row in enumerate(note_rows, start=1):
                self._note_rowid_map[idx] = note_row["id"]

        results = []
        for row in rows:
            rowid = row[0]
            distance = row[1]

            note_id = self._note_rowid_map.get(rowid)
            if not note_id:
                continue

            # Get the full note
            note_row = self.conn.execute(
                "SELECT * FROM notes WHERE id = ?", (note_id,)
            ).fetchone()

            if note_row:
                note = dict(note_row)

                # Apply note_type filter if specified
                if note_type and note.get('type') != note_type:
                    continue

                # Convert distance to similarity score
                score = 1.0 / (1.0 + distance)
                note['score'] = score
                note['distance'] = distance
                results.append(note)

                if len(results) >= limit:
                    break

        return results

    def check_hypothesis(self, note_id: str, run_id: str) -> Dict:
        """
        Check a hypothesis against trace data from a specific run.

        Extracts entity names mentioned in the hypothesis, finds their calls
        in the trace data, and provides evidence for human/LLM judgment.

        Args:
            note_id: The ID of the hypothesis note
            run_id: The ID of the trace run to check against

        Returns:
            Dict containing:
                - hypothesis: The hypothesis content
                - entities_mentioned: List of entity names found in hypothesis
                - evidence: List of evidence items for each entity
                - summary: Human-readable summary of findings
        """
        import re

        # Get the hypothesis note
        note = self.get_note(note_id)
        if not note:
            return {'error': f'Hypothesis not found: {note_id}'}

        if note.get('type') != 'hypothesis':
            return {'error': f'Note is not a hypothesis (type: {note.get("type")})'}

        # Get the trace run
        run = self.get_trace_run(run_id)
        if not run:
            return {'error': f'Trace run not found: {run_id}'}

        hypothesis_text = note.get('content', '')

        # Get linked entities from note_links
        linked_rows = self.conn.execute(
            "SELECT entity_id FROM note_links WHERE note_id = ?",
            (note_id,)
        ).fetchall()

        linked_entity_ids = [row[0] for row in linked_rows]
        entities_mentioned = []

        # Get entity names from linked entities
        for entity_id in linked_entity_ids:
            entity = self.get_entity(int(entity_id)) if entity_id.isdigit() else None
            if entity:
                entities_mentioned.append({
                    'id': entity['id'],
                    'name': entity['name'],
                    'kind': entity.get('kind'),
                    'source': 'linked'
                })

        # Also extract entity names from hypothesis text using simple heuristics
        # Look for patterns like "function_name", "ClassName", "module.function"
        # Match identifiers that look like function/class names
        potential_names = re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b', hypothesis_text)

        # Filter to names that exist in our codebase
        for name in set(potential_names):
            # Skip common words
            if name.lower() in ('the', 'is', 'are', 'be', 'been', 'being', 'have', 'has', 'had',
                                'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
                                'might', 'must', 'shall', 'can', 'need', 'not', 'and', 'or', 'but',
                                'if', 'then', 'else', 'when', 'where', 'why', 'how', 'what', 'which',
                                'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we',
                                'they', 'because', 'returns', 'return', 'empty', 'none', 'null', 'true',
                                'false', 'error', 'exception', 'bug', 'issue', 'problem', 'think',
                                'hypothesis', 'test', 'testing', 'check', 'verify'):
                continue

            # Check if this name exists as an entity
            results = self.query(name)
            if results:
                for r in results:
                    if r['entity']['name'] == name or r['entity']['name'].endswith('.' + name):
                        entity = r['entity']
                        # Avoid duplicates
                        if not any(e['id'] == entity['id'] for e in entities_mentioned):
                            entities_mentioned.append({
                                'id': entity['id'],
                                'name': entity['name'],
                                'kind': entity.get('kind'),
                                'source': 'extracted'
                            })
                        break

        # Now find calls to these entities in the trace
        evidence = []
        calls = self.get_calls_for_run(run_id, include_args=True)

        for entity in entities_mentioned:
            entity_name = entity['name']
            entity_calls = []

            for call in calls:
                func_name = call.get('function_name', '')
                # Match if the function name contains the entity name
                # e.g., "module.ClassName.method" matches "ClassName" or "method"
                name_parts = func_name.split('.')
                if entity_name in name_parts or func_name.endswith(entity_name):
                    entity_calls.append(call)

            # Build evidence for this entity
            if entity_calls:
                # Summarize the calls
                call_summaries = []
                exceptions = []
                for c in entity_calls[:10]:  # Limit to first 10 for readability
                    summary = {
                        'function': c.get('function_name'),
                        'duration_ms': c.get('duration_ms'),
                        'depth': c.get('depth', 0),
                    }
                    if c.get('args_json'):
                        try:
                            args = json.loads(c['args_json'])
                            # Truncate long args
                            args_repr = repr(args)[:200]
                            summary['args'] = args_repr
                        except:
                            pass
                    if c.get('return_value_json'):
                        try:
                            ret = json.loads(c['return_value_json'])
                            ret_repr = repr(ret)[:200]
                            summary['returned'] = ret_repr
                        except:
                            pass
                    if c.get('exception_type'):
                        summary['exception'] = f"{c['exception_type']}: {c.get('exception_message', '')[:100]}"
                        exceptions.append(summary)
                    call_summaries.append(summary)

                evidence.append({
                    'entity': entity_name,
                    'entity_kind': entity.get('kind'),
                    'call_count': len(entity_calls),
                    'exception_count': len(exceptions),
                    'calls': call_summaries,
                    'exceptions': exceptions,
                })
            else:
                evidence.append({
                    'entity': entity_name,
                    'entity_kind': entity.get('kind'),
                    'call_count': 0,
                    'exception_count': 0,
                    'calls': [],
                    'exceptions': [],
                    'note': 'No calls found in this trace run'
                })

        # Build summary
        summary_lines = [
            f"Hypothesis: {hypothesis_text[:200]}{'...' if len(hypothesis_text) > 200 else ''}",
            f"Trace Run: {run_id} ({run.get('command', 'N/A')})",
            f"Status: {run.get('status', 'N/A')}",
            "",
            "Evidence:"
        ]

        for e in evidence:
            if e['call_count'] > 0:
                summary_lines.append(
                    f"  - {e['entity']} ({e['entity_kind']}): "
                    f"called {e['call_count']} times, {e['exception_count']} exceptions"
                )
                if e['exceptions']:
                    for exc in e['exceptions'][:3]:
                        summary_lines.append(f"      Exception: {exc.get('exception', 'N/A')}")
            else:
                summary_lines.append(f"  - {e['entity']} ({e['entity_kind']}): NOT CALLED in this run")

        summary_lines.append("")
        summary_lines.append("Note: This is evidence for human/LLM judgment, not automatic resolution.")

        return {
            'hypothesis': hypothesis_text,
            'hypothesis_id': note_id,
            'trace_run_id': run_id,
            'trace_command': run.get('command'),
            'trace_status': run.get('status'),
            'entities_mentioned': entities_mentioned,
            'evidence': evidence,
            'summary': '\n'.join(summary_lines)
        }
