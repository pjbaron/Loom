"""Runtime tracing instrumentation for Loom.

Provides decorators and context managers to capture function execution traces
and store them in the Loom database for debugging based on facts, not guesses.

Usage:
    from tracer import trace, trace_run, trace_module, trace_class

    @trace
    def my_function(x, y):
        return x + y

    with trace_run(command="my_script.py") as run_id:
        result = my_function(1, 2)
        # All traced functions are recorded to .loom/store.db
"""

from functools import wraps
from contextlib import contextmanager
import threading
import time
import traceback
import inspect
from datetime import datetime
from typing import Any, Callable, Optional, TypeVar, Set
import os

# Lazy import to avoid circular dependencies
_codestore = None


def _get_codestore():
    """Lazy load CodeStore to avoid import cycles."""
    global _codestore
    if _codestore is None:
        from codestore import CodeStore
        _codestore = CodeStore
    return _codestore


# Thread-local storage for current run and call stack
_trace_context = threading.local()

# Set of function IDs that are part of the tracer itself (to avoid infinite recursion)
_tracer_functions: Set[int] = set()

# Maximum depth to prevent runaway recursion
MAX_TRACE_DEPTH = 100

F = TypeVar('F', bound=Callable[..., Any])


def _is_tracing_active() -> bool:
    """Check if tracing is currently active in this thread."""
    return getattr(_trace_context, 'run_id', None) is not None


def _get_current_context() -> tuple:
    """Get (run_id, parent_call_id, depth, store) from thread-local context."""
    return (
        getattr(_trace_context, 'run_id', None),
        getattr(_trace_context, 'call_stack', [])[-1] if getattr(_trace_context, 'call_stack', []) else None,
        len(getattr(_trace_context, 'call_stack', [])),
        getattr(_trace_context, 'store', None),
    )


def _get_function_info(func: Callable) -> tuple:
    """Extract function name, file path, and line number from a function."""
    # Get the fully qualified name
    module = getattr(func, '__module__', None) or ''
    qualname = getattr(func, '__qualname__', None) or getattr(func, '__name__', 'unknown')

    if module:
        function_name = f"{module}.{qualname}"
    else:
        function_name = qualname

    # Get source file and line number
    try:
        file_path = inspect.getfile(func)
        # Make path relative if possible
        try:
            file_path = os.path.relpath(file_path)
        except ValueError:
            pass  # Different drives on Windows
    except (TypeError, OSError):
        file_path = None

    try:
        _, line_number = inspect.getsourcelines(func)
    except (TypeError, OSError):
        line_number = None

    return function_name, file_path, line_number


def _safe_repr(obj: Any, max_len: int = 200) -> str:
    """Safely get a string representation of an object."""
    try:
        r = repr(obj)
        if len(r) > max_len:
            return r[:max_len] + "..."
        return r
    except Exception:
        return f"<{type(obj).__name__}>"


def trace(func: F) -> F:
    """Decorator to trace function execution.

    When tracing is active (inside a trace_run context), records:
    - Function name, file, line number
    - Arguments and keyword arguments
    - Return value or exception
    - Execution duration
    - Call parent/depth for nested calls

    When tracing is NOT active, the function executes with zero overhead
    (just a single attribute check per call).

    Args:
        func: The function to trace

    Returns:
        Wrapped function that records trace data when tracing is active
    """
    # Mark this wrapper as a tracer function to avoid tracing ourselves
    _tracer_functions.add(id(trace))

    # Pre-compute function info at decoration time (not call time)
    function_name, file_path, line_number = _get_function_info(func)

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Fast path: if no active trace run, just execute
        # This is the "zero overhead when tracing is not active" requirement
        if not getattr(_trace_context, 'run_id', None):
            return func(*args, **kwargs)

        # Get context
        run_id = _trace_context.run_id
        store = _trace_context.store
        call_stack = getattr(_trace_context, 'call_stack', [])

        # Check depth to prevent runaway recursion
        depth = len(call_stack)
        if depth >= MAX_TRACE_DEPTH:
            return func(*args, **kwargs)

        parent_call_id = call_stack[-1] if call_stack else None

        # Record call start
        called_at = datetime.utcnow().isoformat()
        start_time = time.perf_counter()

        # Record the call entry (we'll update with result/exception later)
        call_id = store.record_call(
            run_id=run_id,
            function_name=function_name,
            file_path=file_path,
            line_number=line_number,
            called_at=called_at,
            args=args,
            kwargs=kwargs,
            parent_call_id=parent_call_id,
            depth=depth
        )

        # Push this call onto the stack
        call_stack.append(call_id)
        _trace_context.call_stack = call_stack

        try:
            # Execute the actual function
            result = func(*args, **kwargs)

            # Record success
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000
            returned_at = datetime.utcnow().isoformat()

            # Update the call record with return value and timing
            store.conn.execute(
                """UPDATE trace_calls
                   SET returned_at = ?, duration_ms = ?, return_value_json = ?
                   WHERE call_id = ?""",
                (returned_at, duration_ms, store._safe_serialize(result), call_id)
            )
            store.conn.commit()

            return result

        except BaseException as e:
            # Record exception
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000
            returned_at = datetime.utcnow().isoformat()

            # Get full traceback
            tb = traceback.format_exc()

            # Update the call record with exception info
            store.conn.execute(
                """UPDATE trace_calls
                   SET returned_at = ?, duration_ms = ?,
                       exception_type = ?, exception_message = ?, exception_traceback = ?
                   WHERE call_id = ?""",
                (returned_at, duration_ms, type(e).__name__, str(e), tb, call_id)
            )
            store.conn.commit()

            # Re-raise the exception
            raise

        finally:
            # Pop this call from the stack
            if call_stack and call_stack[-1] == call_id:
                call_stack.pop()
                _trace_context.call_stack = call_stack

    # Mark the wrapper so we can identify traced functions
    wrapper._is_traced = True
    wrapper._original_func = func

    return wrapper  # type: ignore


