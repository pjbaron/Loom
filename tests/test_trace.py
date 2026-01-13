"""Tests for runtime tracing storage layer."""

import pytest
import tempfile
import os
import time
from codestore import CodeStore


@pytest.fixture
def cs():
    """Create a fresh CodeStore for each test."""
    with tempfile.TemporaryDirectory() as td:
        store = CodeStore(os.path.join(td, 'test.db'))
        yield store


class TestTraceRuns:
    """Tests for trace run management."""

    def test_start_trace_run(self, cs):
        run_id = cs.start_trace_run(command="pytest tests/")
        assert run_id is not None
        assert len(run_id) == 36  # UUID format

    def test_start_trace_run_creates_running_status(self, cs):
        run_id = cs.start_trace_run()
        run = cs.get_trace_run(run_id)
        assert run['status'] == 'running'
        assert run['started_at'] is not None
        assert run['ended_at'] is None

    def test_end_trace_run_completed(self, cs):
        run_id = cs.start_trace_run()
        success = cs.end_trace_run(run_id, status='completed', exit_code=0)
        assert success

        run = cs.get_trace_run(run_id)
        assert run['status'] == 'completed'
        assert run['exit_code'] == 0
        assert run['ended_at'] is not None

    def test_end_trace_run_failed(self, cs):
        run_id = cs.start_trace_run(command="python failing_script.py")
        cs.end_trace_run(run_id, status='failed', exit_code=1)

        run = cs.get_trace_run(run_id)
        assert run['status'] == 'failed'
        assert run['exit_code'] == 1

    def test_end_nonexistent_run(self, cs):
        success = cs.end_trace_run('nonexistent-id')
        assert not success

    def test_get_trace_run_not_found(self, cs):
        run = cs.get_trace_run('nonexistent-id')
        assert run is None


class TestRecordCall:
    """Tests for recording function calls."""

    def test_record_basic_call(self, cs):
        run_id = cs.start_trace_run()
        call_id = cs.record_call(
            run_id=run_id,
            function_name='module.function',
            file_path='/path/to/file.py',
            line_number=42
        )
        assert call_id is not None
        assert len(call_id) == 36

    def test_record_call_with_args(self, cs):
        run_id = cs.start_trace_run()
        call_id = cs.record_call(
            run_id=run_id,
            function_name='math.add',
            args=(1, 2),
            kwargs={'precision': 2},
            return_value=3
        )

        calls = cs.get_calls_for_run(run_id)
        assert len(calls) == 1
        assert calls[0]['args'] == [1, 2]
        assert calls[0]['kwargs'] == {'precision': 2}
        assert calls[0]['return_value'] == 3

    def test_record_call_with_exception(self, cs):
        run_id = cs.start_trace_run()
        cs.record_call(
            run_id=run_id,
            function_name='failing.function',
            exception_type='ValueError',
            exception_message='Invalid input',
            exception_traceback='Traceback...'
        )

        calls = cs.get_calls_for_run(run_id)
        assert calls[0]['exception_type'] == 'ValueError'
        assert calls[0]['exception_message'] == 'Invalid input'

    def test_record_call_with_duration(self, cs):
        run_id = cs.start_trace_run()
        cs.record_call(
            run_id=run_id,
            function_name='slow.function',
            called_at='2024-01-01T10:00:00',
            returned_at='2024-01-01T10:00:01',
            duration_ms=1000.5
        )

        calls = cs.get_calls_for_run(run_id)
        assert calls[0]['duration_ms'] == 1000.5

    def test_record_nested_calls(self, cs):
        run_id = cs.start_trace_run()

        parent_id = cs.record_call(
            run_id=run_id,
            function_name='outer.function',
            depth=0
        )

        child_id = cs.record_call(
            run_id=run_id,
            function_name='inner.function',
            parent_call_id=parent_id,
            depth=1
        )

        calls = cs.get_calls_for_run(run_id)
        child_call = next(c for c in calls if c['call_id'] == child_id)
        assert child_call['parent_call_id'] == parent_id
        assert child_call['depth'] == 1


