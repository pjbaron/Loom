"""Pytest plugin for automatic Loom tracing with optimized performance.

Enables automatic function tracing during test execution without requiring
@trace decorators. Uses sys.settrace for zero-configuration instrumentation.

Usage:
    pytest --loom-trace tests/              # Full tracing (default)
    pytest --loom-trace --loom-mode=fail tests/  # Only persist on failure
    ./loom test tests/                      # Single command with smart defaults

Performance optimizations:
- Buffered writes: Accumulate calls in memory, flush in batches
- Selective tracing: Skip stdlib, site-packages, test framework, loom internals
- Lazy serialization: Keep references until flush time
- Failure-focused mode: Only persist traces when tests fail (<1.5x overhead)

Target: <1.5x overhead for passing tests, full trace on failures.
"""

import pytest
import sys
import os
import time
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
import uuid

# Lazy import to work both as plugin and standalone
_codestore_class = None


def _get_codestore():
    """Lazy load CodeStore to avoid import issues."""
    global _codestore_class
    if _codestore_class is None:
        from codestore import CodeStore
        _codestore_class = CodeStore
    return _codestore_class


class LazyCallRecord:
    """Lazy call record that delays serialization until flush time.

    Keeps references to args/return values instead of serializing immediately.
    This reduces overhead during tracing since most calls never get persisted
    in failure-focused mode.
    """
    __slots__ = (
        'call_id', 'run_id', 'function_name', 'file_path', 'line_number',
        'called_at', 'returned_at', 'duration_ms', 'parent_call_id', 'depth',
        '_args_ref', '_kwargs_ref', '_return_ref',
        'exception_type', 'exception_message', 'exception_traceback',
        '_start_time', '_test_name', '_serialized'
    )

    def __init__(self):
        self.call_id = None
        self.run_id = None
        self.function_name = None
        self.file_path = None
        self.line_number = None
        self.called_at = None
        self.returned_at = None
        self.duration_ms = None
        self.parent_call_id = None
        self.depth = 0
        self._args_ref = None
        self._kwargs_ref = None
        self._return_ref = None
        self.exception_type = None
        self.exception_message = None
        self.exception_traceback = None
        self._start_time = None
        self._test_name = None
        self._serialized = False

    def serialize_for_db(self, max_len: int = 100) -> tuple:
        """Serialize the record for database insertion."""
        import json

        args_json = None
        kwargs_json = None
        return_json = None

        # Serialize args only if we have them
        if self._args_ref is not None:
            try:
                args_json = json.dumps(_safe_repr_dict(self._args_ref, max_len))
            except Exception:
                args_json = None

        if self._kwargs_ref is not None:
            try:
                kwargs_json = json.dumps(_safe_repr_dict(self._kwargs_ref, max_len))
            except Exception:
                kwargs_json = None

        if self._return_ref is not None:
            try:
                ret_repr = repr(self._return_ref)
                if len(ret_repr) > 200:
                    ret_repr = ret_repr[:200] + '...'
                return_json = json.dumps(ret_repr)
            except Exception:
                return_json = None

        self._serialized = True

        return (
            self.call_id, self.run_id, self.function_name,
            self.file_path, self.line_number, self.called_at,
            self.returned_at, self.duration_ms, args_json,
            kwargs_json, return_json,
            self.exception_type, self.exception_message,
            self.exception_traceback, self.parent_call_id, self.depth
        )


def _safe_repr_dict(obj: dict, max_len: int = 100) -> dict:
    """Convert dict values to safe repr strings."""
    result = {}
    for k, v in obj.items():
        try:
            v_repr = repr(v)
            if len(v_repr) > max_len:
                v_repr = v_repr[:max_len] + '...'
            result[k] = v_repr
        except Exception:
            result[k] = f'<{type(v).__name__}>'
    return result


