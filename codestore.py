"""
codestore - A graph-based code representation backed by SQLite.

Represents code as semantic entities (modules, classes, functions, methods) with
explicit relationships (contains, calls, imports, member_of) and intent annotations.

The CodeStore class is built from mixins to keep file sizes manageable:
- SchemaMixin: Database schema creation and migrations (schema.py)
- ChangeTrackingMixin: File change detection and test impact analysis (change_tracking.py)
- TraceMixin: Runtime tracing and call recording (trace_storage.py)
- NoteMixin: Knowledge base / notes operations (note_storage.py)
- IngestionMixin: Code parsing and ingestion (ingestion.py)
- FailureLogMixin: Failure tracking for attempted fixes (failure_log_storage.py)
- TodoMixin: Work item (TODO) tracking (todo_storage.py)
"""

import ast
import json
import logging
import re
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from parsers import ParserRegistry, PythonParser, JavaScriptParser, TypeScriptParser, CppParser, ActionScript3Parser, HTMLParser
from trace_storage import TraceMixin
from change_tracking import ChangeTrackingMixin
from schema import SchemaMixin
from note_storage import NoteMixin
from ingestion import IngestionMixin
from failure_log_storage import FailureLogMixin
from todo_storage import TodoMixin


class CodeStore(SchemaMixin, ChangeTrackingMixin, TraceMixin, NoteMixin, IngestionMixin, FailureLogMixin, TodoMixin):
    """Graph-based code storage with SQLite backend."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._embedding_model = None  # Lazy-loaded sentence-transformers model
        self._vec_available = False
        self._init_schema()
        self._init_vec_table()

        # Initialize parser registry with default parsers
        self.parser_registry = ParserRegistry()
        self.parser_registry.register(PythonParser())
        self.parser_registry.register(JavaScriptParser())
        self.parser_registry.register(TypeScriptParser())
        self.parser_registry.register(CppParser())
        try:
            self.parser_registry.register(ActionScript3Parser())
            self.parser_registry.register(HTMLParser())
        except ImportError:
            pass  # tree-sitter-language-pack not installed

    # --- Entity Management ---

    def add_entity(self, name: str, kind: str, code: str = None,
                   intent: str = None, metadata: Dict = None) -> int:
        """Add a semantic entity to the graph. Returns entity ID."""
        cur = self.conn.execute(
            "INSERT INTO entities (name, kind, code, intent, metadata) VALUES (?, ?, ?, ?, ?)",
            (name, kind, code, intent, json.dumps(metadata) if metadata else None)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_entity(self, entity_id: int) -> Optional[Dict]:
        """Get entity by ID."""
        row = self.conn.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def find_entities(self, name: str = None, kind: str = None) -> List[Dict]:
        """Find entities by name and/or kind."""
        query = "SELECT * FROM entities WHERE 1=1"
        params = []
        if name:
            query += " AND name LIKE ?"
            params.append(f"%{name}%")
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_entity(self, entity_id: int, **kwargs) -> bool:
        """Update entity fields."""
        allowed = {'name', 'kind', 'code', 'intent', 'metadata'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        if 'metadata' in updates:
            updates['metadata'] = json.dumps(updates['metadata'])
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE entities SET {set_clause} WHERE id = ?",
            (*updates.values(), entity_id)
        )
        self.conn.commit()
        return True

    def delete_entity(self, entity_id: int):
        """Delete entity and its relationships."""
        self.conn.execute("DELETE FROM relationships WHERE source_id = ? OR target_id = ?",
                          (entity_id, entity_id))
        self.conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        self.conn.commit()

    # --- Relationship Management ---

    def add_relationship(self, source_id: int, target_id: int,
                         relation: str, metadata: Dict = None) -> int:
        """Add a relationship between entities. Returns relationship ID."""
        cur = self.conn.execute(
            "INSERT INTO relationships (source_id, target_id, relation, metadata) VALUES (?, ?, ?, ?)",
            (source_id, target_id, relation, json.dumps(metadata) if metadata else None)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_relationships(self, entity_id: int, direction: str = "both") -> List[Dict]:
        """Get relationships for an entity. direction: 'outgoing', 'incoming', or 'both'."""
        results = []
        if direction in ("outgoing", "both"):
            rows = self.conn.execute(
                "SELECT r.*, e.name as target_name, e.kind as target_kind "
                "FROM relationships r JOIN entities e ON r.target_id = e.id "
                "WHERE r.source_id = ?", (entity_id,)
            ).fetchall()
            results.extend([self._row_to_dict(r) for r in rows])
        if direction in ("incoming", "both"):
            rows = self.conn.execute(
                "SELECT r.*, e.name as source_name, e.kind as source_kind "
                "FROM relationships r JOIN entities e ON r.source_id = e.id "
                "WHERE r.target_id = ?", (entity_id,)
            ).fetchall()
            results.extend([self._row_to_dict(r) for r in rows])
        return results

    def find_related(self, entity_id: int, relation: str = None,
                     direction: str = "outgoing") -> List[Dict]:
        """Find entities related to the given entity."""
        if direction == "outgoing":
            query = """
                SELECT e.* FROM entities e
                JOIN relationships r ON e.id = r.target_id
                WHERE r.source_id = ?
            """
        else:
            query = """
                SELECT e.* FROM entities e
                JOIN relationships r ON e.id = r.source_id
                WHERE r.target_id = ?
            """
        params = [entity_id]
        if relation:
            query += " AND r.relation = ?"
            params.append(relation)
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # --- Graph Queries ---

    def get_children(self, entity_id: int) -> List[Dict]:
        """Get entities contained by this entity."""
        return self.find_related(entity_id, relation="contains", direction="outgoing")

    def get_parent(self, entity_id: int) -> Optional[Dict]:
        """Get the containing entity."""
        parents = self.find_related(entity_id, relation="contains", direction="incoming")
        return parents[0] if parents else None

    def get_call_graph(self, entity_id: int, depth: int = 1,
                        recursive: bool = False, _visited: set = None) -> Dict:
        """
        Get the call graph starting from an entity.

        Args:
            entity_id: The ID of the entity to start from
            depth: How many levels deep to traverse (default 1 for direct calls only)
                   Set to -1 for unlimited depth (use with recursive=True for full tree)
            recursive: If True, continues until all reachable calls are found
                       (respects depth limit if set, uses cycle detection)
            _visited: Internal parameter for cycle detection

        Returns:
            Dict with 'entity' (the starting entity), 'calls' (list of call graph dicts),
            and 'call_count' (number of direct calls)
        """
        entity = self.get_entity(entity_id)
        if not entity:
            return {}

        # Cycle detection for recursive traversal
        if _visited is None:
            _visited = set()
        if entity_id in _visited:
            # Return entity info but don't recurse (cycle detected)
            return {"entity": entity, "calls": [], "call_count": 0, "cycle": True}
        _visited.add(entity_id)

        result = {"entity": entity, "calls": [], "call_count": 0}

        # Determine if we should recurse
        should_recurse = (depth > 0) or (recursive and depth == -1)

        if should_recurse:
            called = self.find_related(entity_id, relation="calls", direction="outgoing")
            result["call_count"] = len(called)

            next_depth = depth - 1 if depth > 0 else -1

            for c in called:
                child_graph = self.get_call_graph(
                    c["id"],
                    depth=next_depth,
                    recursive=recursive,
                    _visited=_visited.copy()  # Copy to allow multiple paths to same node
                )
                result["calls"].append(child_graph)

        return result

    def get_callers(self, entity_id: int) -> List[Dict]:
        """
        Get all entities that call the given entity.

        Args:
            entity_id: The ID of the entity to find callers for

        Returns:
            List of entity dicts that call this entity
        """
        return self.find_related(entity_id, relation="calls", direction="incoming")

    def impact_analysis(self, entity_id: int) -> Dict[str, Any]:
        """
        Analyze the impact of changes to a given entity.

        Finds all entities that would be affected by changes to this entity,
        including direct callers and one level of indirect callers.

        For class entities, this also includes all methods of the class (via
        the member_of relationship) in the impact analysis.

        Args:
            entity_id: The ID of the entity to analyze impact for

        Returns:
            Dict with:
            - direct_callers: list of entities that call this one
            - indirect_callers: entities that call the direct callers (1 level)
            - affected_methods: for classes, list of methods that are members of the class
            - risk_score: total count of affected entities
        """
        entity = self.get_entity(entity_id)
        if not entity:
            return {
                "direct_callers": [],
                "indirect_callers": [],
                "affected_methods": [],
                "risk_score": 0,
            }

        # For classes, get all methods via member_of relationship using SQL join
        affected_methods = []
        if entity.get("kind") == "class":
            affected_methods = self._get_class_methods(entity_id)

        # Collect all entity IDs to analyze (the entity itself + its methods for classes)
        entities_to_analyze = [entity_id]
        entities_to_analyze.extend([m["id"] for m in affected_methods])

        # Get direct callers of the entity and all its methods
        direct_callers = []
        direct_caller_ids = set()

        for eid in entities_to_analyze:
            callers = self.get_callers(eid)
            for caller in callers:
                if caller["id"] not in direct_caller_ids and caller["id"] not in entities_to_analyze:
                    direct_callers.append(caller)
                    direct_caller_ids.add(caller["id"])

        # Get indirect callers (one level up from direct callers)
        indirect_callers = []
        seen_indirect = set()

        for caller in direct_callers:
            second_level = self.get_callers(caller["id"])
            for indirect in second_level:
                # Exclude direct callers, original entities, and already seen
                if indirect["id"] not in direct_caller_ids and \
                   indirect["id"] not in entities_to_analyze and \
                   indirect["id"] not in seen_indirect:
                    indirect_callers.append(indirect)
                    seen_indirect.add(indirect["id"])

        risk_score = len(direct_callers) + len(indirect_callers) + len(affected_methods)

        return {
            "direct_callers": direct_callers,
            "indirect_callers": indirect_callers,
            "affected_methods": affected_methods,
            "risk_score": risk_score,
        }

    def _get_class_methods(self, class_id: int) -> List[Dict]:
        """
        Get all methods that belong to a class via the member_of relationship.

        Uses a SQL JOIN to efficiently query methods without string manipulation.

        Args:
            class_id: The ID of the class entity

        Returns:
            List of method entity dicts
        """
        rows = self.conn.execute(
            """
            SELECT e.* FROM entities e
            JOIN relationships r ON e.id = r.source_id
            WHERE r.target_id = ? AND r.relation = 'member_of' AND e.kind = 'method'
            """,
            (class_id,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # --- Projection to Python Package ---

    def project_to_package(self, output_dir: str, root_module: str = None):
        """Project the graph into a runnable Python package."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Find root modules (modules with no parent)
        if root_module:
            modules = self.find_entities(name=root_module, kind="module")
        else:
            modules = self.find_entities(kind="module")
            # Filter to only root modules (no incoming 'contains' relationship)
            modules = [m for m in modules if not self.get_parent(m["id"])]

        for module in modules:
            self._project_module(module, output_path)

        # Create __init__.py at root
        init_path = output_path / "__init__.py"
        if not init_path.exists():
            init_path.write_text("")

    def _project_module(self, module: Dict, base_path: Path):
        """Project a single module entity to a file."""
        module_name = module["name"]

        # Check if this module has submodules
        children = self.get_children(module["id"])
        submodules = [c for c in children if c["kind"] == "module"]

        if submodules:
            # It's a package - create directory
            pkg_path = base_path / module_name
            pkg_path.mkdir(exist_ok=True)

            # Build __init__.py content
            init_content = self._build_module_content(module, children)
            (pkg_path / "__init__.py").write_text(init_content)

            # Recurse into submodules
            for sub in submodules:
                self._project_module(sub, pkg_path)
        else:
            # It's a simple module - create .py file
            content = self._build_module_content(module, children)
            (base_path / f"{module_name}.py").write_text(content)

    def _build_module_content(self, module: Dict, children: List[Dict]) -> str:
        """Build Python source for a module."""
        lines = []

        # Add module docstring from intent
        if module.get("intent"):
            lines.append(f'"""{module["intent"]}"""')
            lines.append("")

        # Add any direct code on the module
        if module.get("code"):
            lines.append(module["code"])
            lines.append("")

        # Add classes and functions
        for child in children:
            if child["kind"] == "module":
                continue
            if child.get("code"):
                # Add intent as docstring if present
                if child.get("intent") and '"""' not in child["code"]:
                    # Insert docstring after def/class line
                    code_lines = child["code"].split("\n")
                    if code_lines:
                        lines.append(code_lines[0])
                        lines.append(f'    """{child["intent"]}"""')
                        lines.extend(code_lines[1:])
                else:
                    lines.append(child["code"])
                lines.append("")

        return "\n".join(lines)

    # NOTE: Ingestion methods (ingest_files, _ingest_file, _extract_function, _extract_class,
    # _extract_method, _build_signature, _get_node_source, analyze_imports, _extract_imports,
    # _resolve_relative_import, analyze_calls, _extract_calls, _resolve_call_target)
    # have been moved to ingestion.py and are inherited via IngestionMixin.

    # --- Semantic Search ---

    def query(self, text: str, entity_type: str = None) -> List[Dict]:
        """
        Perform a simple semantic search across entities.

        Searches for substring matches in:
        1. Entity names
        2. Intent annotations
        3. Code content

        Args:
            text: The search text to look for (case-insensitive substring match)
            entity_type: Optional entity kind to filter by (e.g., 'method', 'class', 'function')

        Returns:
            List of dicts with 'entity' (the matched entity) and 'matches'
            (list of which fields matched: 'name', 'intent', 'code')
        """
        results = []
        seen_ids = set()

        # Empty query returns no results
        if not text or not text.strip():
            return []

        # Search entities, optionally filtered by type
        if entity_type:
            rows = self.conn.execute("SELECT * FROM entities WHERE kind = ?", (entity_type,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM entities").fetchall()

        text_lower = text.lower()

        for row in rows:
            entity = self._row_to_dict(row)
            matches = []

            # Check name match
            if entity.get("name") and text_lower in entity["name"].lower():
                matches.append("name")

            # Check intent match
            if entity.get("intent") and text_lower in entity["intent"].lower():
                matches.append("intent")

            # Check code match
            if entity.get("code") and text_lower in entity["code"].lower():
                matches.append("code")

            if matches and entity["id"] not in seen_ids:
                results.append({
                    "entity": entity,
                    "matches": matches,
                })
                seen_ids.add(entity["id"])

        # Sort by relevance: more matches = more relevant, name matches first
        def relevance_key(r):
            match_count = len(r["matches"])
            has_name = 1 if "name" in r["matches"] else 0
            has_intent = 1 if "intent" in r["matches"] else 0
            return (-match_count, -has_name, -has_intent)

        results.sort(key=relevance_key)
        return results

    # --- Vector Embeddings ---

    def generate_embeddings(self) -> Dict[str, Any]:
        """
        Generate vector embeddings for all entities and notes using sentence-transformers.

        Loads the 'all-MiniLM-L6-v2' model (384 dimensions) on first call,
        then for each entity creates an embedding from:
            f"{name} {intent or ''} {code[:500]}"

        For notes, creates an embedding from:
            f"{title} {content}"

        The embeddings are stored in the vec_entities table with entity_id as rowid.
        Note embeddings use negative rowids to distinguish them from entities.

        Returns:
            Dict with 'entities_processed', 'embeddings_created', 'skipped',
            'notes_processed', 'note_embeddings_created' counts

        Raises:
            RuntimeError: If sqlite-vec is not available
        """
        if not self._vec_available:
            raise RuntimeError(
                "sqlite-vec is not available; cannot generate embeddings"
            )

        stats = {
            "entities_processed": 0,
            "embeddings_created": 0,
            "skipped": 0,
            "notes_processed": 0,
            "note_embeddings_created": 0
        }

        # Lazy-load the embedding model
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed; cannot generate embeddings"
                )

        # Get all entities
        rows = self.conn.execute("SELECT id, name, intent, code FROM entities").fetchall()

        # Clear existing embeddings
        self.conn.execute("DELETE FROM vec_entities")

        for row in rows:
            stats["entities_processed"] += 1
            entity_id = row["id"]
            name = row["name"] or ""
            intent = row["intent"] or ""
            code = (row["code"] or "")[:500]

            # Build text for embedding
            text = f"{name} {intent} {code}".strip()
            if not text:
                stats["skipped"] += 1
                continue

            # Generate embedding
            embedding = self._embedding_model.encode(text)

            # Store in vec table with entity_id as rowid
            self.conn.execute(
                "INSERT INTO vec_entities(rowid, embedding) VALUES (?, ?)",
                (entity_id, embedding.tobytes())
            )
            stats["embeddings_created"] += 1

        # Generate embeddings for notes
        # We need a separate table for note embeddings since notes use string IDs
        # First, ensure the vec_notes table exists
        try:
            self.conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes
                USING vec0(embedding float[384])
            """)
        except Exception:
            pass  # Table may already exist

        # Clear existing note embeddings
        self.conn.execute("DELETE FROM vec_notes")

        # Get all notes
        note_rows = self.conn.execute("SELECT id, title, content FROM notes").fetchall()

        # Build a mapping from rowid to note_id for retrieval
        self._note_rowid_map = {}

        for idx, note_row in enumerate(note_rows, start=1):
            stats["notes_processed"] += 1
            note_id = note_row["id"]
            title = note_row["title"] or ""
            content = note_row["content"] or ""

            # Build text for embedding
            text = f"{title} {content}".strip()
            if not text:
                continue

            # Generate embedding
            embedding = self._embedding_model.encode(text)

            # Store in vec_notes table with sequential rowid
            self.conn.execute(
                "INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)",
                (idx, embedding.tobytes())
            )
            self._note_rowid_map[idx] = note_id
            stats["note_embeddings_created"] += 1

        self.conn.commit()
        return stats

    def semantic_search(
        self, query_text: str, limit: int = 10, include_notes: bool = False
    ) -> List[Dict]:
        """
        Search for entities semantically similar to the query text.

        Uses the same embedding model as generate_embeddings to encode the query,
        then queries sqlite-vec to find the most similar entity embeddings.

        Args:
            query_text: Natural language query (e.g., "find authentication code")
            limit: Maximum number of results to return (default 10)
            include_notes: If True, also search notes and include them in results

        Returns:
            List of dicts with keys:
            - All entity fields (id, name, kind, code, intent, metadata)
            - 'entity_type': alias for 'kind' for convenience
            - 'score': similarity score (1.0 - normalized_distance, higher is better)
            - 'distance': raw L2 distance (lower is better)
            - 'result_type': 'entity' or 'note' (when include_notes=True)
            Results are sorted by relevance (highest score first).

        Raises:
            RuntimeError: If sqlite-vec is not available or no embeddings exist
        """
        if not self._vec_available:
            raise RuntimeError(
                "sqlite-vec is not available; cannot perform semantic search"
            )

        # Check if embeddings exist
        count = self.conn.execute("SELECT COUNT(*) FROM vec_entities").fetchone()[0]
        if count == 0:
            raise RuntimeError(
                "No embeddings found. Run generate_embeddings() first."
            )

        # Lazy-load the embedding model (same as generate_embeddings)
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed; cannot perform semantic search"
                )

        # Generate embedding for query
        query_embedding = self._embedding_model.encode(query_text)

        # Query sqlite-vec for similar embeddings
        # Request extra results to account for potential deduplication
        # (duplicates can occur if entities are ingested multiple times)
        rows = self.conn.execute(
            """
            SELECT rowid, distance
            FROM vec_entities
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (query_embedding.tobytes(), limit * 2)
        ).fetchall()

        # Join back to entities table to get full entity info
        # Track seen entity IDs and names to deduplicate results
        # (duplicates can occur if entities are ingested multiple times)
        seen_ids = set()
        seen_names = {}  # name -> (result_dict, score) to keep highest score

        for row in rows:
            entity_id = row[0]
            distance = row[1]

            # Skip duplicate entity IDs
            if entity_id in seen_ids:
                continue
            seen_ids.add(entity_id)

            entity = self.get_entity(entity_id)
            if entity:
                # Convert distance to a similarity score (higher is better)
                # Using 1/(1+distance) to normalize to 0-1 range
                score = 1.0 / (1.0 + distance)
                result = dict(entity)
                result['entity_type'] = entity.get('kind')
                result['score'] = score
                result['distance'] = distance
                result['result_type'] = 'entity'

                # Deduplicate by entity name, keeping highest-scoring result
                entity_name = entity.get('name')
                if entity_name in seen_names:
                    existing_result, existing_score = seen_names[entity_name]
                    if score > existing_score:
                        # Replace with higher-scoring result
                        seen_names[entity_name] = (result, score)
                else:
                    seen_names[entity_name] = (result, score)

        # Build final results list from deduplicated entries, sorted by score
        results = [result for result, score in seen_names.values()]

        # Include notes if requested
        if include_notes:
            try:
                note_results = self.search_notes(query_text, limit=limit)
                for note in note_results:
                    note['result_type'] = 'note'
                    results.append(note)
            except RuntimeError:
                pass  # No note embeddings, skip

        results.sort(key=lambda r: r['score'], reverse=True)

        # Apply limit after deduplication
        return results[:limit]

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

    # --- Usage Analysis ---

    def find_usages(self, entity_id: int) -> List[Dict]:
        """
        Find all entities that reference a given entity.

        Finds entities that:
        - Call this entity (via 'calls' relationship)
        - Import this entity (via 'imports' relationship)
        - Inherit from this entity (via 'inherits' relationship)
        - Use this entity (via 'uses' relationship)
        - Reference this entity's name in their code (using AST-based analysis)

        For method names (e.g., 'ClassName.method_name'), this uses AST-based
        call analysis to properly detect method calls like obj.method_name()
        without false positives from strings, comments, or unrelated contexts.

        Args:
            entity_id: The ID of the entity to find usages for

        Returns:
            List of dicts with 'entity' (the referencing entity), 'relation'
            (how it references: 'calls', 'imports', 'inherits', 'uses', 'code_reference'),
            and 'context' (additional info about the reference)
        """
        target = self.get_entity(entity_id)
        if not target:
            return []

        results = []
        seen = set()  # Track (entity_id, relation) pairs to avoid duplicates

        # Find all incoming relationships
        relationships = self.get_relationships(entity_id, direction="incoming")

        for rel in relationships:
            source_id = rel["source_id"]
            relation = rel["relation"]

            if (source_id, relation) in seen:
                continue
            seen.add((source_id, relation))

            source_entity = self.get_entity(source_id)
            if source_entity:
                results.append({
                    "entity": source_entity,
                    "relation": relation,
                    "context": rel.get("metadata"),
                })

        # Also search for code references by name using AST-based analysis
        target_name = target["name"]
        short_name = target_name.split(".")[-1]
        target_kind = target.get("kind")

        # Search all entities with code for references to the target
        rows = self.conn.execute(
            "SELECT * FROM entities WHERE code IS NOT NULL AND id != ?",
            (entity_id,)
        ).fetchall()

        for row in rows:
            entity = self._row_to_dict(row)
            code = entity.get("code", "")

            # Use AST-based analysis to find references
            referenced, reference_type = self._find_ast_references(
                code, target_name, short_name, target_kind
            )

            if referenced and (entity["id"], "code_reference") not in seen:
                seen.add((entity["id"], "code_reference"))
                results.append({
                    "entity": entity,
                    "relation": "code_reference",
                    "context": {"reference_type": reference_type, "target_name": target_name},
                })

        return results

    def _find_ast_references(self, code: str, target_name: str, short_name: str,
                              target_kind: str) -> Tuple[bool, Optional[str]]:
        """
        Use AST analysis to find references to a target entity in code.

        This avoids false positives from regex matching method names in strings,
        comments, or unrelated contexts.

        Args:
            code: The source code to analyze
            target_name: The fully qualified name (e.g., 'ClassName.method_name')
            short_name: The short name (e.g., 'method_name')
            target_kind: The kind of entity ('method', 'function', 'class', etc.)

        Returns:
            Tuple of (referenced, reference_type) where referenced is True if
            a reference was found, and reference_type describes how it was found
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return False, None

        # Extract all names used in the code
        names_used = set()
        method_calls = set()
        attribute_accesses = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names_used.add(node.id)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    # Simple function call: foo()
                    names_used.add(func.id)
                elif isinstance(func, ast.Attribute):
                    # Method call: obj.method() or self.method()
                    method_calls.add(func.attr)
                    # Also track chained calls like module.function()
                    if isinstance(func.value, ast.Name):
                        attribute_accesses.add(f"{func.value.id}.{func.attr}")
            elif isinstance(node, ast.Attribute):
                # Attribute access (not necessarily a call)
                attribute_accesses.add(node.attr)
                if isinstance(node.value, ast.Name):
                    attribute_accesses.add(f"{node.value.id}.{node.attr}")

        # Check for references based on target kind
        if target_kind == "method":
            # For methods, look for the short name in method calls
            if short_name in method_calls:
                return True, "method_call"
            # Also check full qualified name in attribute accesses
            if target_name in attribute_accesses:
                return True, "full_name"
            # Check for ClassName.method pattern where ClassName matches
            parts = target_name.split(".")
            if len(parts) >= 2:
                class_name = parts[-2]
                method_name = parts[-1]
                if f"{class_name}.{method_name}" in attribute_accesses:
                    return True, "qualified_call"
        elif target_kind == "function":
            # For functions, look for direct name usage or qualified access
            if short_name in names_used:
                return True, "direct_call"
            if target_name in attribute_accesses:
                return True, "full_name"
        elif target_kind == "class":
            # For classes, look for direct name usage
            if short_name in names_used:
                return True, "instantiation"
            if target_name in attribute_accesses:
                return True, "full_name"
        else:
            # For other kinds, check both names and attributes
            if short_name in names_used:
                return True, "name_reference"
            if target_name in attribute_accesses:
                return True, "full_name"

        return False, None

    # NOTE: Notes methods (add_note, get_notes, update_note_status, get_entity_notes, get_note,
    # update_note, consolidate_notes, delete_note, get_note_stats, search_notes, check_hypothesis)
    # have been moved to note_storage.py and are inherited via NoteMixin.

    # --- Test Suggestion ---

    def suggest_tests(self, entity_id: int) -> List[str]:
        """
        Find relevant test modules for a given entity.

        Searches for test modules (modules with 'test' in name) that are likely
        to test the given entity, based on:
        1. Whether the test imports the entity's parent module
        2. Whether the entity name appears in the test's code

        Args:
            entity_id: The ID of the entity to find tests for

        Returns:
            List of test module names, sorted by relevance (import match > code match)
        """
        entity = self.get_entity(entity_id)
        if not entity:
            return []

        # Get the entity's short name and parent module
        entity_name = entity["name"]
        short_name = entity_name.split(".")[-1]

        # Get parent module name
        parent = self.get_parent(entity_id)
        parent_module_name = parent["name"] if parent else None

        # Find all test modules
        all_modules = self.find_entities(kind="module")
        test_modules = [m for m in all_modules if "test" in m["name"].lower()]

        # Score each test module
        scored_tests = []

        for test_mod in test_modules:
            score = 0

            # Check if test imports the parent module
            if parent_module_name:
                imports = self.find_related(test_mod["id"], relation="imports", direction="outgoing")
                imported_names = [i["name"] for i in imports]

                # Check for direct import of parent module
                if parent_module_name in imported_names:
                    score += 2  # Import match is high relevance

                # Also check partial matches (e.g., importing a package that contains the module)
                for imported in imported_names:
                    if parent_module_name.startswith(imported + ".") or imported.startswith(parent_module_name + "."):
                        score += 1

            # Check if entity name appears in test's source code
            metadata = test_mod.get("metadata") or {}
            file_path = metadata.get("file_path")

            if file_path:
                try:
                    source = Path(file_path).read_text(encoding="utf-8")
                    # Look for the short name as a word boundary
                    pattern = r'\b' + re.escape(short_name) + r'\b'
                    if re.search(pattern, source):
                        score += 1  # Code reference is lower relevance than import
                except (OSError, IOError):
                    pass

            if score > 0:
                scored_tests.append((test_mod["name"], score))

        # Sort by score (descending), then by name (ascending) for stability
        scored_tests.sort(key=lambda x: (-x[1], x[0]))

        return [name for name, score in scored_tests]

    # --- Graph Analysis ---

    def get_central_entities(self, limit: int = 10) -> List[Dict]:
        """
        Find most connected entities (highest in-degree + out-degree).

        Queries the relationships table to count total connections per entity,
        combining both incoming and outgoing relationships.

        Args:
            limit: Maximum number of entities to return (default 10)

        Returns:
            List of dicts with 'id', 'name', 'kind', and 'connections' (total count),
            sorted by connections descending
        """
        rows = self.conn.execute(
            """
            SELECT e.id, e.name, e.kind,
                   COALESCE(out_count, 0) + COALESCE(in_count, 0) as connections
            FROM entities e
            LEFT JOIN (
                SELECT source_id, COUNT(*) as out_count
                FROM relationships
                GROUP BY source_id
            ) out_rels ON e.id = out_rels.source_id
            LEFT JOIN (
                SELECT target_id, COUNT(*) as in_count
                FROM relationships
                GROUP BY target_id
            ) in_rels ON e.id = in_rels.target_id
            WHERE COALESCE(out_count, 0) + COALESCE(in_count, 0) > 0
            ORDER BY connections DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

        return [
            {
                "id": row["id"],
                "name": row["name"],
                "kind": row["kind"],
                "connections": row["connections"],
            }
            for row in rows
        ]

    def get_orphans(self) -> List[Dict]:
        """
        Find entities with no relationships (potential dead code).

        Returns entities that do not appear as either source or target
        in any relationship.

        Returns:
            List of entity dicts (id, name, kind, code, intent, metadata)
        """
        rows = self.conn.execute(
            """
            SELECT e.* FROM entities e
            WHERE e.id NOT IN (
                SELECT DISTINCT source_id FROM relationships
                UNION
                SELECT DISTINCT target_id FROM relationships
            )
            """
        ).fetchall()

        return [self._row_to_dict(row) for row in rows]

    def get_uncalled_methods(self, exclude_private: bool = True) -> List[Dict]:
        """
        Find methods and functions that are never called.

        These are entities of kind 'method' or 'function' that exist
        (may have member_of or contains relationships) but are never
        the target of a 'calls' relationship.

        This catches cases like setTileImages() being defined but never
        wired up - more specific than get_orphans() which requires
        zero relationships.

        Args:
            exclude_private: If True, exclude methods starting with '_'
                           (considered internal/private by convention)

        Returns:
            List of entity dicts for uncalled methods/functions
        """
        # First, get all method/function entities
        rows = self.conn.execute("""
            SELECT e.* FROM entities e
            WHERE e.kind IN ('method', 'function')
        """).fetchall()

        all_methods = [self._row_to_dict(row) for row in rows]

        # Get all called method IDs (from relationships)
        called_ids = set()
        cursor = self.conn.execute("""
            SELECT DISTINCT target_id FROM relationships
            WHERE relation = 'calls'
        """)
        for row in cursor:
            called_ids.add(row[0])

        # Get all method names that are called (from cross_file_refs)
        called_names = set()
        cursor = self.conn.execute("""
            SELECT DISTINCT target_name FROM cross_file_refs
            WHERE ref_type = 'calls'
        """)
        for row in cursor:
            called_names.add(row[0])

        # Filter to uncalled methods
        uncalled = []
        for method in all_methods:
            # Skip if called by ID
            if method['id'] in called_ids:
                continue

            # Get short name (last part after dot)
            short_name = method['name'].split('.')[-1]

            # Skip if called by name
            if short_name in called_names:
                continue

            uncalled.append(method)

        if exclude_private:
            # Filter out private methods (starting with _)
            uncalled = [
                m for m in uncalled
                if not m['name'].split('.')[-1].startswith('_')
            ]

        return uncalled

    def get_path(
        self, from_name: str, to_name: str, max_depth: int = 5
    ) -> List[List[str]]:
        """
        Find relationship paths between two entities.

        Uses BFS to find all paths from one entity to another,
        traversing relationships in both directions.

        Args:
            from_name: Name of the starting entity (can be partial match)
            to_name: Name of the target entity (can be partial match)
            max_depth: Maximum path length to search (default 5)

        Returns:
            List of paths, where each path is a list of entity names.
            Returns empty list if no path found or entities not found.
        """
        from collections import deque

        # Resolve entity names to IDs
        from_entities = self.find_entities(name=from_name)
        to_entities = self.find_entities(name=to_name)

        if not from_entities or not to_entities:
            return []

        # Find exact matches first, fallback to first result
        from_id = None
        for e in from_entities:
            if e["name"] == from_name:
                from_id = e["id"]
                from_entity_name = e["name"]
                break
        if from_id is None:
            from_id = from_entities[0]["id"]
            from_entity_name = from_entities[0]["name"]

        to_id = None
        for e in to_entities:
            if e["name"] == to_name:
                to_id = e["id"]
                break
        if to_id is None:
            to_id = to_entities[0]["id"]

        if from_id == to_id:
            return [[from_entity_name]]

        # BFS to find paths
        # Queue entries: (current_id, path_so_far)
        queue = deque([(from_id, [from_entity_name])])
        found_paths = []
        visited_at_depth = {}  # Track min depth at which each node was visited

        while queue:
            current_id, path = queue.popleft()

            if len(path) > max_depth:
                continue

            # Check if we've visited this node at a shorter or equal depth
            if current_id in visited_at_depth and visited_at_depth[current_id] < len(path):
                continue
            visited_at_depth[current_id] = len(path)

            # Get all connected entities (both directions)
            outgoing = self.conn.execute(
                "SELECT target_id FROM relationships WHERE source_id = ?",
                (current_id,)
            ).fetchall()
            incoming = self.conn.execute(
                "SELECT source_id FROM relationships WHERE target_id = ?",
                (current_id,)
            ).fetchall()

            neighbors = [row[0] for row in outgoing] + [row[0] for row in incoming]

            for neighbor_id in neighbors:
                neighbor = self.get_entity(neighbor_id)
                if not neighbor:
                    continue

                neighbor_name = neighbor["name"]

                # Skip if already in path (avoid cycles)
                if neighbor_name in path:
                    continue

                new_path = path + [neighbor_name]

                if neighbor_id == to_id:
                    found_paths.append(new_path)
                elif len(new_path) < max_depth:
                    queue.append((neighbor_id, new_path))

        # Sort by path length
        found_paths.sort(key=len)
        return found_paths

    def get_architecture_summary(self) -> str:
        """
        Generate high-level architecture overview.

        Analyzes the code graph to identify:
        - Central entities (most connected)
        - Module clusters
        - Orphan count (potential dead code)
        - Key metrics

        Returns:
            Formatted text suitable for LLM consumption
        """
        lines = []
        lines.append("# Architecture Summary")
        lines.append("")

        # Overall metrics
        entity_counts = self.conn.execute(
            "SELECT kind, COUNT(*) as count FROM entities GROUP BY kind ORDER BY count DESC"
        ).fetchall()
        rel_counts = self.conn.execute(
            "SELECT relation, COUNT(*) as count FROM relationships GROUP BY relation ORDER BY count DESC"
        ).fetchall()

        lines.append("## Metrics")
        lines.append("")
        for row in entity_counts:
            lines.append(f"- {row['kind']}: {row['count']}")
        lines.append("")
        lines.append("Relationships:")
        for row in rel_counts:
            lines.append(f"- {row['relation']}: {row['count']}")
        lines.append("")

        # Central entities
        central = self.get_central_entities(10)
        if central:
            lines.append("## Central Entities (Most Connected)")
            lines.append("")
            for e in central:
                lines.append(f"- {e['name']} ({e['kind']}): {e['connections']} connections")
            lines.append("")

        # Module clusters
        modules = self.find_entities(kind="module")
        if modules:
            lines.append("## Module Overview")
            lines.append("")

            # Group modules by top-level package
            packages = {}
            for m in modules:
                parts = m["name"].split(".")
                pkg = parts[0]
                if pkg not in packages:
                    packages[pkg] = []
                packages[pkg].append(m["name"])

            for pkg, mod_list in sorted(packages.items(), key=lambda x: -len(x[1])):
                lines.append(f"- {pkg}: {len(mod_list)} module(s)")
                if len(mod_list) <= 5:
                    for mod_name in sorted(mod_list):
                        lines.append(f"  - {mod_name}")
            lines.append("")

        # Orphans
        orphans = self.get_orphans()
        if orphans:
            lines.append("## Orphan Entities (No Relationships)")
            lines.append("")
            lines.append(f"Found {len(orphans)} orphan entities (potential dead code):")
            for orphan in orphans[:10]:
                lines.append(f"- {orphan['name']} ({orphan['kind']})")
            if len(orphans) > 10:
                lines.append(f"- ... and {len(orphans) - 10} more")
            lines.append("")

        # Import graph summary
        import_rels = self.conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE relation = 'imports'"
        ).fetchone()[0]
        if import_rels > 0:
            lines.append("## Import Graph")
            lines.append("")
            # Find modules with most imports
            most_imports = self.conn.execute(
                """
                SELECT e.name, COUNT(*) as import_count
                FROM relationships r
                JOIN entities e ON r.source_id = e.id
                WHERE r.relation = 'imports'
                GROUP BY r.source_id
                ORDER BY import_count DESC
                LIMIT 5
                """
            ).fetchall()
            lines.append("Most dependencies:")
            for row in most_imports:
                lines.append(f"- {row['name']}: imports {row['import_count']} modules")
            lines.append("")

        return "\n".join(lines)

    # --- Runtime Tracing ---

    # Maximum size for serialized arguments/return values (in characters)
    MAX_SERIALIZED_SIZE = 10000

    def _safe_serialize(self, obj: Any, max_size: int = None) -> Optional[str]:
        """
        Safely serialize an object to JSON, handling non-serializable types.

        Args:
            obj: Object to serialize
            max_size: Maximum size in characters (defaults to MAX_SERIALIZED_SIZE)

        Returns:
            JSON string, or None if serialization fails
        """
        if max_size is None:
            max_size = self.MAX_SERIALIZED_SIZE

        def make_serializable(o, depth=0):
            """Convert non-serializable objects to serializable representations."""
            if depth > 10:
                return "<max depth exceeded>"

            if o is None or isinstance(o, (bool, int, float, str)):
                return o
            elif isinstance(o, bytes):
                # Truncate large byte strings
                if len(o) > 100:
                    return f"<bytes len={len(o)}>"
                try:
                    return o.decode('utf-8', errors='replace')
                except Exception:
                    return f"<bytes len={len(o)}>"
            elif isinstance(o, (list, tuple)):
                if len(o) > 100:
                    return [make_serializable(x, depth + 1) for x in o[:100]] + [f"<...{len(o) - 100} more>"]
                return [make_serializable(x, depth + 1) for x in o]
            elif isinstance(o, dict):
                if len(o) > 50:
                    items = list(o.items())[:50]
                    result = {str(k): make_serializable(v, depth + 1) for k, v in items}
                    result["<truncated>"] = f"{len(o) - 50} more keys"
                    return result
                return {str(k): make_serializable(v, depth + 1) for k, v in o.items()}
            elif isinstance(o, set):
                return list(o)[:100]
            elif callable(o):
                return f"<function {getattr(o, '__name__', 'unknown')}>"
            elif hasattr(o, '__dict__'):
                # Object with attributes
                cls_name = type(o).__name__
                try:
                    attrs = {k: make_serializable(v, depth + 1)
                             for k, v in list(o.__dict__.items())[:20]}
                    return {"__class__": cls_name, **attrs}
                except Exception:
                    return f"<{cls_name} object>"
            else:
                # Fallback: try str representation
                try:
                    s = str(o)
                    if len(s) > 200:
                        return s[:200] + "..."
                    return s
                except Exception:
                    return f"<{type(o).__name__}>"

        try:
            serializable = make_serializable(obj)
            result = json.dumps(serializable, ensure_ascii=False)
            if len(result) > max_size:
                return json.dumps({"<truncated>": f"Object too large ({len(result)} chars)"})
            return result
        except Exception as e:
            return json.dumps({"<error>": str(e)})

    # NOTE: Trace methods (start_trace_run, end_trace_run, record_call, get_trace_run,
    # get_calls_for_run, get_recent_calls, get_failed_calls, get_trace_stats)
    # have been moved to trace_storage.py and are inherited via TraceMixin.

    # --- Utilities ---

    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Convert a database row to a dictionary."""
        d = dict(row)
        if d.get("metadata"):
            d["metadata"] = json.loads(d["metadata"])
        return d

    def close(self):
        """Close the database connection."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# Convenience function
def open_store(db_path: str = ":memory:") -> CodeStore:
    """Open or create a code store."""
    return CodeStore(db_path)
