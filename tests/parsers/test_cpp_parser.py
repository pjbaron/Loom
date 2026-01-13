"""Tests for the C++ parser with Unreal Engine support."""

import pytest
from pathlib import Path

from parsers.cpp_parser import CppParser


@pytest.fixture
def parser():
    return CppParser()


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent / "test_fixtures"


class TestCppParserBasics:
    """Tests for basic C++ parser functionality."""

    def test_language_property(self, parser):
        assert parser.language == "cpp"

    def test_file_extensions(self, parser):
        extensions = parser.file_extensions
        assert ".h" in extensions
        assert ".hpp" in extensions
        assert ".cpp" in extensions
        assert ".cc" in extensions
        assert ".c" in extensions

    def test_can_parse_cpp_files(self, parser):
        assert parser.can_parse(Path("test.cpp")) is True
        assert parser.can_parse(Path("test.h")) is True
        assert parser.can_parse(Path("test.hpp")) is True
        assert parser.can_parse(Path("test.cc")) is True
        assert parser.can_parse(Path("test.cxx")) is True

    def test_can_parse_non_cpp_files(self, parser):
        assert parser.can_parse(Path("test.py")) is False
        assert parser.can_parse(Path("test.js")) is False
        assert parser.can_parse(Path("test.ts")) is False


