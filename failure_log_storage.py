"""
failure_log_storage - Mixin class for tracking failed fix attempts.

This module provides functionality for logging and querying failed fixes
to help developers avoid repeating unsuccessful approaches.

Usage:
    ./loom failure-log 'message' - Log a failure
    ./loom attempted-fixes query - See what's been tried for an entity/file
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional


class FailureLogMixin:
    """
    Mixin class providing failure tracking operations.

    This mixin expects the following attributes on the class:
    - self.conn: sqlite3 connection with Row factory
    - self.query: method for searching entities by name

    Usage:
        class CodeStore(FailureLogMixin, ...):
            ...
    """

    def log_failure(
        self,
        attempted_fix: str,
        context: str = None,
        entity_name: str = None,
        entity_id: int = None,
        file_path: str = None,
        failure_reason: str = None,
        related_error: str = None,
        tags: List[str] = None
    ) -> int:
        """
        Log a failed fix attempt.

        Args:
            attempted_fix: What was tried
            context: What was being worked on
            entity_name: Name of function/class being fixed (optional)
            entity_id: ID of the entity being fixed (optional, takes precedence over entity_name)
            file_path: File being worked on (optional)
            failure_reason: Why it didn't work (optional)
            related_error: Error message if any (optional)
            tags: List of tags for categorization (optional)

        Returns:
            ID of the created failure log
        """
        timestamp = datetime.utcnow().isoformat()
        tags_str = ','.join(tags) if tags else None

        # Resolve entity_name to entity_id if entity_id not provided
        if entity_id is None and entity_name:
            results = self.query(entity_name)
            if results:
                # Find exact match or use first result
                for r in results:
                    if r['entity']['name'] == entity_name:
                        entity_id = r['entity']['id']
                        break
                if entity_id is None:
                    entity_id = results[0]['entity']['id']

        cursor = self.conn.execute(
            """
            INSERT INTO failure_logs
            (timestamp, entity_id, entity_name, file_path, context, attempted_fix, failure_reason, related_error, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (timestamp, entity_id, entity_name, file_path, context, attempted_fix, failure_reason, related_error, tags_str)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_failure_logs(
        self,
        entity_name: str = None,
        entity_id: int = None,
        file_path: str = None,
        limit: int = 50,
        tags: List[str] = None,
        context_search: str = None
    ) -> List[Dict]:
        """
        Get failure logs matching criteria.

        Args:
            entity_name: Filter by entity name
            entity_id: Filter by entity ID (takes precedence over entity_name)
            file_path: Filter by file path
            limit: Max number of results
            tags: Filter by tags (OR logic)
            context_search: Search in context and attempted_fix text

        Returns:
            List of failure log dicts with keys: id, timestamp, context,
            attempted_fix, failure_reason, related_error, tags, entity_name, file_path
        """
        conditions = []
        params = []

        if entity_id is not None:
            conditions.append("entity_id = ?")
            params.append(entity_id)
        elif entity_name is not None:
            # Support both exact match and partial match
            conditions.append("(entity_name = ? OR entity_name LIKE ?)")
            params.append(entity_name)
            params.append(f"%{entity_name}%")

        if file_path is not None:
            conditions.append("file_path LIKE ?")
            params.append(f"%{file_path}%")

        if tags:
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("tags LIKE ?")
                params.append(f"%{tag}%")
            conditions.append(f"({' OR '.join(tag_conditions)})")

        if context_search is not None:
            conditions.append("(context LIKE ? OR attempted_fix LIKE ?)")
            params.append(f"%{context_search}%")
            params.append(f"%{context_search}%")

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        params.append(limit)

        cursor = self.conn.execute(
            f"""
            SELECT id, timestamp, entity_name, file_path, context, attempted_fix,
                   failure_reason, related_error, tags
            FROM failure_logs
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            params
        )

        results = []
        for row in cursor.fetchall():
            entry = dict(row)
            # Parse tags back to list
            if entry.get('tags'):
                entry['tags'] = entry['tags'].split(',')
            else:
                entry['tags'] = []
            results.append(entry)

        return results

    def get_recent_failures(self, days: int = 7, limit: int = 20) -> List[Dict]:
        """
        Get recent failure logs.

        Args:
            days: Number of days to look back (default 7)
            limit: Maximum number of results (default 20)

        Returns:
            List of failure log dicts
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        cursor = self.conn.execute(
            """
            SELECT id, timestamp, entity_name, file_path, context, attempted_fix,
                   failure_reason, related_error, tags
            FROM failure_logs
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (cutoff, limit)
        )

        results = []
        for row in cursor.fetchall():
            entry = dict(row)
            if entry.get('tags'):
                entry['tags'] = entry['tags'].split(',')
            else:
                entry['tags'] = []
            results.append(entry)

        return results

    def delete_failure_log(self, log_id: int) -> bool:
        """
        Delete a failure log by ID.

        Args:
            log_id: The ID of the failure log to delete

        Returns:
            True if deleted, False if not found
        """
        cursor = self.conn.execute(
            "DELETE FROM failure_logs WHERE id = ?",
            (log_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def clear_old_failures(self, days: int = 30) -> int:
        """
        Delete failure logs older than N days.

        Args:
            days: Delete logs older than this many days (default 30)

        Returns:
            Count deleted
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        cursor = self.conn.execute(
            "DELETE FROM failure_logs WHERE timestamp < ?",
            (cutoff,)
        )
        self.conn.commit()
        return cursor.rowcount
