"""Tests for the tracer instrumentation module."""

import pytest
import tempfile
import os
import sys
import time
import threading
from types import ModuleType

from tracer import trace, trace_run, trace_module, trace_class, is_traced, get_original
from codestore import CodeStore


@pytest.fixture
def db_path():
    """Create a temporary database path for each test."""
    with tempfile.TemporaryDirectory() as td:
        yield os.path.join(td, 'test.db')


@pytest.fixture
def cs(db_path):
    """Create a fresh CodeStore for each test."""
    store = CodeStore(db_path)
    yield store
    store.close()


class TestTraceDecorator:
    """Tests for the @trace decorator."""

    def test_basic_function_tracing(self, db_path):
        """Verify that basic function calls are traced."""
        @trace
        def add(a, b):
            return a + b

        with trace_run(command="test", db_path=db_path) as run_id:
            result = add(1, 2)

        assert result == 3

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 1
        assert 'add' in calls[0]['function_name']
        assert calls[0]['args'] == [1, 2]
        assert calls[0]['return_value'] == 3

    def test_function_with_kwargs(self, db_path):
        """Verify kwargs are captured correctly."""
        @trace
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        with trace_run(db_path=db_path) as run_id:
            result = greet("World", greeting="Hi")

        assert result == "Hi, World!"

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert calls[0]['kwargs'] == {'greeting': 'Hi'}

    def test_no_tracing_without_context(self, db_path):
        """Verify functions work normally without trace_run context."""
        call_count = [0]

        @trace
        def tracked_func():
            call_count[0] += 1
            return 42

        # Call without trace context
        result = tracked_func()
        assert result == 42
        assert call_count[0] == 1

        # Verify nothing was recorded
        store = CodeStore(db_path)
        stats = store.get_trace_stats()
        store.close()

        assert stats['run_count'] == 0
        assert stats['call_count'] == 0

    def test_zero_overhead_when_inactive(self):
        """Verify minimal overhead when tracing is not active."""
        @trace
        def simple_func(x):
            return x * 2

        def untraced_func(x):
            return x * 2

        # Warm up
        for _ in range(100):
            simple_func(5)
            untraced_func(5)

        # Time traced function (without active context)
        start = time.perf_counter()
        for _ in range(10000):
            simple_func(5)
        traced_time = time.perf_counter() - start

        # Time untraced function
        start = time.perf_counter()
        for _ in range(10000):
            untraced_func(5)
        untraced_time = time.perf_counter() - start

        # Traced should be no more than 5x slower when inactive
        # (accounting for the single attribute check)
        assert traced_time < untraced_time * 5


class TestNestedCalls:
    """Tests for nested/recursive call tracking."""

    def test_nested_calls_track_parent(self, db_path):
        """Verify nested calls correctly track parent_call_id."""
        @trace
        def outer():
            return inner()

        @trace
        def inner():
            return 42

        with trace_run(db_path=db_path) as run_id:
            result = outer()

        assert result == 42

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 2

        # Find outer and inner calls
        outer_call = next(c for c in calls if 'outer' in c['function_name'])
        inner_call = next(c for c in calls if 'inner' in c['function_name'])

        # Inner should have outer as parent
        assert inner_call['parent_call_id'] == outer_call['call_id']
        assert outer_call['parent_call_id'] is None

        # Depth should be correct
        assert outer_call['depth'] == 0
        assert inner_call['depth'] == 1

    def test_deeply_nested_calls(self, db_path):
        """Verify deeply nested calls are tracked correctly."""
        @trace
        def level(n):
            if n <= 0:
                return 0
            return level(n - 1) + 1

        with trace_run(db_path=db_path) as run_id:
            result = level(5)

        assert result == 5

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 6  # levels 5, 4, 3, 2, 1, 0

        # Verify depth increases
        depths = [c['depth'] for c in calls]
        assert depths == [0, 1, 2, 3, 4, 5]

    def test_sibling_calls(self, db_path):
        """Verify sibling calls at the same level work correctly."""
        @trace
        def parent():
            child_a()
            child_b()

        @trace
        def child_a():
            return "A"

        @trace
        def child_b():
            return "B"

        with trace_run(db_path=db_path) as run_id:
            parent()

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 3

        parent_call = next(c for c in calls if 'parent' in c['function_name'])
        child_a_call = next(c for c in calls if 'child_a' in c['function_name'])
        child_b_call = next(c for c in calls if 'child_b' in c['function_name'])

        # Both children should have parent as their parent
        assert child_a_call['parent_call_id'] == parent_call['call_id']
        assert child_b_call['parent_call_id'] == parent_call['call_id']

        # Both children at depth 1
        assert child_a_call['depth'] == 1
        assert child_b_call['depth'] == 1


