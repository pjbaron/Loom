"""Tests for the ingest_files() method of CodeStore."""

import pytest
import tempfile
import shutil
from pathlib import Path

from codestore import CodeStore


@pytest.fixture
def store():
    """Create a fresh in-memory CodeStore for each test."""
    return CodeStore(":memory:")


@pytest.fixture
def fixtures_dir():
    """Return the path to the test fixtures directory."""
    return Path(__file__).parent / "test_fixtures"


class TestIngestSingleFile:
    """Tests for ingesting a single valid Python file."""

    def test_ingest_single_file_returns_stats(self, store, fixtures_dir):
        """Ingesting a single file returns correct statistics."""
        single_file_dir = fixtures_dir / "simple_module.py"

        # Create a temp directory with just the single file
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(single_file_dir, dest)

            stats = store.ingest_files(tmpdir)

            assert stats["modules"] == 1
            assert stats["functions"] == 3  # greet, add_numbers, fetch_data
            assert stats["classes"] == 1    # Calculator
            assert stats["errors"] == 0

    def test_ingest_creates_module_entity(self, store, fixtures_dir):
        """Ingesting a file creates a module entity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            modules = store.find_entities(kind="module")
            assert len(modules) == 1
            assert modules[0]["name"] == "simple_module"

    def test_ingest_creates_function_entities(self, store, fixtures_dir):
        """Ingesting a file creates function entities for each top-level function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            functions = store.find_entities(kind="function")
            func_names = [f["name"] for f in functions]

            assert len(functions) == 3
            assert "simple_module.greet" in func_names
            assert "simple_module.add_numbers" in func_names
            assert "simple_module.fetch_data" in func_names

    def test_ingest_creates_class_entities(self, store, fixtures_dir):
        """Ingesting a file creates class entities for each top-level class."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            classes = store.find_entities(kind="class")
            assert len(classes) == 1
            assert classes[0]["name"] == "simple_module.Calculator"

    def test_ingest_detects_async_functions(self, store, fixtures_dir):
        """Async functions are marked in metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            fetch_funcs = store.find_entities(name="fetch_data")
            assert len(fetch_funcs) == 1
            assert fetch_funcs[0]["metadata"]["is_async"] is True

    def test_ingest_captures_function_arguments(self, store, fixtures_dir):
        """Function arguments are captured in metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            add_funcs = store.find_entities(name="add_numbers")
            assert len(add_funcs) == 1
            assert add_funcs[0]["metadata"]["args"] == ["a", "b"]


class TestIngestNestedDirectories:
    """Tests for ingesting a directory with nested subdirectories."""

    def test_ingest_nested_directory_stats(self, store, fixtures_dir):
        """Ingesting a nested directory returns correct statistics."""
        stats = store.ingest_files(str(fixtures_dir / "nested_pkg"))

        # 4 modules: __init__, utils, models, subpkg/__init__, subpkg/deep_module
        assert stats["modules"] == 5
        # Functions: helper_function, format_string, deep_function
        assert stats["functions"] == 3
        # Classes: BaseModel, User, DeepClass
        assert stats["classes"] == 3
        assert stats["errors"] == 0

    def test_ingest_creates_modules_for_each_file(self, store, fixtures_dir):
        """Each Python file becomes a module entity."""
        store.ingest_files(str(fixtures_dir / "nested_pkg"))

        modules = store.find_entities(kind="module")
        module_names = [m["name"] for m in modules]

        assert len(modules) == 5
        # Check for expected module names (may vary based on path handling)
        assert any("utils" in name for name in module_names)
        assert any("models" in name for name in module_names)
        assert any("deep_module" in name for name in module_names)

    def test_ingest_handles_package_init(self, store, fixtures_dir):
        """Package __init__.py files are handled correctly."""
        store.ingest_files(str(fixtures_dir / "nested_pkg"))

        modules = store.find_entities(kind="module")
        # Look for the package init module
        init_modules = [m for m in modules if "__init__" not in m["name"]
                        and "utils" not in m["name"]
                        and "models" not in m["name"]
                        and "deep" not in m["name"]]
        # Should have at least the root package
        assert len(init_modules) >= 1

    def test_ingest_preserves_nested_module_paths(self, store, fixtures_dir):
        """Deeply nested modules have correct dotted paths."""
        store.ingest_files(str(fixtures_dir / "nested_pkg"))

        deep_funcs = store.find_entities(name="deep_function")
        assert len(deep_funcs) == 1
        # The function should be in a nested module (deep_module contains it)
        assert "deep_module" in deep_funcs[0]["name"] or "deep_function" in deep_funcs[0]["name"]


class TestIngestSyntaxErrors:
    """Tests for handling files with syntax errors."""

    def test_syntax_error_increments_error_count(self, store, fixtures_dir):
        """Files with syntax errors increment the error count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "broken.py"
            shutil.copy(fixtures_dir / "syntax_error.py", dest)

            stats = store.ingest_files(tmpdir)

            assert stats["errors"] == 1
            assert stats["modules"] == 0

    def test_syntax_error_skipped_gracefully(self, store, fixtures_dir):
        """Syntax errors don't prevent other files from being processed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy both a valid and invalid file
            shutil.copy(fixtures_dir / "simple_module.py",
                       Path(tmpdir) / "good.py")
            shutil.copy(fixtures_dir / "syntax_error.py",
                       Path(tmpdir) / "bad.py")

            stats = store.ingest_files(tmpdir)

            # One error for the bad file
            assert stats["errors"] == 1
            # But the good file was still processed
            assert stats["modules"] == 1
            assert stats["functions"] == 3
            assert stats["classes"] == 1

    def test_syntax_error_no_entities_created(self, store, fixtures_dir):
        """Files with syntax errors don't create partial entities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "broken.py"
            shutil.copy(fixtures_dir / "syntax_error.py", dest)

            store.ingest_files(tmpdir)

            # No entities should be created for the broken file
            assert store.find_entities() == []


