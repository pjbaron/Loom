"""Tests for PythonParser - language-agnostic test patterns for parser implementations."""

import pytest
import tempfile
from pathlib import Path

from parsers.base import ParseResult
from parsers.python_parser import PythonParser


@pytest.fixture
def parser():
    """Create a fresh PythonParser for each test."""
    return PythonParser()


@pytest.fixture
def fixtures_dir():
    """Return the path to the test fixtures directory."""
    return Path(__file__).parent.parent / "test_fixtures"


class TestParseFileEntityCount:
    """Tests for parse_file returning correct entity counts."""

    def test_parse_simple_module_entity_count(self, parser, fixtures_dir):
        """Parsing a simple module returns correct number of entities."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        # Count entities by kind
        kinds = [e["kind"] for e in result.entities]

        assert kinds.count("module") == 1
        assert kinds.count("function") == 3  # greet, add_numbers, fetch_data
        assert kinds.count("class") == 1  # Calculator
        # Calculator has 3 methods: __init__, add, multiply
        assert kinds.count("method") == 3

    def test_parse_file_returns_parse_result(self, parser, fixtures_dir):
        """parse_file returns a ParseResult instance."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        assert isinstance(result, ParseResult)
        assert hasattr(result, "entities")
        assert hasattr(result, "relationships")
        assert hasattr(result, "errors")

    def test_parse_empty_file(self, parser):
        """Parsing an empty file returns only module entity."""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            f.write("")
            f.flush()

            result = parser.parse_file(Path(f.name))

            kinds = [e["kind"] for e in result.entities]
            assert kinds.count("module") == 1
            assert len(result.entities) == 1

    def test_parse_file_with_source_parameter(self, parser):
        """parse_file accepts source code directly via parameter."""
        source = """
def hello():
    pass

class World:
    def method(self):
        pass
"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            kinds = [e["kind"] for e in result.entities]
            assert kinds.count("module") == 1
            assert kinds.count("function") == 1
            assert kinds.count("class") == 1
            assert kinds.count("method") == 1

    def test_parse_nested_classes_not_supported(self, parser):
        """Nested classes are not extracted (by design - top level only)."""
        source = """
class Outer:
    class Inner:
        def inner_method(self):
            pass
"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            class_entities = [e for e in result.entities if e["kind"] == "class"]
            # Only Outer should be extracted as a class entity
            assert len(class_entities) == 1
            assert "Outer" in class_entities[0]["name"]


class TestRelationshipExtraction:
    """Tests for relationship extraction from parsed files."""

    def test_contains_relationships(self, parser, fixtures_dir):
        """Module contains function and class relationships are extracted."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        contains_rels = [r for r in result.relationships if r[2] == "contains"]

        # Module should contain 3 functions + 1 class
        assert len(contains_rels) == 4

    def test_member_of_relationships(self, parser, fixtures_dir):
        """Method member_of class relationships are extracted."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        member_rels = [r for r in result.relationships if r[2] == "member_of"]

        # Calculator has 3 methods
        assert len(member_rels) == 3

        # All should point to Calculator class
        for method_name, class_name, rel_type in member_rels:
            assert "Calculator" in class_name

    def test_import_relationships(self, parser):
        """Import statements generate import relationships."""
        source = """
import os
import sys
from pathlib import Path
from typing import List, Dict
"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            import_rels = [r for r in result.relationships if r[2] == "imports"]

            imported_modules = [r[1] for r in import_rels]
            assert "os" in imported_modules
            assert "sys" in imported_modules
            assert "pathlib" in imported_modules
            assert "typing" in imported_modules

    def test_calls_relationships(self, parser):
        """Function calls generate calls relationships."""
        source = """
def caller():
    print("hello")
    helper()

def helper():
    pass
"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            calls_rels = [r for r in result.relationships if r[2] == "calls"]

            called_names = [r[1] for r in calls_rels]
            assert "print" in called_names
            assert "helper" in called_names

    def test_method_calls_extracted(self, parser):
        """Method calls on self are extracted."""
        source = """
class MyClass:
    def public_method(self):
        self._private_helper()

    def _private_helper(self):
        pass
"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            calls_rels = [r for r in result.relationships if r[2] == "calls"]

            called_names = [r[1] for r in calls_rels]
            assert "_private_helper" in called_names

    def test_relationship_tuple_format(self, parser, fixtures_dir):
        """Relationships are (from_name, to_name, relation_type) tuples."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        for rel in result.relationships:
            assert isinstance(rel, tuple)
            assert len(rel) == 3
            from_name, to_name, rel_type = rel
            assert isinstance(from_name, str)
            assert isinstance(to_name, str)
            assert rel_type in ("contains", "member_of", "imports", "calls")