class TestExceptionCapture:
    """Tests for exception capturing with tracebacks."""

    def test_exception_captured(self, db_path):
        """Verify exceptions are captured with full details."""
        @trace
        def failing_func():
            raise ValueError("Something went wrong")

        with pytest.raises(ValueError):
            with trace_run(db_path=db_path) as run_id:
                failing_func()

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 1
        call = calls[0]

        assert call['exception_type'] == 'ValueError'
        assert call['exception_message'] == 'Something went wrong'
        assert call['exception_traceback'] is not None
        assert 'Traceback' in call['exception_traceback']
        assert 'ValueError' in call['exception_traceback']

    def test_exception_in_nested_call(self, db_path):
        """Verify exception in nested call is captured correctly."""
        @trace
        def outer():
            return inner()

        @trace
        def inner():
            raise RuntimeError("Inner error")

        with pytest.raises(RuntimeError):
            with trace_run(db_path=db_path) as run_id:
                outer()

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        # Both calls should be recorded
        assert len(calls) == 2

        outer_call = next(c for c in calls if 'outer' in c['function_name'])
        inner_call = next(c for c in calls if 'inner' in c['function_name'])

        # Inner has the exception
        assert inner_call['exception_type'] == 'RuntimeError'

        # Outer doesn't have its own exception recorded (it re-raises)
        # Note: depending on implementation, outer might also show the exception
        # The important thing is inner definitely has it
        assert 'RuntimeError' in inner_call['exception_traceback']

    def test_exception_preserves_traceback(self, db_path):
        """Verify the original exception traceback is preserved for debugging."""
        @trace
        def level_3():
            raise KeyError("missing key")

        @trace
        def level_2():
            return level_3()

        @trace
        def level_1():
            return level_2()

        try:
            with trace_run(db_path=db_path) as run_id:
                level_1()
        except KeyError:
            pass

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        # Find the call that raised the exception
        level_3_call = next(c for c in calls if 'level_3' in c['function_name'])

        # Verify traceback contains the function where exception was raised
        # and includes the exception type/message
        tb = level_3_call['exception_traceback']
        assert 'level_3' in tb
        assert 'KeyError' in tb
        assert 'missing key' in tb
        assert 'Traceback' in tb


class TestNonSerializableObjects:
    """Tests for handling non-serializable objects."""

    def test_non_serializable_args_dont_crash(self, db_path):
        """Verify non-serializable arguments don't cause crashes."""
        @trace
        def func_with_complex_args(lock, file_obj):
            return "done"

        lock = threading.Lock()

        with tempfile.NamedTemporaryFile() as f:
            with trace_run(db_path=db_path) as run_id:
                result = func_with_complex_args(lock, f)

        assert result == "done"

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 1
        # Args should be serialized somehow (even if just as repr)
        assert calls[0]['args'] is not None

    def test_lambda_as_argument(self, db_path):
        """Verify lambda functions as arguments are handled."""
        @trace
        def apply_func(fn, x):
            return fn(x)

        with trace_run(db_path=db_path) as run_id:
            result = apply_func(lambda x: x * 2, 5)

        assert result == 10

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 1
        # Lambda should be serialized as <function>
        assert '<function' in str(calls[0]['args'])

    def test_circular_reference(self, db_path):
        """Verify objects with circular references don't crash."""
        @trace
        def process_circular(obj):
            return "processed"

        # Create circular reference
        circular = {'a': 1}
        circular['self'] = circular

        with trace_run(db_path=db_path) as run_id:
            result = process_circular(circular)

        assert result == "processed"

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        # Should not crash, args should be serialized
        assert len(calls) == 1

    def test_custom_class_without_repr(self, db_path):
        """Verify custom classes without __repr__ are handled."""
        class NoReprClass:
            def __init__(self):
                self.value = 42

        @trace
        def use_no_repr(obj):
            return obj.value

        obj = NoReprClass()

        with trace_run(db_path=db_path) as run_id:
            result = use_no_repr(obj)

        assert result == 42

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 1


class TestTraceRun:
    """Tests for the trace_run context manager."""

    def test_run_creates_record(self, db_path):
        """Verify trace_run creates a run record."""
        with trace_run(command="test command", db_path=db_path) as run_id:
            pass

        store = CodeStore(db_path)
        run = store.get_trace_run(run_id)
        store.close()

        assert run is not None
        assert run['command'] == "test command"
        assert run['status'] == 'completed'
        assert run['exit_code'] == 0

    def test_run_failed_on_exception(self, db_path):
        """Verify run status is 'failed' when exception occurs."""
        with pytest.raises(ValueError):
            with trace_run(db_path=db_path) as run_id:
                raise ValueError("test error")

        store = CodeStore(db_path)
        run = store.get_trace_run(run_id)
        store.close()

        assert run['status'] == 'failed'
        assert run['exit_code'] == 1

    def test_run_records_ended_at(self, db_path):
        """Verify run has ended_at timestamp."""
        with trace_run(db_path=db_path) as run_id:
            time.sleep(0.01)

        store = CodeStore(db_path)
        run = store.get_trace_run(run_id)
        store.close()

        assert run['started_at'] is not None
        assert run['ended_at'] is not None
        assert run['started_at'] < run['ended_at']