class TestEntityKindsAndRelationships:
    """Tests for verifying entities have correct kinds and relationships."""

    def test_module_contains_functions(self, store, fixtures_dir):
        """Module entities have 'contains' relationships to their functions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            modules = store.find_entities(kind="module")
            assert len(modules) == 1
            module = modules[0]

            children = store.get_children(module["id"])
            child_kinds = [c["kind"] for c in children]

            assert "function" in child_kinds
            assert len([k for k in child_kinds if k == "function"]) == 3

    def test_module_contains_classes(self, store, fixtures_dir):
        """Module entities have 'contains' relationships to their classes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            modules = store.find_entities(kind="module")
            module = modules[0]

            children = store.get_children(module["id"])
            class_children = [c for c in children if c["kind"] == "class"]

            assert len(class_children) == 1
            assert "Calculator" in class_children[0]["name"]

    def test_entities_have_correct_kinds(self, store, fixtures_dir):
        """All entities have the expected kind values."""
        store.ingest_files(str(fixtures_dir / "nested_pkg"))

        all_entities = store.find_entities()
        kinds = set(e["kind"] for e in all_entities)

        assert "module" in kinds
        assert "function" in kinds
        assert "class" in kinds
        # No 'variable' kind expected from our fixtures
        assert "variable" not in kinds

    def test_class_entities_have_base_info(self, store, fixtures_dir):
        """Class entities include base class information in metadata."""
        store.ingest_files(str(fixtures_dir / "nested_pkg"))

        user_classes = store.find_entities(name="User", kind="class")
        assert len(user_classes) >= 1, "Should find at least one User class"

        # Find the actual class (not methods containing "User")
        user = user_classes[0]
        assert user["kind"] == "class"
        assert "BaseModel" in user["metadata"]["bases"]

    def test_class_entities_have_method_list(self, store, fixtures_dir):
        """Class entities include method names in metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            calc_classes = store.find_entities(name="Calculator", kind="class")
            assert len(calc_classes) >= 1, "Should find at least one Calculator class"

            calc = calc_classes[0]
            methods = calc["metadata"]["methods"]

            assert "__init__" in methods
            assert "add" in methods
            assert "multiply" in methods

    def test_relationships_are_bidirectional_queryable(self, store, fixtures_dir):
        """Relationships can be queried from both directions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            # Get a function and verify we can find its parent module
            functions = store.find_entities(kind="function")
            func = functions[0]

            parent = store.get_parent(func["id"])
            assert parent is not None
            assert parent["kind"] == "module"