class TestSafeSerialization:
    """Tests for safe serialization of complex objects."""

    def test_serialize_primitives(self, cs):
        run_id = cs.start_trace_run()
        cs.record_call(
            run_id=run_id,
            function_name='test',
            args=(1, 'string', True, None, 3.14)
        )

        calls = cs.get_calls_for_run(run_id)
        assert calls[0]['args'] == [1, 'string', True, None, 3.14]

    def test_serialize_nested_structures(self, cs):
        run_id = cs.start_trace_run()
        cs.record_call(
            run_id=run_id,
            function_name='test',
            kwargs={'nested': {'a': [1, 2, 3]}}
        )

        calls = cs.get_calls_for_run(run_id)
        assert calls[0]['kwargs'] == {'nested': {'a': [1, 2, 3]}}

    def test_serialize_large_list_truncated(self, cs):
        run_id = cs.start_trace_run()
        large_list = list(range(200))
        cs.record_call(
            run_id=run_id,
            function_name='test',
            args=(large_list,)
        )

        calls = cs.get_calls_for_run(run_id)
        # Should truncate to 100 items + message
        assert len(calls[0]['args'][0]) == 101
        assert '<...100 more>' in str(calls[0]['args'][0][-1])

    def test_serialize_large_dict_truncated(self, cs):
        run_id = cs.start_trace_run()
        large_dict = {f'key{i}': i for i in range(100)}
        cs.record_call(
            run_id=run_id,
            function_name='test',
            kwargs=large_dict
        )

        calls = cs.get_calls_for_run(run_id)
        # Should truncate to 50 keys + truncation message
        assert '<truncated>' in calls[0]['kwargs']

    def test_serialize_bytes(self, cs):
        run_id = cs.start_trace_run()
        cs.record_call(
            run_id=run_id,
            function_name='test',
            args=(b'hello',)
        )

        calls = cs.get_calls_for_run(run_id)
        assert calls[0]['args'][0] == 'hello'

    def test_serialize_large_bytes_truncated(self, cs):
        run_id = cs.start_trace_run()
        cs.record_call(
            run_id=run_id,
            function_name='test',
            args=(b'x' * 200,)
        )

        calls = cs.get_calls_for_run(run_id)
        assert '<bytes len=200>' in str(calls[0]['args'][0])

    def test_serialize_custom_object(self, cs):
        class MyClass:
            def __init__(self):
                self.value = 42
                self.name = 'test'

        run_id = cs.start_trace_run()
        obj = MyClass()
        cs.record_call(
            run_id=run_id,
            function_name='test',
            return_value=obj
        )

        calls = cs.get_calls_for_run(run_id)
        ret = calls[0]['return_value']
        assert ret['__class__'] == 'MyClass'
        assert ret['value'] == 42
        assert ret['name'] == 'test'

    def test_serialize_callable(self, cs):
        def my_func():
            pass

        run_id = cs.start_trace_run()
        cs.record_call(
            run_id=run_id,
            function_name='test',
            args=(my_func,)
        )

        calls = cs.get_calls_for_run(run_id)
        assert '<function my_func>' in str(calls[0]['args'][0])

    def test_serialize_set(self, cs):
        run_id = cs.start_trace_run()
        cs.record_call(
            run_id=run_id,
            function_name='test',
            args=({1, 2, 3},)
        )

        calls = cs.get_calls_for_run(run_id)
        # Set is converted to list
        assert set(calls[0]['args'][0]) == {1, 2, 3}


class TestGetCallsForRun:
    """Tests for retrieving calls by run."""

    def test_get_calls_ordered_by_time(self, cs):
        run_id = cs.start_trace_run()

        cs.record_call(run_id=run_id, function_name='first',
                       called_at='2024-01-01T10:00:01')
        cs.record_call(run_id=run_id, function_name='second',
                       called_at='2024-01-01T10:00:02')
        cs.record_call(run_id=run_id, function_name='third',
                       called_at='2024-01-01T10:00:03')

        calls = cs.get_calls_for_run(run_id)
        assert [c['function_name'] for c in calls] == ['first', 'second', 'third']

    def test_get_calls_only_exceptions(self, cs):
        run_id = cs.start_trace_run()

        cs.record_call(run_id=run_id, function_name='success')
        cs.record_call(run_id=run_id, function_name='failure',
                       exception_type='Error')
        cs.record_call(run_id=run_id, function_name='another_success')

        calls = cs.get_calls_for_run(run_id, only_exceptions=True)
        assert len(calls) == 1
        assert calls[0]['function_name'] == 'failure'

    def test_get_calls_exclude_args(self, cs):
        run_id = cs.start_trace_run()
        cs.record_call(run_id=run_id, function_name='test',
                       args=(1, 2), kwargs={'a': 1}, return_value=3)

        calls = cs.get_calls_for_run(run_id, include_args=False)
        assert 'args' not in calls[0]
        assert 'kwargs' not in calls[0]
        assert 'return_value' not in calls[0]


class TestGetRecentCalls:
    """Tests for retrieving recent calls by function name."""

    def test_get_recent_calls_exact_match(self, cs):
        run1 = cs.start_trace_run()
        run2 = cs.start_trace_run()

        cs.record_call(run_id=run1, function_name='module.target',
                       called_at='2024-01-01T10:00:00')
        cs.record_call(run_id=run1, function_name='module.other',
                       called_at='2024-01-01T10:00:01')
        cs.record_call(run_id=run2, function_name='module.target',
                       called_at='2024-01-01T10:00:02')

        calls = cs.get_recent_calls('module.target')
        assert len(calls) == 2
        assert all(c['function_name'] == 'module.target' for c in calls)

    def test_get_recent_calls_with_pattern(self, cs):
        run_id = cs.start_trace_run()

        cs.record_call(run_id=run_id, function_name='module.ClassA.method')
        cs.record_call(run_id=run_id, function_name='module.ClassB.method')
        cs.record_call(run_id=run_id, function_name='other.function')

        calls = cs.get_recent_calls('module.%')
        assert len(calls) == 2

    def test_get_recent_calls_respects_limit(self, cs):
        run_id = cs.start_trace_run()

        for i in range(20):
            cs.record_call(run_id=run_id, function_name='target',
                           called_at=f'2024-01-01T10:00:{i:02d}')

        calls = cs.get_recent_calls('target', limit=5)
        assert len(calls) == 5

    def test_get_recent_calls_most_recent_first(self, cs):
        run_id = cs.start_trace_run()

        cs.record_call(run_id=run_id, function_name='target',
                       called_at='2024-01-01T10:00:01', args=('first',))
        cs.record_call(run_id=run_id, function_name='target',
                       called_at='2024-01-01T10:00:02', args=('second',))

        calls = cs.get_recent_calls('target')
        assert calls[0]['args'] == ['second']  # Most recent first


