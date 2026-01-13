"""
Change tracking mixin for CodeStore.

Provides file change detection and impacted test identification:
- Track file modification times
- Map file changes to entities
- Suggest impacted tests based on changed entities
- Track ingest runs for change comparison

Extracted from codestore.py to reduce its size.
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class ChangeTrackingMixin:
    """Mixin providing change detection and test impact analysis."""

    # --- Change Detection ---

    def get_changed_files(self, since_run_id: str = None) -> List[Tuple[str, str]]:
        """
        Return files that changed since last ingest or specified run.

        Compares current file mtimes against stored mtimes.

        Args:
            since_run_id: Optional ingest run ID to compare against.
                         If None, compares against the most recent ingest.

        Returns:
            List of (file_path, change_type) where change_type is
            'modified', 'added', or 'deleted'.
        """
        # Get tracked files from the database
        if since_run_id:
            rows = self.conn.execute(
                "SELECT file_path, mtime FROM file_tracking WHERE last_ingest_run = ?",
                (since_run_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT file_path, mtime FROM file_tracking"
            ).fetchall()

        tracked_files = {row['file_path']: row['mtime'] for row in rows}
        changes = []

        # Check for modified and deleted files
        for file_path, stored_mtime in tracked_files.items():
            path = Path(file_path)
            if not path.exists():
                changes.append((file_path, 'deleted'))
            else:
                current_mtime = os.path.getmtime(file_path)
                if current_mtime > stored_mtime:
                    changes.append((file_path, 'modified'))

        # Check for new files in tracked directories
        # Get unique directories from tracked files
        tracked_dirs = set()
        for file_path in tracked_files.keys():
            tracked_dirs.add(str(Path(file_path).parent))

        supported_extensions = self.parser_registry.supported_extensions()

        for dir_path in tracked_dirs:
            dir_p = Path(dir_path)
            if not dir_p.exists():
                continue
            for ext in supported_extensions:
                for source_file in dir_p.glob(f"*{ext}"):
                    str_path = str(source_file)
                    if str_path not in tracked_files:
                        changes.append((str_path, 'added'))

        return changes

    def get_changed_entities(self, since_run_id: str = None) -> List[Dict]:
        """
        Return entities in files that changed.

        Maps changed files -> entities defined in those files.

        Args:
            since_run_id: Optional ingest run ID to compare against.

        Returns:
            List of entity dicts with additional 'change_type' field.
        """
        changed_files = self.get_changed_files(since_run_id)

        if not changed_files:
            return []

        entities = []
        file_to_change = {fp: ct for fp, ct in changed_files}

        for file_path, change_type in changed_files:
            if change_type == 'deleted':
                # For deleted files, find entities that were in this file
                rows = self.conn.execute(
                    "SELECT entity_id FROM entity_files WHERE file_path = ?",
                    (file_path,)
                ).fetchall()
                for row in rows:
                    entity = self.get_entity(row['entity_id'])
                    if entity:
                        entity['change_type'] = 'deleted'
                        entity['file_path'] = file_path
                        entities.append(entity)
            else:
                # For added/modified files, find entities via metadata
                rows = self.conn.execute(
                    "SELECT entity_id FROM entity_files WHERE file_path = ?",
                    (file_path,)
                ).fetchall()
                for row in rows:
                    entity = self.get_entity(row['entity_id'])
                    if entity:
                        entity['change_type'] = change_type
                        entity['file_path'] = file_path
                        entities.append(entity)

        return entities

    def get_impacted_tests(self, changed_entities: List[Dict] = None) -> List[str]:
        """
        Return tests that should run based on changed entities.

        Uses existing suggest_tests() logic but batched for multiple entities.

        Args:
            changed_entities: List of entity dicts (from get_changed_entities).
                            If None, automatically detects changed entities.

        Returns:
            Deduplicated list of test file paths, sorted by relevance.
        """
        if changed_entities is None:
            changed_entities = self.get_changed_entities()

        if not changed_entities:
            return []

        # Collect test suggestions for all changed entities
        test_scores: Dict[str, int] = {}

        for entity in changed_entities:
            entity_id = entity.get('id')
            if entity_id is None:
                continue

            # Get suggested tests for this entity
            suggested = self.suggest_tests(entity_id)
            for test_name in suggested:
                # Higher weight for tests suggested for more entities
                test_scores[test_name] = test_scores.get(test_name, 0) + 1

        # Also check trace history for runtime connections
        # Find tests that actually called changed entities in previous runs
        for entity in changed_entities:
            entity_name = entity.get('name', '')
            if not entity_name:
                continue

            # Look for test runs that called this entity
            rows = self.conn.execute(
                """
                SELECT DISTINCT r.command
                FROM trace_calls c
                JOIN trace_runs r ON c.run_id = r.run_id
                WHERE c.function_name LIKE ?
                AND r.command LIKE '%test%'
                ORDER BY r.started_at DESC
                LIMIT 20
                """,
                (f'%{entity_name.split(".")[-1]}%',)
            ).fetchall()

            for row in rows:
                if row['command']:
                    # Extract test file from command
                    test_scores[row['command']] = test_scores.get(row['command'], 0) + 2

        # Sort by score descending, then alphabetically
        sorted_tests = sorted(test_scores.items(), key=lambda x: (-x[1], x[0]))

        return [test_name for test_name, score in sorted_tests]

    # --- Ingest Run Tracking ---

    def get_latest_ingest_run(self) -> Optional[Dict]:
        """Get the most recent ingest run."""
        row = self.conn.execute(
            "SELECT * FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if row:
            result = dict(row)
            if result.get('paths'):
                result['paths'] = json.loads(result['paths'])
            if result.get('stats'):
                result['stats'] = json.loads(result['stats'])
            return result
        return None

    def get_latest_test_run(self) -> Optional[Dict]:
        """Get the most recent test run (trace run with 'test' in command)."""
        row = self.conn.execute(
            """
            SELECT * FROM trace_runs
            WHERE command LIKE '%test%'
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None

    def start_ingest_run(self, paths: List[str]) -> str:
        """
        Start tracking an ingest operation.

        Args:
            paths: List of paths being ingested

        Returns:
            The run_id for this ingest operation
        """
        run_id = str(uuid.uuid4())
        started_at = datetime.utcnow().isoformat()

        self.conn.execute(
            "INSERT INTO ingest_runs (run_id, started_at, paths, status) VALUES (?, ?, ?, ?)",
            (run_id, started_at, json.dumps(paths), "running")
        )
        self.conn.commit()
        return run_id

    def end_ingest_run(self, run_id: str, stats: Dict, status: str = "completed"):
        """
        End an ingest operation.

        Args:
            run_id: The ingest run ID
            stats: Statistics dict with counts
            status: Final status
        """
        ended_at = datetime.utcnow().isoformat()

        self.conn.execute(
            "UPDATE ingest_runs SET ended_at = ?, stats = ?, status = ? WHERE run_id = ?",
            (ended_at, json.dumps(stats), status, run_id)
        )
        self.conn.commit()

    # --- File and Entity Tracking ---

    def track_file(self, file_path: str, run_id: str = None):
        """
        Record a file's mtime for change tracking.

        Args:
            file_path: Path to the file
            run_id: Optional ingest run ID
        """
        path = Path(file_path)
        if not path.exists():
            return

        mtime = os.path.getmtime(file_path)
        size = os.path.getsize(file_path)
        ingested_at = datetime.utcnow().isoformat()

        self.conn.execute(
            """
            INSERT OR REPLACE INTO file_tracking
            (file_path, mtime, size, last_ingest_run, ingested_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(file_path), mtime, size, run_id, ingested_at)
        )
        self.conn.commit()

    def track_entity_file(self, entity_id: int, file_path: str):
        """
        Record the file an entity comes from.

        Args:
            entity_id: The entity ID
            file_path: Path to the source file
        """
        self.conn.execute(
            "INSERT OR REPLACE INTO entity_files (entity_id, file_path) VALUES (?, ?)",
            (entity_id, str(file_path))
        )
        self.conn.commit()