class TestTraceModule:
    """Tests for trace_module function."""

    def test_trace_module_instruments_functions(self, db_path):
        """Verify trace_module instruments all public functions."""
        # Create a test module
        test_module = ModuleType('test_module')
        test_module.public_func = lambda x: x * 2
        test_module._private_func = lambda x: x * 3

        trace_module(test_module)

        assert is_traced(test_module.public_func)
        assert not is_traced(test_module._private_func)

    def test_traced_module_functions_record(self, db_path):
        """Verify instrumented module functions actually record traces."""
        # Create a test module
        test_module = ModuleType('test_module')

        def multiply(a, b):
            return a * b

        test_module.multiply = multiply

        trace_module(test_module)

        with trace_run(db_path=db_path) as run_id:
            result = test_module.multiply(3, 4)

        assert result == 12

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 1


class TestTraceClass:
    """Tests for trace_class decorator."""

    def test_trace_class_instruments_methods(self, db_path):
        """Verify trace_class instruments all public methods."""
        @trace_class
        class MyClass:
            def public_method(self):
                return 1

            def _private_method(self):
                return 2

        obj = MyClass()

        assert is_traced(MyClass.public_method)
        assert not is_traced(MyClass._private_method)

    def test_traced_class_methods_record(self, db_path):
        """Verify instrumented class methods actually record traces."""
        @trace_class
        class Calculator:
            def add(self, a, b):
                return a + b

            def multiply(self, a, b):
                return a * b

        calc = Calculator()

        with trace_run(db_path=db_path) as run_id:
            sum_result = calc.add(1, 2)
            prod_result = calc.multiply(3, 4)

        assert sum_result == 3
        assert prod_result == 12

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 2
        function_names = [c['function_name'] for c in calls]
        assert any('add' in name for name in function_names)
        assert any('multiply' in name for name in function_names)

    def test_trace_class_handles_staticmethod(self, db_path):
        """Verify trace_class handles static methods."""
        @trace_class
        class WithStatic:
            @staticmethod
            def static_method(x):
                return x * 2

        with trace_run(db_path=db_path) as run_id:
            result = WithStatic.static_method(5)

        assert result == 10

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 1

    def test_trace_class_handles_classmethod(self, db_path):
        """Verify trace_class handles class methods."""
        @trace_class
        class WithClassMethod:
            value = 10

            @classmethod
            def class_method(cls):
                return cls.value

        with trace_run(db_path=db_path) as run_id:
            result = WithClassMethod.class_method()

        assert result == 10

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 1


class TestThreadSafety:
    """Tests for thread safety of tracing."""

    def test_independent_thread_contexts(self, db_path):
        """Verify each thread has independent trace context."""
        results = []
        errors = []

        @trace
        def thread_func(thread_id):
            time.sleep(0.01)  # Small delay to interleave threads
            return f"thread_{thread_id}"

        def thread_work(thread_id, db_path):
            try:
                with trace_run(command=f"thread_{thread_id}", db_path=db_path) as run_id:
                    result = thread_func(thread_id)
                    results.append((thread_id, run_id, result))
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(3):
            t = threading.Thread(target=thread_work, args=(i, db_path))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 3

        # Each thread should have its own run
        run_ids = set(r[1] for r in results)
        assert len(run_ids) == 3


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_is_traced(self):
        """Verify is_traced correctly identifies traced functions."""
        def normal_func():
            pass

        @trace
        def traced_func():
            pass

        assert not is_traced(normal_func)
        assert is_traced(traced_func)

    def test_get_original(self):
        """Verify get_original returns the unwrapped function."""
        def original():
            return 42

        traced = trace(original)

        assert get_original(traced) is original
        assert get_original(original) is original  # Idempotent


class TestDuration:
    """Tests for duration tracking."""

    def test_duration_captured(self, db_path):
        """Verify duration is captured for function calls."""
        @trace
        def slow_func():
            time.sleep(0.05)
            return "done"

        with trace_run(db_path=db_path) as run_id:
            slow_func()

        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
        store.close()

        assert len(calls) == 1
        duration = calls[0]['duration_ms']

        # Should be at least 50ms (we slept 50ms)
        assert duration >= 50
        # But not crazy long
        assert duration < 500