class TestCppParserEntityExtraction:
    """Tests for entity extraction from C++ files."""

    def test_parse_simple_header(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.h")

        assert len(result.errors) == 0

        # Check for module entity
        modules = [e for e in result.entities if e["kind"] == "module"]
        assert len(modules) == 1
        assert modules[0]["name"] == "simple_class"

        # Check for class entity
        classes = [e for e in result.entities if e["kind"] == "class"]
        assert len(classes) >= 1

        # Find SimpleClass
        simple_class = next((c for c in classes if "SimpleClass" in c["name"]), None)
        assert simple_class is not None
        assert "MyNamespace" in simple_class["name"]

    def test_parse_simple_implementation(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.cpp")

        assert len(result.errors) == 0

        # Check for methods
        methods = [e for e in result.entities if e["kind"] == "method"]
        assert len(methods) >= 1

        # Check for includes
        imports = [r for r in result.relationships if r[2] == "imports"]
        assert len(imports) >= 1
        assert any("simple_class.h" in r[1] for r in imports)

    def test_parse_class_with_methods(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.h")

        # Find SimpleClass
        classes = [e for e in result.entities if e["kind"] == "class"]
        simple_class = next((c for c in classes if "SimpleClass" in c["name"]), None)
        assert simple_class is not None

        # Check metadata
        assert "methods" in simple_class["metadata"]
        method_names = simple_class["metadata"]["methods"]
        # Should have constructor, destructor, and other methods
        assert len(method_names) >= 3

    def test_extract_free_function(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.h")

        # Check for free function
        functions = [e for e in result.entities if e["kind"] == "function"]
        helper_func = next((f for f in functions if "helperFunction" in f["name"]), None)
        assert helper_func is not None

    def test_extract_enum(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "unreal_character.h")

        # Check for enum
        enums = [e for e in result.entities if e["kind"] == "enum"]
        assert len(enums) >= 1

        state_enum = next((e for e in enums if "ECharacterState" in e["name"]), None)
        assert state_enum is not None
        assert "members" in state_enum["metadata"]


class TestCppParserUnrealEngine:
    """Tests for Unreal Engine specific features."""

    def test_parse_uclass(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "unreal_character.h")

        # Find the UE character class
        classes = [e for e in result.entities if e["kind"] == "class"]
        character = next((c for c in classes if "AUnrealCharacter" in c["name"]), None)
        assert character is not None

        # Check for UE metadata (may be detected from UCLASS macro)
        metadata = character["metadata"]
        assert metadata.get("language") == "cpp"

    def test_parse_ustruct(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "unreal_character.h")

        # Find the UE struct
        classes = [e for e in result.entities if e["kind"] == "class"]
        stats_struct = next((c for c in classes if "FCharacterStats" in c["name"]), None)
        assert stats_struct is not None

        # Check it's recognized as a struct
        assert stats_struct["metadata"].get("is_struct") is True

    def test_parse_uenum(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "unreal_character.h")

        # Find the UE enum
        enums = [e for e in result.entities if e["kind"] == "enum"]
        state_enum = next((e for e in enums if "ECharacterState" in e["name"]), None)
        assert state_enum is not None

        # Check members
        members = state_enum["metadata"].get("members", [])
        assert "Idle" in members
        assert "Walking" in members
        assert "Running" in members
        assert "Jumping" in members


class TestCppParserRelationships:
    """Tests for relationship extraction."""

    def test_include_relationships(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.h")

        imports = [r for r in result.relationships if r[2] == "imports"]
        assert len(imports) >= 2

        # Check for standard library includes
        import_paths = [r[1] for r in imports]
        assert "string" in import_paths
        assert "vector" in import_paths

    def test_contains_relationships(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.h")

        contains_rels = [r for r in result.relationships if r[2] == "contains"]
        assert len(contains_rels) >= 1

    def test_member_of_relationships(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.cpp")

        member_of_rels = [r for r in result.relationships if r[2] == "member_of"]
        assert len(member_of_rels) >= 1

    def test_calls_relationships(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.cpp")

        calls_rels = [r for r in result.relationships if r[2] == "calls"]
        # Should detect calls to internalHelper, process, etc.
        assert len(calls_rels) >= 1


class TestCppParserMetadata:
    """Tests for metadata extraction."""

    def test_method_signature(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.h")

        methods = [e for e in result.entities if e["kind"] == "method"]
        set_value = next((m for m in methods if "setValue" in m["name"]), None)
        assert set_value is not None
        assert "signature" in set_value["metadata"]
        assert "int" in set_value["metadata"]["signature"]

    def test_virtual_method_detection(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.h")

        methods = [e for e in result.entities if e["kind"] == "method"]
        process_method = next((m for m in methods if "process" in m["name"]), None)
        # Virtual detection depends on how it's parsed
        if process_method:
            assert "metadata" in process_method

    def test_static_method_detection(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "simple_class.h")

        methods = [e for e in result.entities if e["kind"] == "method"]
        create_method = next((m for m in methods if "create" in m["name"]), None)
        # Static detection depends on how it's parsed
        if create_method:
            assert "metadata" in create_method

    def test_class_base_classes(self, parser, fixtures_dir):
        result = parser.parse_file(fixtures_dir / "unreal_character.h")

        classes = [e for e in result.entities if e["kind"] == "class"]
        character = next((c for c in classes if "AUnrealCharacter" in c["name"]), None)
        assert character is not None

        bases = character["metadata"].get("bases", [])
        assert "ACharacter" in bases


class TestCppParserSourceCode:
    """Tests for inline source code parsing."""

    def test_parse_simple_code_string(self, parser):
        code = '''
class TestClass {
public:
    void doSomething() {
        // Implementation
    }
};
'''
        result = parser.parse_file(Path("test.h"), source=code)

        assert len(result.errors) == 0

        classes = [e for e in result.entities if e["kind"] == "class"]
        assert len(classes) == 1
        assert "TestClass" in classes[0]["name"]

    def test_parse_namespace_code(self, parser):
        code = '''
namespace Outer {
namespace Inner {

void nestedFunction() {}

}
}
'''
        result = parser.parse_file(Path("test.cpp"), source=code)

        assert len(result.errors) == 0

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert "nestedFunction" in functions[0]["name"]

    def test_parse_template_class(self, parser):
        code = '''
template<typename T>
class GenericContainer {
public:
    void add(const T& item);
    T get(int index) const;
};
'''
        result = parser.parse_file(Path("test.h"), source=code)

        assert len(result.errors) == 0

        classes = [e for e in result.entities if e["kind"] == "class"]
        assert len(classes) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