class LoomTracePlugin:
    """Pytest plugin for automatic function tracing with optimized performance."""

    # System paths to exclude - checked against sys.prefix at runtime
    STDLIB_PREFIXES: Tuple[str, ...] = ()  # Populated in __init__

    # Patterns to exclude (substring match)
    EXCLUDE_PATTERNS = frozenset({
        'site-packages',
        'dist-packages',
        '__pycache__',
        '.pytest_cache',
        '<frozen',
        '<string>',
        '<stdin>',
        # Loom infrastructure - must not trace itself
        'loom_pytest_plugin.py',
        'codestore.py',
        'tracer.py',
        'loom_tools.py',
        # Test framework internals
        '_pytest',
        'pytest',
        'pluggy',
        '_pytest/',
        'pluggy/',
    })

    # File extensions to trace
    TRACE_EXTENSIONS = frozenset({'.py'})

    # Buffer size before flushing to DB
    BUFFER_SIZE = 100

    # Maximum call stack depth
    MAX_DEPTH = 50

    # Tracing modes
    MODE_FULL = 'full'      # Always persist all traces
    MODE_FAIL = 'fail'      # Only persist when test fails

    def __init__(self, db_path: str = '.loom/store.db', project_root: str = None,
                 mode: str = 'full'):
        """Initialize the plugin.

        Args:
            db_path: Path to the Loom database
            project_root: Root directory of the project (for filtering)
            mode: 'full' or 'fail' - controls when traces are persisted
        """
        self.db_path = db_path
        self.project_root = project_root or os.getcwd()
        self.project_root = os.path.abspath(self.project_root)
        self.mode = mode

        # Build stdlib prefixes for fast exclusion
        self.STDLIB_PREFIXES = self._build_stdlib_prefixes()

        # Ensure .loom directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        CodeStore = _get_codestore()
        self.cs = CodeStore(db_path)

        # Tracing state
        self.run_id: Optional[str] = None
        self.call_stack: List[LazyCallRecord] = []
        self.trace_buffer: List[LazyCallRecord] = []
        self.current_test: Optional[str] = None

        # Per-test buffer for failure-focused mode
        self.test_buffer: List[LazyCallRecord] = []
        self.test_had_failure = False

        # Performance tracking
        self.trace_overhead_ms = 0.0
        self.calls_traced = 0
        self.calls_persisted = 0

        # Thread safety
        self._lock = threading.Lock()
        self._local = threading.local()

        # Cache for file filtering decisions - use dict for speed
        self._file_filter_cache: Dict[str, bool] = {}

        # Pre-compute project root for fast comparison
        self._project_root_len = len(self.project_root)

        # Track failed tests for trace summaries
        self.failed_tests: Dict[str, List[Dict]] = {}

    def _build_stdlib_prefixes(self) -> Tuple[str, ...]:
        """Build tuple of stdlib prefixes for fast exclusion."""
        prefixes = []

        # sys.prefix and sys.base_prefix
        if sys.prefix:
            prefixes.append(sys.prefix)
        if sys.base_prefix and sys.base_prefix != sys.prefix:
            prefixes.append(sys.base_prefix)

        # Common virtual env patterns
        for pattern in ('venv', '.venv', 'virtualenv', 'env', '.env'):
            venv_path = os.path.join(self.project_root, pattern)
            if os.path.isdir(venv_path):
                prefixes.append(venv_path)

        # Standard library paths
        for path in sys.path:
            if path and ('lib/python' in path or 'lib64/python' in path):
                prefixes.append(path)

        return tuple(prefixes)

    def _should_trace_file(self, filename: str) -> bool:
        """Check if a file should be traced.

        Uses aggressive caching and fast-path exclusions.
        """
        if not filename:
            return False

        # Check cache first (dict lookup is very fast)
        cached = self._file_filter_cache.get(filename)
        if cached is not None:
            return cached

        result = self._check_file_traceable(filename)
        self._file_filter_cache[filename] = result
        return result

    def _check_file_traceable(self, filename: str) -> bool:
        """Internal check for file traceability (not cached)."""
        # Fast extension check
        if not filename.endswith('.py'):
            return False

        # Fast pattern exclusion
        for pattern in self.EXCLUDE_PATTERNS:
            if pattern in filename:
                return False

        # Fast stdlib exclusion using prefixes
        for prefix in self.STDLIB_PREFIXES:
            if filename.startswith(prefix):
                return False

        # Must be under project root - fast check
        if not filename.startswith(self.project_root):
            try:
                abs_filename = os.path.abspath(filename)
                if not abs_filename.startswith(self.project_root):
                    return False
            except (OSError, ValueError):
                return False

        return True

    def _get_call_context(self) -> Tuple[Optional[str], int]:
        """Get parent call ID and depth from current call stack."""
        if not self.call_stack:
            return None, 0
        parent = self.call_stack[-1]
        return parent.call_id, len(self.call_stack)

    def _trace_func(self, frame, event, arg):
        """sys.settrace callback for function tracing.

        This is the core tracing function. Optimized for minimal overhead.
        """
        # Only trace call and return events
        if event not in ('call', 'return', 'exception'):
            return self._trace_func

        # Fast path: check if file should be traced
        filename = frame.f_code.co_filename
        if not self._should_trace_file(filename):
            return self._trace_func

        # Get function info
        func_name = frame.f_code.co_name

        # Skip internal/magic functions (except __init__)
        if func_name.startswith('_') and func_name != '__init__':
            return self._trace_func

        start_time = time.perf_counter()

        try:
            if event == 'call':
                self._handle_call(func_name, filename, frame)
            elif event == 'return':
                self._handle_return(arg)
            elif event == 'exception':
                self._handle_exception(arg)
        finally:
            self.trace_overhead_ms += (time.perf_counter() - start_time) * 1000

        return self._trace_func

    def _handle_call(self, func_name: str, filename: str, frame):
        """Handle a function call event."""
        if len(self.call_stack) >= self.MAX_DEPTH:
            return

        parent_id, depth = self._get_call_context()

        # Create lazy record - don't serialize yet
        record = LazyCallRecord()
        record.call_id = str(uuid.uuid4())
        record.run_id = self.run_id
        record.function_name = self._get_qualified_name(func_name, frame)
        record.file_path = self._get_relative_path(filename)
        record.line_number = frame.f_code.co_firstlineno
        record.called_at = datetime.utcnow().isoformat()
        record.parent_call_id = parent_id
        record.depth = depth
        record._start_time = time.perf_counter()
        record._test_name = self.current_test

        # Capture args lazily - keep reference, serialize later
        record._args_ref = self._capture_args_lazy(frame)

        self.call_stack.append(record)
        self.calls_traced += 1

    def _get_qualified_name(self, func_name: str, frame) -> str:
        """Get qualified function name (module.class.method)."""
        try:
            if 'self' in frame.f_locals:
                cls = frame.f_locals['self'].__class__
                return f"{cls.__module__}.{cls.__name__}.{func_name}"
            elif 'cls' in frame.f_locals:
                cls = frame.f_locals['cls']
                return f"{cls.__module__}.{cls.__name__}.{func_name}"
            else:
                module = frame.f_globals.get('__name__', '<unknown>')
                return f"{module}.{func_name}"
        except (AttributeError, KeyError):
            return func_name

    def _get_relative_path(self, filename: str) -> str:
        """Get path relative to project root."""
        if filename.startswith(self.project_root):
            return filename[self._project_root_len + 1:]  # +1 for separator
        try:
            return os.path.relpath(filename, self.project_root)
        except ValueError:
            return filename

    def _capture_args_lazy(self, frame, max_args: int = 5) -> Optional[Dict]:
        """Capture function arguments as a dict (no serialization yet)."""
        try:
            code = frame.f_code
            arg_names = code.co_varnames[:code.co_argcount]
            locals_copy = frame.f_locals

            args = {}
            for name in arg_names[:max_args]:
                if name in ('self', 'cls'):
                    continue
                if name in locals_copy:
                    args[name] = locals_copy[name]

            return args if args else None
        except Exception:
            return None

    def _handle_return(self, return_value):
        """Handle a function return event."""
        if not self.call_stack:
            return

        record = self.call_stack.pop()
        end_time = time.perf_counter()

        record.returned_at = datetime.utcnow().isoformat()
        record.duration_ms = (end_time - record._start_time) * 1000

        # Keep reference to return value - serialize later
        record._return_ref = return_value

        self._buffer_call(record)

    def _handle_exception(self, exc_info):
        """Handle an exception event."""
        if not self.call_stack:
            return

        exc_type, exc_value, exc_tb = exc_info

        # Update the current call record with exception info
        record = self.call_stack[-1]
        record.exception_type = exc_type.__name__ if exc_type else None
        record.exception_message = str(exc_value) if exc_value else None

        # Mark test as having a failure for failure-focused mode
        self.test_had_failure = True

        # Only capture traceback for the first exception occurrence
        if not record.exception_traceback:
            try:
                record.exception_traceback = ''.join(
                    traceback.format_exception(exc_type, exc_value, exc_tb)
                )
            except Exception:
                pass

    def _buffer_call(self, record: LazyCallRecord):
        """Add a call record to the buffer, handling mode-specific buffering."""
        with self._lock:
            if self.mode == self.MODE_FAIL:
                # In failure-focused mode, buffer per-test
                self.test_buffer.append(record)
            else:
                # In full mode, buffer and flush when full
                self.trace_buffer.append(record)
                if len(self.trace_buffer) >= self.BUFFER_SIZE:
                    self._flush_buffer_locked()

    def _flush_buffer_locked(self):
        """Flush the buffer to the database (must hold lock)."""
        if not self.trace_buffer:
            return

        try:
            cursor = self.cs.conn.cursor()
            cursor.executemany(
                """
                INSERT INTO trace_calls (
                    call_id, run_id, function_name, file_path, line_number,
                    called_at, returned_at, duration_ms, args_json, kwargs_json,
                    return_value_json, exception_type, exception_message,
                    exception_traceback, parent_call_id, depth
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [record.serialize_for_db() for record in self.trace_buffer]
            )
            self.cs.conn.commit()
            self.calls_persisted += len(self.trace_buffer)
        except Exception as e:
            sys.stderr.write(f"Loom trace buffer flush error: {e}\n")

        self.trace_buffer = []

    def _flush_buffer(self):
        """Flush the buffer to the database (acquires lock)."""
        with self._lock:
            self._flush_buffer_locked()

    def _flush_test_buffer(self, persist: bool):
        """Flush test buffer - persist to DB or discard based on test result."""
        with self._lock:
            if persist and self.test_buffer:
                # Move test buffer to main buffer and flush
                self.trace_buffer.extend(self.test_buffer)
                self._flush_buffer_locked()
            # Clear test buffer regardless
            self.test_buffer = []
            self.test_had_failure = False

    # =========================================================================
    # Pytest hooks
    # =========================================================================

    def pytest_sessionstart(self, session):
        """Called at the start of the test session."""
        # Determine command for trace run name
        cmd_parts = ['pytest']
        if hasattr(session.config, 'args'):
            cmd_parts.extend(session.config.args)
        command = ' '.join(cmd_parts)

        # Start trace run
        self.run_id = self.cs.start_trace_run(command)

        # Print trace info
        mode_str = f" ({self.mode} mode)" if self.mode != self.MODE_FULL else ""
        print(f"\n[Loom] Trace run started: {self.run_id[:8]}...{mode_str}")
        print(f"[Loom] Project root: {self.project_root}")

        # Install trace function
        sys.settrace(self._trace_func)
        threading.settrace(self._trace_func)

    def pytest_sessionfinish(self, session, exitstatus):
        """Called at the end of the test session."""
        # Remove trace function
        sys.settrace(None)
        threading.settrace(None)

        # Flush any remaining buffered calls
        # Also flush any incomplete calls still on stack
        while self.call_stack:
            record = self.call_stack.pop()
            record.returned_at = datetime.utcnow().isoformat()
            record.duration_ms = (
                time.perf_counter() - (record._start_time or time.perf_counter())
            ) * 1000
            self.trace_buffer.append(record)

        self._flush_buffer()

        # End trace run
        status = 'completed' if exitstatus == 0 else 'failed'
        self.cs.end_trace_run(self.run_id, status, exitstatus)

        # Print summary
        print(f"\n[Loom] Trace run completed: {self.run_id[:8]}...")
        print(f"[Loom] Calls traced: {self.calls_traced}, persisted: {self.calls_persisted}")
        print(f"[Loom] Trace overhead: {self.trace_overhead_ms:.1f}ms")
        if self.mode == self.MODE_FAIL:
            saved_pct = 100 * (1 - self.calls_persisted / max(1, self.calls_traced))
            print(f"[Loom] Failure-focused mode saved {saved_pct:.0f}% of writes")
        print(f"[Loom] View trace: ./loom trace show {self.run_id[:8]}")

    def pytest_runtest_setup(self, item):
        """Called before each test runs."""
        self.current_test = item.nodeid
        self.test_had_failure = False
        self.test_buffer = []

    def pytest_runtest_teardown(self, item, nextitem):
        """Called after each test runs."""
        if self.mode == self.MODE_FULL:
            # Full mode: always flush at test boundaries
            self._flush_buffer()
        else:
            # Failure-focused mode: only persist if test failed
            self._flush_test_buffer(persist=self.test_had_failure)

        self.current_test = None

    def pytest_runtest_makereport(self, item, call):
        """Called for each test phase (setup, call, teardown)."""
        if call.excinfo is not None:
            # Test had an exception - mark for persistence
            self.test_had_failure = True

    def pytest_runtest_logreport(self, report):
        """Called for each test phase report."""
        if report.when == 'call' and report.failed:
            # Mark failure and attach trace summary
            self.test_had_failure = True
            self._attach_trace_summary(report)

    def _attach_trace_summary(self, report):
        """Attach trace summary to a failed test report."""
        try:
            # In failure-focused mode, flush test buffer now
            if self.mode == self.MODE_FAIL:
                self._flush_test_buffer(persist=True)
            else:
                self._flush_buffer()

            # Also pop any incomplete calls from the stack
            incomplete_calls = []
            while self.call_stack:
                record = self.call_stack.pop()
                record.returned_at = datetime.utcnow().isoformat()
                record.duration_ms = (
                    time.perf_counter() - (record._start_time or time.perf_counter())
                ) * 1000
                incomplete_calls.append(record)
                self.trace_buffer.append(record)

            if incomplete_calls:
                self._flush_buffer()

            failed_calls = self.cs.get_failed_calls(run_id=self.run_id, limit=20)

            if failed_calls:
                summary_lines = [
                    "",
                    "=" * 60,
                    "[Loom] Traced calls with exceptions:",
                    "-" * 60,
                ]

                for call in failed_calls[-10:]:  # Show last 10
                    func = call.get('function_name', '?')
                    if '.' in func:
                        func = func.rsplit('.', 1)[-1]  # Short name
                    exc_type = call.get('exception_type', '?')
                    exc_msg = call.get('exception_message', '')
                    if len(exc_msg) > 60:
                        exc_msg = exc_msg[:57] + '...'
                    file_path = call.get('file_path', '?')
                    if '/' in file_path:
                        file_path = file_path.rsplit('/', 1)[-1]
                    lineno = call.get('line_number', '?')

                    summary_lines.append(
                        f"  {func}() -> {exc_type}: {exc_msg}"
                    )
                    summary_lines.append(
                        f"    at {file_path}:{lineno}"
                    )

                summary_lines.extend([
                    "-" * 60,
                    f"[Loom] Full trace: ./loom trace show {self.run_id[:8]}",
                    "=" * 60,
                ])

                report.sections.append(
                    ('Loom Trace Summary', '\n'.join(summary_lines))
                )
        except Exception:
            # Don't let trace summary failures affect test reporting
            pass


# =========================================================================
# Pytest plugin registration
# =========================================================================

def pytest_addoption(parser):
    """Add command line options for the plugin."""
    group = parser.getgroup('loom', 'Loom tracing options')
    group.addoption(
        '--loom-trace',
        action='store_true',
        default=False,
        help='Enable Loom automatic tracing during test execution'
    )
    group.addoption(
        '--loom-db',
        action='store',
        default='.loom/store.db',
        help='Path to Loom database (default: .loom/store.db)'
    )
    group.addoption(
        '--loom-root',
        action='store',
        default=None,
        help='Project root for filtering traced files (default: current directory)'
    )
    group.addoption(
        '--loom-mode',
        action='store',
        default='full',
        choices=['full', 'fail'],
        help='Tracing mode: full (always persist) or fail (only on failure)'
    )


def pytest_configure(config):
    """Configure the plugin based on command line options."""
    if config.getoption('--loom-trace', default=False):
        db_path = config.getoption('--loom-db', default='.loom/store.db')
        project_root = config.getoption('--loom-root', default=None)
        mode = config.getoption('--loom-mode', default='full')

        plugin = LoomTracePlugin(db_path=db_path, project_root=project_root, mode=mode)
        config.pluginmanager.register(plugin, 'loom_trace')


# =========================================================================
# Standalone usage for subprocess tracing
# =========================================================================

_standalone_plugin: Optional[LoomTracePlugin] = None


def enable_tracing(db_path: str = '.loom/store.db', project_root: str = None,
                   mode: str = 'full'):
    """Enable tracing for standalone (non-pytest) usage.

    This can be used to trace code in subprocesses:

        import loom_pytest_plugin
        loom_pytest_plugin.enable_tracing()

        # Your code here - all calls will be traced

        loom_pytest_plugin.disable_tracing()
    """
    global _standalone_plugin

    if _standalone_plugin is not None:
        return _standalone_plugin.run_id

    _standalone_plugin = LoomTracePlugin(db_path=db_path, project_root=project_root, mode=mode)
    _standalone_plugin.run_id = _standalone_plugin.cs.start_trace_run(
        f"standalone: {' '.join(sys.argv)}"
    )

    sys.settrace(_standalone_plugin._trace_func)
    threading.settrace(_standalone_plugin._trace_func)

    return _standalone_plugin.run_id


def disable_tracing(status: str = 'completed', exit_code: int = 0):
    """Disable tracing and finalize the trace run."""
    global _standalone_plugin

    if _standalone_plugin is None:
        return

    sys.settrace(None)
    threading.settrace(None)

    _standalone_plugin._flush_buffer()
    _standalone_plugin.cs.end_trace_run(
        _standalone_plugin.run_id, status, exit_code
    )

    run_id = _standalone_plugin.run_id
    _standalone_plugin = None

    return run_id


# For use with atexit
def _cleanup():
    """Clean up tracing on process exit."""
    if _standalone_plugin is not None:
        disable_tracing(status='crashed', exit_code=1)


import atexit
atexit.register(_cleanup)