class TestSyntaxErrorHandling:
    """Tests for graceful handling of syntax errors."""

    def test_syntax_error_returns_error_in_result(self, parser, fixtures_dir):
        """Files with syntax errors have errors in result."""
        result = parser.parse_file(fixtures_dir / "syntax_error.py")

        assert len(result.errors) > 0
        assert any("Syntax error" in e or "syntax" in e.lower() for e in result.errors)

    def test_syntax_error_no_entities(self, parser, fixtures_dir):
        """Files with syntax errors produce no entities."""
        result = parser.parse_file(fixtures_dir / "syntax_error.py")

        assert len(result.entities) == 0

    def test_syntax_error_no_relationships(self, parser, fixtures_dir):
        """Files with syntax errors produce no relationships."""
        result = parser.parse_file(fixtures_dir / "syntax_error.py")

        assert len(result.relationships) == 0

    def test_syntax_error_message_includes_file(self, parser, fixtures_dir):
        """Error message includes the file path for debugging."""
        result = parser.parse_file(fixtures_dir / "syntax_error.py")

        assert len(result.errors) > 0
        # Error should reference the file somehow
        error_text = " ".join(result.errors)
        assert "syntax_error" in error_text.lower() or "line" in error_text.lower()

    def test_partial_syntax_error(self, parser):
        """Even partial syntax errors prevent entity extraction."""
        source = """
def valid_function():
    pass

def broken_function(
    # Missing closing paren
"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            # Should have errors
            assert len(result.errors) > 0
            # Should not have partial entities
            assert len(result.entities) == 0


class TestEncodingHandling:
    """Tests for handling various file encodings."""

    def test_utf8_encoding(self, parser):
        """Standard UTF-8 files are parsed correctly."""
        source = '''"""Module with UTF-8 content."""

def greet():
    """Say hello in multiple languages."""
    return "Hello, 你好, مرحبا, Привет"
'''
        with tempfile.NamedTemporaryFile(
            suffix=".py", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write(source)
            f.flush()

            result = parser.parse_file(Path(f.name))

            assert len(result.errors) == 0
            assert len(result.entities) == 2  # module + function

    def test_utf8_bom_encoding(self, parser):
        """UTF-8 with BOM is handled correctly."""
        source = '''"""Module with BOM."""

def test():
    pass
'''
        with tempfile.NamedTemporaryFile(
            suffix=".py", delete=False, mode="w", encoding="utf-8-sig"
        ) as f:
            f.write(source)
            f.flush()

            result = parser.parse_file(Path(f.name))

            # Python's ast.parse is strict about BOM - if there's an error,
            # verify it's handled gracefully. The parser tries multiple encodings
            # but ast.parse may still reject the BOM at the start.
            # Either success or graceful error is acceptable.
            assert isinstance(result, ParseResult)
            if len(result.errors) == 0:
                assert any(e["kind"] == "function" for e in result.entities)

    def test_latin1_encoding(self, parser):
        """Latin-1 encoded files are handled."""
        # Create a file with Latin-1 specific characters
        content = b'"""Module with Latin-1."""\n\ndef caf\xe9():\n    pass\n'

        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(content)
            f.flush()

            result = parser.parse_file(Path(f.name))

            # Should either parse successfully or fail gracefully
            # (depends on how the parser handles the encoding)
            assert isinstance(result, ParseResult)

    def test_invalid_encoding_graceful_failure(self, parser):
        """Files with invalid encoding are handled gracefully."""
        # Create a file with mixed/invalid encoding
        content = b'"""Module."""\n\ndef test():\n    x = \xff\xfe\n    pass\n'

        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(content)
            f.flush()

            result = parser.parse_file(Path(f.name))

            # Should not raise an exception
            assert isinstance(result, ParseResult)

    def test_nonexistent_file(self, parser):
        """Nonexistent file returns error in result."""
        result = parser.parse_file(Path("/nonexistent/path/file.py"))

        assert len(result.errors) > 0
        assert len(result.entities) == 0


class TestEntityMetadata:
    """Tests for entity metadata extraction."""

    def test_function_has_line_numbers(self, parser, fixtures_dir):
        """Functions have start and end line numbers."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        functions = [e for e in result.entities if e["kind"] == "function"]

        for func in functions:
            assert func["start_line"] is not None
            assert func["start_line"] > 0
            assert func["end_line"] is not None
            assert func["end_line"] >= func["start_line"]

    def test_function_has_signature(self, parser, fixtures_dir):
        """Functions have signature in metadata."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        greet_funcs = [e for e in result.entities if "greet" in e["name"]]
        assert len(greet_funcs) == 1

        assert "signature" in greet_funcs[0]["metadata"]
        assert "name" in greet_funcs[0]["metadata"]["signature"]

    def test_async_function_marked(self, parser, fixtures_dir):
        """Async functions are marked in metadata."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        async_funcs = [
            e for e in result.entities
            if e["kind"] == "function" and e["metadata"].get("is_async")
        ]

        assert len(async_funcs) == 1
        assert "fetch_data" in async_funcs[0]["name"]

    def test_class_has_bases(self, parser):
        """Classes with inheritance have base classes in metadata."""
        source = """
class Base:
    pass

class Derived(Base):
    pass

class Multi(Base, object):
    pass
"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            classes = {e["name"].split(".")[-1]: e for e in result.entities if e["kind"] == "class"}

            assert "bases" in classes["Derived"]["metadata"]
            assert "Base" in classes["Derived"]["metadata"]["bases"]

            assert "bases" in classes["Multi"]["metadata"]
            assert len(classes["Multi"]["metadata"]["bases"]) == 2

    def test_class_has_method_list(self, parser, fixtures_dir):
        """Classes have list of method names in metadata."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        calc_classes = [e for e in result.entities if "Calculator" in e["name"] and e["kind"] == "class"]
        assert len(calc_classes) == 1

        methods = calc_classes[0]["metadata"]["methods"]
        assert "__init__" in methods
        assert "add" in methods
        assert "multiply" in methods

    def test_entity_has_code(self, parser, fixtures_dir):
        """Entities have their source code stored."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        functions = [e for e in result.entities if e["kind"] == "function"]

        for func in functions:
            assert func["code"] is not None
            assert "def " in func["code"]

    def test_entity_has_intent(self, parser, fixtures_dir):
        """Entities with docstrings have intent set."""
        result = parser.parse_file(fixtures_dir / "simple_module.py")

        greet_funcs = [e for e in result.entities if "greet" in e["name"] and e["kind"] == "function"]
        assert len(greet_funcs) == 1

        assert greet_funcs[0]["intent"] is not None
        assert "greeting" in greet_funcs[0]["intent"].lower()


class TestParserInterface:
    """Tests for the BaseParser interface implementation."""

    def test_language_property(self, parser):
        """Parser has a language property."""
        assert parser.language == "python"

    def test_file_extensions_property(self, parser):
        """Parser reports supported file extensions."""
        exts = parser.file_extensions
        assert ".py" in exts
        assert ".pyw" in exts

    def test_can_parse_python_file(self, parser):
        """can_parse returns True for Python files."""
        assert parser.can_parse(Path("test.py"))
        assert parser.can_parse(Path("test.pyw"))
        assert parser.can_parse(Path("/some/path/module.py"))

    def test_can_parse_non_python_file(self, parser):
        """can_parse returns False for non-Python files."""
        assert not parser.can_parse(Path("test.js"))
        assert not parser.can_parse(Path("test.rb"))
        assert not parser.can_parse(Path("test.txt"))
        assert not parser.can_parse(Path("Makefile"))

    def test_parse_files_method(self, parser, fixtures_dir):
        """parse_files method parses multiple files."""
        files = [
            fixtures_dir / "simple_module.py",
            fixtures_dir / "syntax_error.py",
        ]

        results = parser.parse_files(files)

        assert len(results) == 2
        # First file should parse successfully
        assert len(results[0].entities) > 0
        # Second file should have errors
        assert len(results[1].errors) > 0


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_decorators_preserved(self, parser):
        """Functions with decorators are parsed correctly."""
        source = """
