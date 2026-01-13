"""
todo_storage - Mixin class for tracking work items (TODOs).

This module provides functionality for managing work items that persist across
sessions, allowing LLMs to track what needs to be done, combine overlapping items,
and complete them as work progresses.

TODOs are structured like task_runner tasks with prompts and context, but live
in the database for persistence and easy querying.

Usage:
    ./loom todo add 'Refactor the authentication module' --context 'Related to PR #123'
    ./loom todo list                    # List pending TODOs
    ./loom todo complete <id>           # Mark a TODO as done
"""

from datetime import datetime
from typing import Dict, List, Optional
import json


class TodoMixin:
    """
    Mixin class providing TODO/work item tracking operations.

    This mixin expects the following attributes on the class:
    - self.conn: sqlite3 connection with Row factory

    Usage:
        class CodeStore(TodoMixin, ...):
            ...
    """

    # Status constants
    TODO_STATUS_PENDING = 'pending'
    TODO_STATUS_IN_PROGRESS = 'in_progress'
    TODO_STATUS_COMPLETED = 'completed'
    TODO_STATUS_COMBINED = 'combined'  # Merged into another TODO

    def add_todo(
        self,
        prompt: str,
        title: str = None,
        context: str = None,
        priority: int = 0,
        entity_name: str = None,
        file_path: str = None,
        tags: List[str] = None,
        metadata: Dict = None,
        estimated_minutes: int = None,
        critical: bool = False
    ) -> int:
        """
        Add a new TODO work item.

        Args:
            prompt: The task description (what needs to be done)
            title: Short name for display (optional, defaults to first 50 chars of prompt)
            context: Additional context about the task (why, how, related info)
            priority: Priority level (higher = more urgent, default 0)
            entity_name: Related entity name (function/class being worked on)
            file_path: Related file path
            tags: List of tags for categorization
            metadata: Additional JSON-serializable data
            estimated_minutes: Optional time estimate in minutes
            critical: If true, blocks subsequent work on failure

        Returns:
            ID of the created TODO
        """
        timestamp = datetime.utcnow().isoformat()
        tags_str = ','.join(tags) if tags else None
        metadata_json = json.dumps(metadata) if metadata else None

        # Auto-generate title from prompt if not provided
        if title is None:
            title = prompt[:50] + ('...' if len(prompt) > 50 else '')

        # Get next position (FIFO order)
        cursor = self.conn.execute("SELECT MAX(position) FROM todos")
        max_pos = cursor.fetchone()[0]
        next_position = (max_pos or 0) + 1

        cursor = self.conn.execute(
            """
            INSERT INTO todos
            (created_at, title, prompt, context, priority, position, entity_name,
             file_path, tags, metadata, status, estimated_minutes, critical)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (timestamp, title, prompt, context, priority, next_position, entity_name,
             file_path, tags_str, metadata_json, self.TODO_STATUS_PENDING,
             estimated_minutes, 1 if critical else 0)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_todo(self, todo_id: int) -> Optional[Dict]:
        """
        Get a single TODO by ID.

        Args:
            todo_id: The TODO ID

        Returns:
            TODO dict or None if not found
        """
        cursor = self.conn.execute(
            "SELECT * FROM todos WHERE id = ?",
            (todo_id,)
        )
        row = cursor.fetchone()
        if row:
            return self._todo_row_to_dict(row)
        return None

    def list_todos(
        self,
        status: str = None,
        entity_name: str = None,
        file_path: str = None,
        tags: List[str] = None,
        limit: int = 50,
        include_completed: bool = False,
        critical_only: bool = False
    ) -> List[Dict]:
        """
        List TODOs matching criteria, ordered by priority then position (FIFO).

        Args:
            status: Filter by status ('pending', 'in_progress', 'completed')
            entity_name: Filter by related entity
            file_path: Filter by related file
            tags: Filter by tags (OR logic)
            limit: Maximum number of results
            include_completed: If True, also show completed TODOs
            critical_only: If True, only show critical TODOs

        Returns:
            List of TODO dicts ordered by priority (desc) then position (asc)
        """
        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        elif not include_completed:
            # Exclude completed and combined by default
            conditions.append("status NOT IN (?, ?)")
            params.append(self.TODO_STATUS_COMPLETED)
            params.append(self.TODO_STATUS_COMBINED)

        if entity_name:
            conditions.append("entity_name LIKE ?")
            params.append(f"%{entity_name}%")

        if file_path:
            conditions.append("file_path LIKE ?")
            params.append(f"%{file_path}%")

        if tags:
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("tags LIKE ?")
                params.append(f"%{tag}%")
            conditions.append(f"({' OR '.join(tag_conditions)})")

        if critical_only:
            conditions.append("critical = 1")

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        params.append(limit)

        cursor = self.conn.execute(
            f"""
            SELECT * FROM todos
            {where_clause}
            ORDER BY priority DESC, position ASC, created_at ASC
            LIMIT ?
            """,
            params
        )

        return [self._todo_row_to_dict(row) for row in cursor.fetchall()]

    def get_next_todo(self, critical_first: bool = True) -> Optional[Dict]:
        """
        Get the next TODO to work on (highest priority pending item, FIFO).

        Args:
            critical_first: If True, prioritize critical TODOs over non-critical

        Returns:
            The next TODO dict or None if queue is empty
        """
        order_by = "priority DESC, position ASC, created_at ASC"
        if critical_first:
            order_by = "critical DESC, priority DESC, position ASC, created_at ASC"

        cursor = self.conn.execute(
            f"""
            SELECT * FROM todos
            WHERE status = ?
            ORDER BY {order_by}
            LIMIT 1
            """,
            (self.TODO_STATUS_PENDING,)
        )
        row = cursor.fetchone()
        if row:
            return self._todo_row_to_dict(row)
        return None

    def start_todo(self, todo_id: int) -> bool:
        """
        Mark a TODO as in progress.

        Args:
            todo_id: The TODO ID to start

        Returns:
            True if updated, False if not found
        """
        timestamp = datetime.utcnow().isoformat()
        cursor = self.conn.execute(
            """
            UPDATE todos
            SET status = ?, started_at = ?
            WHERE id = ? AND status = ?
            """,
            (self.TODO_STATUS_IN_PROGRESS, timestamp, todo_id, self.TODO_STATUS_PENDING)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def complete_todo(
        self,
        todo_id: int,
        result: str = None,
        completion_notes: str = None,
        success: bool = True,
        notes: str = None
    ) -> bool:
        """
        Mark a TODO as completed.

        Args:
            todo_id: The TODO ID to complete
            result: Optional result/notes about completion (stored in metadata)
            completion_notes: Notes about completion (stored in dedicated column)
            success: Whether the task was successful (default True)
            notes: Alias for completion_notes (for API compatibility)

        Returns:
            True if updated, False if not found
        """
        timestamp = datetime.utcnow().isoformat()

        # Get existing metadata to merge
        existing = self.get_todo(todo_id)
        if not existing:
            return False

        metadata = existing.get('metadata') or {}
        metadata['result'] = result
        metadata['success'] = success

        # Use notes as completion_notes if completion_notes not explicitly provided
        final_notes = completion_notes or notes or result

        cursor = self.conn.execute(
            """
            UPDATE todos
            SET status = ?, completed_at = ?, metadata = ?, completion_notes = ?
            WHERE id = ?
            """,
            (self.TODO_STATUS_COMPLETED, timestamp, json.dumps(metadata), final_notes, todo_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def update_todo(
        self,
        todo_id: int,
        title: str = None,
        prompt: str = None,
        context: str = None,
        priority: int = None,
        position: int = None,
        tags: List[str] = None,
        estimated_minutes: int = None,
        critical: bool = None
    ) -> bool:
        """
        Update a TODO's fields.

        Args:
            todo_id: The TODO ID to update
            title: New title
            prompt: New prompt text
            context: New context
            priority: New priority
            position: New position for ordering
            tags: New tags list
            estimated_minutes: New time estimate
            critical: Whether this blocks subsequent work

        Returns:
            True if updated, False if not found
        """
        updates = []
        params = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if prompt is not None:
            updates.append("prompt = ?")
            params.append(prompt)
        if context is not None:
            updates.append("context = ?")
            params.append(context)
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        if position is not None:
            updates.append("position = ?")
            params.append(position)
        if tags is not None:
            updates.append("tags = ?")
            params.append(','.join(tags) if tags else None)
        if estimated_minutes is not None:
            updates.append("estimated_minutes = ?")
            params.append(estimated_minutes)
        if critical is not None:
            updates.append("critical = ?")
            params.append(1 if critical else 0)

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(todo_id)

        cursor = self.conn.execute(
            f"""
            UPDATE todos
            SET {', '.join(updates)}
            WHERE id = ?
            """,
            params
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def combine_todos(self, keep_id: int, merge_ids: List[int], new_prompt: str = None, new_title: str = None) -> bool:
        """
        Combine overlapping TODOs into one.

        Marks the merged TODOs as 'combined' and optionally updates the kept TODO's prompt.

        Args:
            keep_id: The TODO ID to keep
            merge_ids: List of TODO IDs to merge into keep_id
            new_prompt: Optional new combined prompt
            new_title: Optional new title for combined TODO

        Returns:
            True if successful, False if keep_id not found
        """
        # Verify keep_id exists
        keep_todo = self.get_todo(keep_id)
        if not keep_todo:
            return False

        # Gather context from all TODOs being merged
        merged_context_parts = []
        if keep_todo.get('context'):
            merged_context_parts.append(keep_todo['context'])

        for merge_id in merge_ids:
            merge_todo = self.get_todo(merge_id)
            if merge_todo:
                # Add to context
                merged_context_parts.append(f"[Merged from #{merge_id}] {merge_todo['prompt']}")
                if merge_todo.get('context'):
                    merged_context_parts.append(merge_todo['context'])

        # Update the kept TODO
        new_context = '\n'.join(merged_context_parts) if merged_context_parts else None

        timestamp = datetime.utcnow().isoformat()

        # Build update query for kept TODO
        update_parts = ["updated_at = ?"]
        update_params = [timestamp]

        if new_prompt:
            update_parts.append("prompt = ?")
            update_params.append(new_prompt)
        if new_title:
            update_parts.append("title = ?")
            update_params.append(new_title)
        if new_context:
            update_parts.append("context = ?")
            update_params.append(new_context)

        update_params.append(keep_id)
        self.conn.execute(
            f"""
            UPDATE todos
            SET {', '.join(update_parts)}
            WHERE id = ?
            """,
            update_params
        )

        # Mark merged TODOs as combined using the dedicated combined_into column
        if merge_ids:
            placeholders = ','.join('?' * len(merge_ids))
            self.conn.execute(
                f"""
                UPDATE todos
                SET status = ?, combined_into = ?, updated_at = ?
                WHERE id IN ({placeholders})
                """,
                [self.TODO_STATUS_COMBINED, keep_id, timestamp] + list(merge_ids)
            )

        self.conn.commit()
        return True

    def search_todos(self, query: str, limit: int = 20) -> List[Dict]:
        """
        Search TODOs by prompt or context text.

        Args:
            query: Search text
            limit: Maximum results

        Returns:
            List of matching TODO dicts
        """
        cursor = self.conn.execute(
            """
            SELECT * FROM todos
            WHERE (prompt LIKE ? OR context LIKE ?)
            AND status NOT IN (?, ?)
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
            """,
            (f"%{query}%", f"%{query}%",
             self.TODO_STATUS_COMPLETED, self.TODO_STATUS_COMBINED,
             limit)
        )
        return [self._todo_row_to_dict(row) for row in cursor.fetchall()]

    def get_todo_stats(self) -> Dict:
        """
        Get statistics about TODOs.

        Returns:
            Dict with counts by status and other stats
        """
        cursor = self.conn.execute(
            """
            SELECT
                status,
                COUNT(*) as count,
                AVG(priority) as avg_priority
            FROM todos
            GROUP BY status
            """
        )

        stats = {
            'by_status': {},
            'total': 0,
            'pending': 0,
            'in_progress': 0,
            'completed': 0
        }

        for row in cursor.fetchall():
            status = row['status']
            count = row['count']
            stats['by_status'][status] = {
                'count': count,
                'avg_priority': row['avg_priority']
            }
            stats['total'] += count
            if status == self.TODO_STATUS_PENDING:
                stats['pending'] = count
            elif status == self.TODO_STATUS_IN_PROGRESS:
                stats['in_progress'] = count
            elif status == self.TODO_STATUS_COMPLETED:
                stats['completed'] = count

        return stats

    def delete_todo(self, todo_id: int) -> bool:
        """
        Delete a TODO.

        Args:
            todo_id: The TODO ID to delete

        Returns:
            True if deleted, False if not found
        """
        cursor = self.conn.execute(
            "DELETE FROM todos WHERE id = ?",
            (todo_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def clear_completed_todos(self, days_old: int = 30) -> int:
        """
        Delete completed TODOs older than N days.

        Args:
            days_old: Delete completed TODOs older than this many days

        Returns:
            Number of TODOs deleted
        """
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days_old)).isoformat()

        cursor = self.conn.execute(
            """
            DELETE FROM todos
            WHERE status = ? AND completed_at < ?
            """,
            (self.TODO_STATUS_COMPLETED, cutoff)
        )
        self.conn.commit()
        return cursor.rowcount

    # --- Convenience aliases to match the requested API ---

    def get_todos(
        self,
        status: str = None,
        include_combined: bool = False,
        limit: int = None,
        tags: List[str] = None
    ) -> List[Dict]:
        """
        Get TODOs ordered by position (FIFO). Alias for list_todos with simplified params.

        Args:
            status: Filter by status (pending, in_progress, completed, combined)
            include_combined: Include items combined into others (default False)
            limit: Maximum number of results (default: no limit)
            tags: Filter by tags

        Returns:
            List of TODO dicts ordered by priority then position (FIFO)
        """
        # Default to pending only if no status specified and not including combined
        if status is None and not include_combined:
            # Get pending and in_progress by default (most common use case)
            return self.list_todos(
                status=None,
                tags=tags,
                limit=limit or 100,
                include_completed=include_combined
            )
        elif status:
            return self.list_todos(
                status=status,
                tags=tags,
                limit=limit or 100,
                include_completed=True
            )
        else:
            return self.list_todos(
                status=None,
                tags=tags,
                limit=limit or 100,
                include_completed=include_combined
            )

    def todo_stats(self) -> Dict:
        """
        Get counts by status. Alias for get_todo_stats().

        Returns:
            Dict with: {pending: N, in_progress: N, completed: N, combined: N}
        """
        stats = self.get_todo_stats()
        # Return simplified format matching requested API
        result = {
            'pending': stats.get('pending', 0),
            'in_progress': stats.get('in_progress', 0),
            'completed': stats.get('completed', 0),
            'combined': stats['by_status'].get(self.TODO_STATUS_COMBINED, {}).get('count', 0),
            'total': stats.get('total', 0)
        }
        return result

    def merge_todos(
        self,
        todo_ids: List[int],
        combined_title: str = None,
        combined_prompt: str = None
    ) -> int:
        """
        Combine multiple TODOs into one.

        Creates a new combined TODO (using the first ID as survivor) with combined context.
        Marks others as 'combined' with combined_into pointing to survivor.

        Args:
            todo_ids: List of TODO IDs to combine (first one survives)
            combined_title: Optional new title for the combined TODO
            combined_prompt: Optional new combined prompt

        Returns:
            The surviving TODO id
        """
        if not todo_ids or len(todo_ids) < 2:
            raise ValueError("Need at least 2 TODO IDs to combine")

        keep_id = todo_ids[0]
        merge_ids = todo_ids[1:]

        self.combine_todos(
            keep_id=keep_id,
            merge_ids=merge_ids,
            new_prompt=combined_prompt,
            new_title=combined_title
        )
        return keep_id

    def reorder_todo(self, todo_id: int, new_position: int) -> bool:
        """
        Move a TODO to a new position in the queue.

        Args:
            todo_id: The TODO ID to move
            new_position: The new position (1-based)

        Returns:
            True if successful, False if not found
        """
        # Get current position
        todo = self.get_todo(todo_id)
        if not todo:
            return False

        old_position = todo.get('position')
        if old_position == new_position:
            return True  # No change needed

        timestamp = datetime.utcnow().isoformat()

        if old_position is None:
            # Just set the position directly
            self.conn.execute(
                "UPDATE todos SET position = ?, updated_at = ? WHERE id = ?",
                (new_position, timestamp, todo_id)
            )
        elif new_position < old_position:
            # Moving up: shift others down
            self.conn.execute(
                """
                UPDATE todos
                SET position = position + 1
                WHERE position >= ? AND position < ? AND id != ?
                """,
                (new_position, old_position, todo_id)
            )
            self.conn.execute(
                "UPDATE todos SET position = ?, updated_at = ? WHERE id = ?",
                (new_position, timestamp, todo_id)
            )
        else:
            # Moving down: shift others up
            self.conn.execute(
                """
                UPDATE todos
                SET position = position - 1
                WHERE position > ? AND position <= ? AND id != ?
                """,
                (old_position, new_position, todo_id)
            )
            self.conn.execute(
                "UPDATE todos SET position = ?, updated_at = ? WHERE id = ?",
                (new_position, timestamp, todo_id)
            )

        self.conn.commit()
        return True

    def _todo_row_to_dict(self, row) -> Dict:
        """Convert a database row to a TODO dict."""
        entry = dict(row)

        # Parse tags back to list
        if entry.get('tags'):
            entry['tags'] = entry['tags'].split(',')
        else:
            entry['tags'] = []

        # Parse metadata JSON
        if entry.get('metadata'):
            try:
                entry['metadata'] = json.loads(entry['metadata'])
            except (json.JSONDecodeError, TypeError):
                entry['metadata'] = {}
        else:
            entry['metadata'] = {}

        # Ensure critical is a boolean
        if 'critical' in entry:
            entry['critical'] = bool(entry['critical'])

        return entry