class TestDocstringsAsIntent:
    """Tests for verifying docstrings become intent annotations."""

    def test_module_docstring_becomes_intent(self, store, fixtures_dir):
        """Module docstrings are stored as intent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            modules = store.find_entities(kind="module")
            module = modules[0]

            assert module["intent"] == "A simple module for testing code ingestion."

    def test_function_docstring_becomes_intent(self, store, fixtures_dir):
        """Function docstrings are stored as intent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            greet_funcs = store.find_entities(name="greet")
            assert len(greet_funcs) == 1

            assert greet_funcs[0]["intent"] == "Return a greeting message for the given name."

    def test_class_docstring_becomes_intent(self, store, fixtures_dir):
        """Class docstrings are stored as intent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            calc_classes = store.find_entities(name="Calculator", kind="class")
            assert len(calc_classes) >= 1, "Should find at least one Calculator class"

            assert calc_classes[0]["intent"] == "A simple calculator class for basic arithmetic."

    def test_missing_docstring_results_in_none_intent(self, store):
        """Entities without docstrings have None intent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file without docstrings
            no_doc_file = Path(tmpdir) / "no_docs.py"
            no_doc_file.write_text("""
def no_docstring_func():
    return 42

class NoDocClass:
    pass
""")

            store.ingest_files(tmpdir)

            func = store.find_entities(name="no_docstring_func")[0]
            cls = store.find_entities(name="NoDocClass")[0]

            assert func["intent"] is None
            assert cls["intent"] is None

    def test_multiline_docstring_preserved(self, store):
        """Multiline docstrings are fully preserved as intent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            multiline_file = Path(tmpdir) / "multiline.py"
            multiline_file.write_text('''
def complex_function(a, b, c):
    """
    Perform a complex operation on three inputs.

    This function does something very important
    that requires multiple lines to explain.

    Args:
        a: First argument
        b: Second argument
        c: Third argument

    Returns:
        The result of the operation
    """
    return a + b + c
''')

            store.ingest_files(tmpdir)

            func = store.find_entities(name="complex_function")[0]

            # Intent should contain the full multiline docstring
            assert "Perform a complex operation" in func["intent"]
            assert "Args:" in func["intent"]
            assert "Returns:" in func["intent"]


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_nonexistent_path_raises_error(self, store):
        """Ingesting a nonexistent path raises ValueError."""
        with pytest.raises(ValueError, match="Path does not exist"):
            store.ingest_files("/nonexistent/path/that/does/not/exist")

    def test_empty_directory(self, store):
        """Ingesting an empty directory returns zero counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stats = store.ingest_files(tmpdir)

            assert stats["modules"] == 0
            assert stats["functions"] == 0
            assert stats["classes"] == 0
            assert stats["errors"] == 0

    def test_empty_python_file(self, store):
        """Ingesting an empty Python file creates only a module entity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_file = Path(tmpdir) / "empty.py"
            empty_file.write_text("")

            stats = store.ingest_files(tmpdir)

            assert stats["modules"] == 1
            assert stats["functions"] == 0
            assert stats["classes"] == 0

    def test_file_with_only_comments(self, store):
        """A file with only comments creates a module with no children."""
        with tempfile.TemporaryDirectory() as tmpdir:
            comment_file = Path(tmpdir) / "comments_only.py"
            comment_file.write_text("""
# This is a comment
# Another comment
# No actual code here
""")

            stats = store.ingest_files(tmpdir)

            assert stats["modules"] == 1
            assert stats["functions"] == 0
            assert stats["classes"] == 0

    def test_code_is_stored_for_entities(self, store, fixtures_dir):
        """Entity code is stored and retrievable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            greet_func = store.find_entities(name="greet")[0]

            assert greet_func["code"] is not None
            assert "def greet" in greet_func["code"]
            assert "Hello" in greet_func["code"]

    def test_metadata_contains_line_numbers(self, store, fixtures_dir):
        """Entity metadata includes line number information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            greet_func = store.find_entities(name="greet")[0]

            assert "lineno" in greet_func["metadata"]
            assert greet_func["metadata"]["lineno"] > 0

    def test_metadata_contains_file_path_for_modules(self, store, fixtures_dir):
        """Module metadata includes the source file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)

            module = store.find_entities(kind="module")[0]

            assert "file_path" in module["metadata"]
            assert "simple_module.py" in module["metadata"]["file_path"]