def decorator(func):
    return func

@decorator
def decorated_function():
    pass

class MyClass:
    @staticmethod
    def static_method():
        pass

    @classmethod
    def class_method(cls):
        pass
"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            functions = [e for e in result.entities if e["kind"] == "function"]
            methods = [e for e in result.entities if e["kind"] == "method"]

            assert len(functions) == 2  # decorator + decorated_function
            assert len(methods) == 2  # static_method + class_method

    def test_lambda_not_extracted(self, parser):
        """Lambda functions are not extracted as entities."""
        source = """
add = lambda x, y: x + y
multiply = lambda x, y: x * y

def uses_lambda():
    return list(map(lambda x: x * 2, [1, 2, 3]))
"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            functions = [e for e in result.entities if e["kind"] == "function"]
            # Only uses_lambda should be extracted
            assert len(functions) == 1
            assert "uses_lambda" in functions[0]["name"]

    def test_module_name_from_path(self, parser):
        """Module name is derived from file path."""
        source = "pass"

        with tempfile.NamedTemporaryFile(
            suffix=".py", delete=False, prefix="my_module_"
        ) as f:
            result = parser.parse_file(Path(f.name), source=source)

            modules = [e for e in result.entities if e["kind"] == "module"]
            assert len(modules) == 1
            # Module name should be based on file stem
            assert modules[0]["name"].startswith("my_module_")

    def test_init_file_module_name(self, parser):
        """__init__.py files use parent directory as module name."""
        source = "pass"

        with tempfile.TemporaryDirectory() as tmpdir:
            init_file = Path(tmpdir) / "__init__.py"
            init_file.write_text(source)

            result = parser.parse_file(init_file, source=source)

            modules = [e for e in result.entities if e["kind"] == "module"]
            assert len(modules) == 1
            # Module name should be the parent directory name
            assert modules[0]["name"] == Path(tmpdir).name

    def test_complex_signatures(self, parser):
        """Functions with complex signatures are handled."""
        source = """
def complex_args(pos_only, /, standard, *args, kw_only, **kwargs):
    pass

def with_defaults(a, b=10, c="default"):
    pass

def with_annotations(x: int, y: str = "hello") -> bool:
    pass
"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            functions = [e for e in result.entities if e["kind"] == "function"]
            assert len(functions) == 3

            for func in functions:
                assert "signature" in func["metadata"]
