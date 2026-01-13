"""
trace_storage - Mixin class for trace run and call recording operations.

This module is extracted from codestore.py to reduce file size.
It provides all runtime tracing functionality for recording function calls,
managing trace runs, and querying trace data.
"""

import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any


class TraceMixin:
    """
    Mixin class providing trace storage operations.

    This mixin expects the following attributes on the class:
    - self.conn: sqlite3 connection with Row factory
    - self.MAX_SERIALIZED_SIZE: int constant for serialization limits
    - self._safe_serialize: method for safe JSON serialization

    Usage:
        class CodeStore(TraceMixin, ...):
            ...
    """

    def start_trace_run(self, command: str = None) -> str:
        """
        Start a new trace run.

        Args:
            command: Optional description of what is being executed

        Returns:
            The run_id for the new trace run
        """
        run_id = str(uuid.uuid4())
        started_at = datetime.utcnow().isoformat()

        self.conn.execute(
            "INSERT INTO trace_runs (run_id, started_at, command, status) VALUES (?, ?, ?, ?)",
            (run_id, started_at, command, "running")
        )
        self.conn.commit()
        return run_id

    def end_trace_run(
        self,
        run_id: str,
        status: str = "completed",
        exit_code: int = None
    ) -> bool:
        """
        End a trace run.

        Args:
            run_id: The ID of the run to end
            status: Final status ('completed', 'failed', 'crashed')
            exit_code: Optional exit code

        Returns:
            True if the run was updated, False if not found
        """
        ended_at = datetime.utcnow().isoformat()

        cursor = self.conn.execute(
            "UPDATE trace_runs SET ended_at = ?, status = ?, exit_code = ? WHERE run_id = ?",
            (ended_at, status, exit_code, run_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def record_call(
        self,
        run_id: str,
        function_name: str,
        file_path: str = None,
        line_number: int = None,
        called_at: str = None,
        returned_at: str = None,
        duration_ms: float = None,
        args: tuple = None,
        kwargs: dict = None,
        return_value: Any = None,
        exception_type: str = None,
        exception_message: str = None,
        exception_traceback: str = None,
        parent_call_id: str = None,
        depth: int = 0
    ) -> str:
        """
        Record a function call within a trace run.

        Args:
            run_id: The ID of the trace run
            function_name: Fully qualified function name (e.g., module.class.method)
            file_path: Source file path
            line_number: Line number of the function definition
            called_at: ISO timestamp when function was called (defaults to now)
            returned_at: ISO timestamp when function returned
            duration_ms: Execution time in milliseconds
            args: Positional arguments (will be safely serialized)
            kwargs: Keyword arguments (will be safely serialized)
            return_value: Return value (will be safely serialized)
            exception_type: Type of exception if one was raised
            exception_message: Exception message
            exception_traceback: Full traceback string
            parent_call_id: ID of the parent call for nested calls
            depth: Nesting depth (0 for top-level calls)

        Returns:
            The call_id for the recorded call
        """
        call_id = str(uuid.uuid4())

        if called_at is None:
            called_at = datetime.utcnow().isoformat()

        # Safely serialize args, kwargs, and return value
        args_json = self._safe_serialize(args) if args is not None else None
        kwargs_json = self._safe_serialize(kwargs) if kwargs is not None else None
        return_value_json = self._safe_serialize(return_value) if return_value is not None else None

        self.conn.execute(
            """
            INSERT INTO trace_calls (
                call_id, run_id, function_name, file_path, line_number,
                called_at, returned_at, duration_ms, args_json, kwargs_json,
                return_value_json, exception_type, exception_message,
                exception_traceback, parent_call_id, depth
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (call_id, run_id, function_name, file_path, line_number,
             called_at, returned_at, duration_ms, args_json, kwargs_json,
             return_value_json, exception_type, exception_message,
             exception_traceback, parent_call_id, depth)
        )
        self.conn.commit()
        return call_id

    def get_trace_run(self, run_id: str) -> Optional[Dict]:
        """
        Get a trace run by ID.

        Args:
            run_id: The ID of the run to retrieve

        Returns:
            Dict with run details, or None if not found
        """
        row = self.conn.execute(
            "SELECT * FROM trace_runs WHERE run_id = ?",
            (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_calls_for_run(
        self,
        run_id: str,
        include_args: bool = True,
        only_exceptions: bool = False
    ) -> List[Dict]:
        """
        Get all calls for a trace run.

        Args:
            run_id: The ID of the run
            include_args: If True, include serialized args/kwargs/return values
            only_exceptions: If True, only return calls that raised exceptions

        Returns:
            List of call dicts, ordered by called_at
        """
        query = "SELECT * FROM trace_calls WHERE run_id = ?"
        params = [run_id]

        if only_exceptions:
            query += " AND exception_type IS NOT NULL"

        query += " ORDER BY called_at"

        rows = self.conn.execute(query, params).fetchall()
        results = []

        for row in rows:
            call = dict(row)
            # Parse JSON fields
            if call.get('args_json'):
                try:
                    call['args'] = json.loads(call['args_json'])
                except json.JSONDecodeError:
                    call['args'] = None
            if call.get('kwargs_json'):
                try:
                    call['kwargs'] = json.loads(call['kwargs_json'])
                except json.JSONDecodeError:
                    call['kwargs'] = None
            if call.get('return_value_json'):
                try:
                    call['return_value'] = json.loads(call['return_value_json'])
                except json.JSONDecodeError:
                    call['return_value'] = None

            if not include_args:
                call.pop('args_json', None)
                call.pop('kwargs_json', None)
                call.pop('return_value_json', None)
                call.pop('args', None)
                call.pop('kwargs', None)
                call.pop('return_value', None)

            results.append(call)

        return results

    def get_recent_calls(
        self,
        function_name: str,
        limit: int = 10,
        include_args: bool = True
    ) -> List[Dict]:
        """
        Get recent calls to a specific function across all runs.

        Args:
            function_name: The function name to search for (supports LIKE patterns)
            limit: Maximum number of calls to return
            include_args: If True, include serialized args/kwargs/return values

        Returns:
            List of call dicts, ordered by most recent first
        """
        # Support both exact match and LIKE patterns
        if '%' in function_name:
            query = "SELECT * FROM trace_calls WHERE function_name LIKE ? ORDER BY called_at DESC LIMIT ?"
        else:
            query = "SELECT * FROM trace_calls WHERE function_name = ? ORDER BY called_at DESC LIMIT ?"

        rows = self.conn.execute(query, (function_name, limit)).fetchall()
        results = []

        for row in rows:
            call = dict(row)
            # Parse JSON fields
            if call.get('args_json'):
                try:
                    call['args'] = json.loads(call['args_json'])
                except json.JSONDecodeError:
                    call['args'] = None
            if call.get('kwargs_json'):
                try:
                    call['kwargs'] = json.loads(call['kwargs_json'])
                except json.JSONDecodeError:
                    call['kwargs'] = None
            if call.get('return_value_json'):
                try:
                    call['return_value'] = json.loads(call['return_value_json'])
                except json.JSONDecodeError:
                    call['return_value'] = None

            if not include_args:
                call.pop('args_json', None)
                call.pop('kwargs_json', None)
                call.pop('return_value_json', None)
                call.pop('args', None)
                call.pop('kwargs', None)
                call.pop('return_value', None)

            results.append(call)

        return results

    def get_failed_calls(self, run_id: str = None, limit: int = 50) -> List[Dict]:
        """
        Get calls that raised exceptions.

        Args:
            run_id: Optional run ID to filter by
            limit: Maximum number of calls to return

        Returns:
            List of call dicts with exception information
        """
        if run_id:
            query = """
                SELECT c.*, r.command, r.status as run_status
                FROM trace_calls c
                JOIN trace_runs r ON c.run_id = r.run_id
                WHERE c.run_id = ? AND c.exception_type IS NOT NULL
                ORDER BY c.called_at DESC
                LIMIT ?
            """
            rows = self.conn.execute(query, (run_id, limit)).fetchall()
        else:
            query = """
                SELECT c.*, r.command, r.status as run_status
                FROM trace_calls c
                JOIN trace_runs r ON c.run_id = r.run_id
                WHERE c.exception_type IS NOT NULL
                ORDER BY c.called_at DESC
                LIMIT ?
            """
            rows = self.conn.execute(query, (limit,)).fetchall()

        return [dict(row) for row in rows]

    def get_trace_stats(self, run_id: str = None) -> Dict:
        """
        Get statistics about trace data.

        Args:
            run_id: Optional run ID to get stats for specific run

        Returns:
            Dict with counts and summary statistics
        """
        if run_id:
            run = self.get_trace_run(run_id)
            if not run:
                return {}

            call_count = self.conn.execute(
                "SELECT COUNT(*) FROM trace_calls WHERE run_id = ?", (run_id,)
            ).fetchone()[0]

            exception_count = self.conn.execute(
                "SELECT COUNT(*) FROM trace_calls WHERE run_id = ? AND exception_type IS NOT NULL",
                (run_id,)
            ).fetchone()[0]

            avg_duration = self.conn.execute(
                "SELECT AVG(duration_ms) FROM trace_calls WHERE run_id = ? AND duration_ms IS NOT NULL",
                (run_id,)
            ).fetchone()[0]

            max_depth = self.conn.execute(
                "SELECT MAX(depth) FROM trace_calls WHERE run_id = ?", (run_id,)
            ).fetchone()[0]

            return {
                'run_id': run_id,
                'status': run.get('status'),
                'call_count': call_count,
                'exception_count': exception_count,
                'avg_duration_ms': avg_duration,
                'max_depth': max_depth or 0,
            }
        else:
            # Global stats
            run_count = self.conn.execute("SELECT COUNT(*) FROM trace_runs").fetchone()[0]
            call_count = self.conn.execute("SELECT COUNT(*) FROM trace_calls").fetchone()[0]
            exception_count = self.conn.execute(
                "SELECT COUNT(*) FROM trace_calls WHERE exception_type IS NOT NULL"
            ).fetchone()[0]

            # Most called functions
            top_functions = self.conn.execute(
                """
                SELECT function_name, COUNT(*) as count
                FROM trace_calls
                GROUP BY function_name
                ORDER BY count DESC
                LIMIT 10
                """
            ).fetchall()

            return {
                'run_count': run_count,
                'call_count': call_count,
                'exception_count': exception_count,
                'top_functions': [{'function': r[0], 'count': r[1]} for r in top_functions],
            }