@contextmanager
def trace_run(command: Optional[str] = None, db_path: str = '.loom/store.db'):
    """Context manager for a trace run.

    Creates a trace run record in the database and sets up thread-local
    context for the @trace decorator to record function calls.

    Args:
        command: Optional description of what is being executed
        db_path: Path to the Loom database (default: .loom/store.db)

    Yields:
        run_id: The UUID of the trace run

    Example:
        with trace_run(command="process_data.py") as run_id:
            process_data()
            # All @trace decorated functions called here are recorded

        # After the context exits, query the trace:
        store = CodeStore(db_path)
        calls = store.get_calls_for_run(run_id)
    """
    CodeStore = _get_codestore()

    # Create the store connection
    store = CodeStore(db_path)

    # Start the trace run
    run_id = store.start_trace_run(command=command)

    # Set up thread-local context
    _trace_context.run_id = run_id
    _trace_context.store = store
    _trace_context.call_stack = []

    status = 'completed'
    exit_code = 0

    try:
        yield run_id
    except SystemExit as e:
        status = 'completed' if e.code == 0 else 'failed'
        exit_code = e.code if isinstance(e.code, int) else 1
        raise
    except KeyboardInterrupt:
        status = 'crashed'
        exit_code = 130
        raise
    except BaseException:
        status = 'failed'
        exit_code = 1
        raise
    finally:
        # Clean up thread-local context
        _trace_context.run_id = None
        _trace_context.store = None
        _trace_context.call_stack = []

        # End the trace run
        store.end_trace_run(run_id, status=status, exit_code=exit_code)
        store.close()


def trace_module(module) -> None:
    """Instrument all functions in a module.

    Replaces all public functions in the module with traced versions.
    Private functions (starting with _) are not traced.

    Args:
        module: The module object to instrument

    Example:
        import my_module
        from tracer import trace_module

        trace_module(my_module)
        # Now all functions in my_module will be traced
    """
    for name in dir(module):
        # Skip private/magic names
        if name.startswith('_'):
            continue

        obj = getattr(module, name)

        # Skip if already traced
        if getattr(obj, '_is_traced', False):
            continue

        # Skip if it's a tracer function
        if id(obj) in _tracer_functions:
            continue

        # Trace functions
        if callable(obj) and not isinstance(obj, type):
            try:
                setattr(module, name, trace(obj))
            except (TypeError, AttributeError):
                # Some objects can't be replaced
                pass


def trace_class(cls: type) -> type:
    """Instrument all methods in a class.

    Returns a new class with all methods wrapped with tracing.
    Works with instance methods, class methods, and static methods.
    Private methods (starting with _) are not traced.

    Args:
        cls: The class to instrument

    Returns:
        The instrumented class (same object, modified in place)

    Example:
        @trace_class
        class MyClass:
            def method(self, x):
                return x * 2

        # Or after the fact:
        trace_class(ExistingClass)
    """
    for name, method in inspect.getmembers(cls):
        # Skip private/magic methods
        if name.startswith('_'):
            continue

        # Skip if already traced
        if getattr(method, '_is_traced', False):
            continue

        # Skip if it's a tracer function
        if id(method) in _tracer_functions:
            continue

        # Handle different method types
        if isinstance(inspect.getattr_static(cls, name), staticmethod):
            # Static method
            try:
                setattr(cls, name, staticmethod(trace(method)))
            except (TypeError, AttributeError):
                pass
        elif isinstance(inspect.getattr_static(cls, name), classmethod):
            # Class method - get the underlying function
            try:
                underlying = method.__func__
                setattr(cls, name, classmethod(trace(underlying)))
            except (TypeError, AttributeError):
                pass
        elif callable(method) and not isinstance(method, type):
            # Regular instance method
            try:
                setattr(cls, name, trace(method))
            except (TypeError, AttributeError):
                pass

    return cls


# Convenience function to check if a function is traced
def is_traced(func: Callable) -> bool:
    """Check if a function is decorated with @trace."""
    return getattr(func, '_is_traced', False)


# Convenience function to get the original untraced function
def get_original(func: Callable) -> Callable:
    """Get the original untraced function from a traced wrapper."""
    return getattr(func, '_original_func', func)