class TestGetFailedCalls:
    """Tests for retrieving failed calls."""

    def test_get_failed_calls_all_runs(self, cs):
        run1 = cs.start_trace_run()
        run2 = cs.start_trace_run()

        cs.record_call(run_id=run1, function_name='func1',
                       exception_type='ValueError')
        cs.record_call(run_id=run1, function_name='func2')  # success
        cs.record_call(run_id=run2, function_name='func3',
                       exception_type='TypeError')

        failed = cs.get_failed_calls()
        assert len(failed) == 2
        assert all(c['exception_type'] is not None for c in failed)

    def test_get_failed_calls_specific_run(self, cs):
        run1 = cs.start_trace_run()
        run2 = cs.start_trace_run()

        cs.record_call(run_id=run1, function_name='func1',
                       exception_type='ValueError')
        cs.record_call(run_id=run2, function_name='func2',
                       exception_type='TypeError')

        failed = cs.get_failed_calls(run_id=run1)
        assert len(failed) == 1
        assert failed[0]['exception_type'] == 'ValueError'

    def test_get_failed_calls_includes_run_info(self, cs):
        run_id = cs.start_trace_run(command='pytest test.py')
        cs.record_call(run_id=run_id, function_name='test_func',
                       exception_type='AssertionError')
        cs.end_trace_run(run_id, status='failed')

        failed = cs.get_failed_calls()
        assert failed[0]['command'] == 'pytest test.py'
        assert failed[0]['run_status'] == 'failed'


class TestTraceStats:
    """Tests for trace statistics."""

    def test_get_stats_for_run(self, cs):
        run_id = cs.start_trace_run()

        cs.record_call(run_id=run_id, function_name='func1',
                       duration_ms=100, depth=0)
        cs.record_call(run_id=run_id, function_name='func2',
                       duration_ms=200, depth=1)
        cs.record_call(run_id=run_id, function_name='func3',
                       duration_ms=300, depth=2, exception_type='Error')

        cs.end_trace_run(run_id, status='failed')

        stats = cs.get_trace_stats(run_id)
        assert stats['run_id'] == run_id
        assert stats['status'] == 'failed'
        assert stats['call_count'] == 3
        assert stats['exception_count'] == 1
        assert stats['avg_duration_ms'] == 200.0
        assert stats['max_depth'] == 2

    def test_get_global_stats(self, cs):
        run1 = cs.start_trace_run()
        run2 = cs.start_trace_run()

        cs.record_call(run_id=run1, function_name='common.func')
        cs.record_call(run_id=run1, function_name='common.func')
        cs.record_call(run_id=run2, function_name='common.func')
        cs.record_call(run_id=run2, function_name='other.func',
                       exception_type='Error')

        stats = cs.get_trace_stats()
        assert stats['run_count'] == 2
        assert stats['call_count'] == 4
        assert stats['exception_count'] == 1
        assert len(stats['top_functions']) > 0
        assert stats['top_functions'][0]['function'] == 'common.func'
        assert stats['top_functions'][0]['count'] == 3

    def test_get_stats_nonexistent_run(self, cs):
        stats = cs.get_trace_stats('nonexistent')
        assert stats == {}


class TestSchemaMigration:
    """Tests for schema migration."""

    def test_tables_created_on_init(self, cs):
        # Check trace_runs table exists
        result = cs.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trace_runs'"
        ).fetchone()
        assert result is not None

        # Check trace_calls table exists
        result = cs.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trace_calls'"
        ).fetchone()
        assert result is not None

    def test_indices_created(self, cs):
        # Check indices exist
        indices = cs.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = [i[0] for i in indices]

        assert 'idx_trace_calls_run' in index_names
        assert 'idx_trace_calls_function' in index_names

    def test_schema_version_tracked(self, cs):
        version = cs._get_schema_version()
        assert version == 3  # Updated to v3 with notes/knowledge tables

    def test_migration_idempotent(self, cs):
        """Running migrations again should not fail."""
        cs._run_migrations()
        # Should still work
        run_id = cs.start_trace_run()
        assert run_id is not None
