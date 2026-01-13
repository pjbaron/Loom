"""Tests for JavaScript and TypeScript parsers."""

import pytest
import tempfile
from pathlib import Path

from parsers.base import ParseResult

# Skip all tests if tree-sitter not available
pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_javascript")
pytest.importorskip("tree_sitter_typescript")

from parsers.js_ts_parser import JavaScriptParser, TypeScriptParser


@pytest.fixture
def js_parser():
    """Create a fresh JavaScriptParser for each test."""
    return JavaScriptParser()


@pytest.fixture
def ts_parser():
    """Create a fresh TypeScriptParser for each test."""
    return TypeScriptParser()


class TestJavaScriptParseFileEntityCount:
    """Tests for JavaScript parse_file returning correct entity counts."""

    def test_parse_simple_module_entity_count(self, js_parser):
        """Parsing a simple module returns correct number of entities."""
        source = '''
function greet(name) {
    return `Hello, ${name}!`;
}

async function fetchData(url) {
    return await fetch(url);
}

class Calculator {
    constructor(value) {
        this.value = value;
    }

    add(n) {
        return this.value + n;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        kinds = [e["kind"] for e in result.entities]
        assert kinds.count("module") == 1
        assert kinds.count("function") == 2  # greet, fetchData
        assert kinds.count("class") == 1  # Calculator
        assert kinds.count("method") == 2  # constructor, add

    def test_parse_file_returns_parse_result(self, js_parser):
        """parse_file returns a ParseResult instance."""
        source = "function test() {}"
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        assert isinstance(result, ParseResult)
        assert hasattr(result, "entities")
        assert hasattr(result, "relationships")
        assert hasattr(result, "errors")

    def test_parse_empty_file(self, js_parser):
        """Parsing an empty file returns only module entity."""
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write("")
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        kinds = [e["kind"] for e in result.entities]
        assert kinds.count("module") == 1
        assert len(result.entities) == 1

    def test_parse_arrow_functions(self, js_parser):
        """Arrow functions assigned to variables are extracted."""
        source = '''
const add = (a, b) => a + b;
const multiply = (a, b) => {
    return a * b;
};
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 2
        names = [f["name"].split(".")[-1] for f in functions]
        assert "add" in names
        assert "multiply" in names


class TestJavaScriptRelationshipExtraction:
    """Tests for JavaScript relationship extraction."""

    def test_contains_relationships(self, js_parser):
        """Module contains function and class relationships are extracted."""
        source = '''
function greet() {}
class Calculator {}
const arrow = () => {};
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        contains_rels = [r for r in result.relationships if r[2] == "contains"]
        assert len(contains_rels) == 3  # greet, Calculator, arrow

    def test_member_of_relationships(self, js_parser):
        """Method member_of class relationships are extracted."""
        source = '''
class Calculator {
    constructor(value) {
        this.value = value;
    }
    add(n) {
        return this.value + n;
    }
    multiply(n) {
        return this.value * n;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        member_rels = [r for r in result.relationships if r[2] == "member_of"]
        assert len(member_rels) == 3  # constructor, add, multiply

        for method_name, class_name, rel_type in member_rels:
            assert "Calculator" in class_name

    def test_import_relationships(self, js_parser):
        """Import statements generate import relationships."""
        source = '''
import { foo } from 'bar';
import * as utils from './utils';
import defaultExport from 'module';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        imported_modules = [r[1] for r in import_rels]
        assert "bar" in imported_modules
        assert "./utils" in imported_modules
        assert "module" in imported_modules

    def test_calls_relationships(self, js_parser):
        """Function calls generate calls relationships."""
        source = '''
function caller() {
    console.log("hello");
    helper();
}

function helper() {}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        calls_rels = [r for r in result.relationships if r[2] == "calls"]
        called_names = [r[1] for r in calls_rels]
        assert "log" in called_names
        assert "helper" in called_names


class TestJavaScriptEntityMetadata:
    """Tests for JavaScript entity metadata extraction."""

    def test_function_has_line_numbers(self, js_parser):
        """Functions have start and end line numbers."""
        source = '''
function greet() {
    return "hello";
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        for func in functions:
            assert func["start_line"] is not None
            assert func["start_line"] > 0
            assert func["end_line"] is not None
            assert func["end_line"] >= func["start_line"]

    def test_async_function_marked(self, js_parser):
        """Async functions are marked in metadata."""
        source = '''
async function fetchData() {
    return await fetch('/api');
}

function syncFunction() {}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        async_funcs = [
            e for e in result.entities
            if e["kind"] == "function" and e["metadata"].get("is_async")
        ]
        assert len(async_funcs) == 1
        assert "fetchData" in async_funcs[0]["name"]

    def test_jsdoc_extracted_as_intent(self, js_parser):
        """JSDoc comments are extracted as intent."""
        source = '''
/** A simple greeting function */
function greet(name) {
    return `Hello, ${name}!`;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        greet_funcs = [e for e in result.entities if "greet" in e["name"]]
        assert len(greet_funcs) == 1
        assert greet_funcs[0]["intent"] is not None
        assert "greeting" in greet_funcs[0]["intent"].lower()

    def test_class_has_method_list(self, js_parser):
        """Classes have list of method names in metadata."""
        source = '''
class Calculator {
    constructor(value) {}
    add(n) {}
    multiply(n) {}
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        calc_classes = [e for e in result.entities if "Calculator" in e["name"] and e["kind"] == "class"]
        assert len(calc_classes) == 1
        methods = calc_classes[0]["metadata"]["methods"]
        assert "constructor" in methods
        assert "add" in methods
        assert "multiply" in methods


class TestJavaScriptParserInterface:
    """Tests for the BaseParser interface implementation."""

    def test_language_property(self, js_parser):
        """Parser has a language property."""
        assert js_parser.language == "javascript"

    def test_file_extensions_property(self, js_parser):
        """Parser reports supported file extensions."""
        exts = js_parser.file_extensions
        assert ".js" in exts
        assert ".mjs" in exts
        assert ".cjs" in exts
        assert ".jsx" in exts

    def test_can_parse_js_file(self, js_parser):
        """can_parse returns True for JavaScript files."""
        assert js_parser.can_parse(Path("test.js"))
        assert js_parser.can_parse(Path("test.mjs"))
        assert js_parser.can_parse(Path("test.jsx"))
        assert js_parser.can_parse(Path("/some/path/module.js"))

    def test_can_parse_non_js_file(self, js_parser):
        """can_parse returns False for non-JavaScript files."""
        assert not js_parser.can_parse(Path("test.py"))
        assert not js_parser.can_parse(Path("test.ts"))
        assert not js_parser.can_parse(Path("test.txt"))


class TestTypeScriptParseFileEntityCount:
    """Tests for TypeScript parse_file returning correct entity counts."""

    def test_parse_simple_module_entity_count(self, ts_parser):
        """Parsing a simple module returns correct number of entities."""
        source = '''
interface Person {
    name: string;
    age: number;
}

type Status = 'active' | 'inactive';

function greet(person: Person): string {
    return `Hello, ${person.name}!`;
}

class UserService {
    private users: string[] = [];

    getUser(id: string): string | null {
        return this.users.find(u => u === id) ?? null;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".ts", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = ts_parser.parse_file(Path(f.name))

        kinds = [e["kind"] for e in result.entities]
        assert kinds.count("module") == 1
        assert kinds.count("interface") == 1  # Person
        assert kinds.count("type") == 1  # Status
        assert kinds.count("function") == 1  # greet
        assert kinds.count("class") == 1  # UserService
        assert kinds.count("method") == 1  # getUser

    def test_parse_interface(self, ts_parser):
        """TypeScript interfaces are extracted."""
        source = '''
interface User {
    id: string;
    name: string;
    email: string;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".ts", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = ts_parser.parse_file(Path(f.name))

        interfaces = [e for e in result.entities if e["kind"] == "interface"]
        assert len(interfaces) == 1
        assert "User" in interfaces[0]["name"]
        assert "properties" in interfaces[0]["metadata"]
        assert "id" in interfaces[0]["metadata"]["properties"]
        assert "name" in interfaces[0]["metadata"]["properties"]

    def test_parse_type_alias(self, ts_parser):
        """TypeScript type aliases are extracted."""
        source = '''
type Status = 'active' | 'inactive';
type ID = string | number;
'''
        with tempfile.NamedTemporaryFile(suffix=".ts", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = ts_parser.parse_file(Path(f.name))

        types = [e for e in result.entities if e["kind"] == "type"]
        assert len(types) == 2
        names = [t["name"].split(".")[-1] for t in types]
        assert "Status" in names
        assert "ID" in names

    def test_parse_enum(self, ts_parser):
        """TypeScript enums are extracted."""
        source = '''
enum Color {
    Red,
    Green,
    Blue
}

enum Status {
    Active = 'active',
    Inactive = 'inactive'
}
'''
        with tempfile.NamedTemporaryFile(suffix=".ts", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = ts_parser.parse_file(Path(f.name))

        enums = [e for e in result.entities if e["kind"] == "enum"]
        assert len(enums) == 2
        names = [t["name"].split(".")[-1] for t in enums]
        assert "Color" in names
        assert "Status" in names


class TestTypeScriptParserInterface:
    """Tests for the TypeScript parser interface."""

    def test_language_property(self, ts_parser):
        """Parser has a language property."""
        assert ts_parser.language == "typescript"

    def test_file_extensions_property(self, ts_parser):
        """Parser reports supported file extensions."""
        exts = ts_parser.file_extensions
        assert ".ts" in exts
        assert ".tsx" in exts

    def test_can_parse_ts_file(self, ts_parser):
        """can_parse returns True for TypeScript files."""
        assert ts_parser.can_parse(Path("test.ts"))
        assert ts_parser.can_parse(Path("test.tsx"))
        assert ts_parser.can_parse(Path("/some/path/module.ts"))

    def test_can_parse_non_ts_file(self, ts_parser):
        """can_parse returns False for non-TypeScript files."""
        assert not ts_parser.can_parse(Path("test.js"))
        assert not ts_parser.can_parse(Path("test.py"))


class TestEncodingHandling:
    """Tests for handling various file encodings in JS/TS files."""

    def test_utf8_encoding(self, js_parser):
        """Standard UTF-8 files are parsed correctly."""
        source = '''
function greet() {
    return "Hello, 你好, مرحبا, Привет";
}
'''
        with tempfile.NamedTemporaryFile(
            suffix=".js", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        assert len(result.errors) == 0
        assert len(result.entities) == 2  # module + function

    def test_nonexistent_file(self, js_parser):
        """Nonexistent file returns error in result."""
        result = js_parser.parse_file(Path("/nonexistent/path/file.js"))

        assert len(result.errors) > 0
        assert len(result.entities) == 0


class TestExportedDeclarations:
    """Tests for handling exported declarations."""

    def test_exported_function(self, js_parser):
        """Exported functions are extracted."""
        source = '''
export function greet(name) {
    return `Hello, ${name}!`;
}

export default function main() {
    console.log("main");
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 2
        names = [f["name"].split(".")[-1] for f in functions]
        assert "greet" in names
        assert "main" in names

    def test_exported_class(self, js_parser):
        """Exported classes are extracted."""
        source = '''
export class Calculator {
    add(a, b) {
        return a + b;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        classes = [e for e in result.entities if e["kind"] == "class"]
        assert len(classes) == 1
        assert "Calculator" in classes[0]["name"]


class TestStaticMethods:
    """Tests for static method handling."""

    def test_static_method_marked(self, js_parser):
        """Static methods are marked in metadata."""
        source = '''
class Calculator {
    static create() {
        return new Calculator();
    }

    add(n) {
        return this.value + n;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        methods = [e for e in result.entities if e["kind"] == "method"]
        static_methods = [m for m in methods if m["metadata"].get("is_static")]
        assert len(static_methods) == 1
        assert "create" in static_methods[0]["name"]


class TestImportSpecifiers:
    """Tests for detailed import specifier extraction."""

    def test_named_imports_with_specifiers(self, js_parser):
        """Named imports include specifier details."""
        source = '''
import { foo, bar } from './utils';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        assert import_rels[0][1] == "./utils"
        assert len(import_rels[0]) == 4  # Has metadata
        metadata = import_rels[0][3]
        assert 'specifiers' in metadata
        names = [s['name'] for s in metadata['specifiers']]
        assert 'foo' in names
        assert 'bar' in names
        assert all(s['type'] == 'named' for s in metadata['specifiers'])

    def test_namespace_import(self, js_parser):
        """Namespace imports are captured with type."""
        source = '''
import * as lodash from 'lodash';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        assert import_rels[0][1] == "lodash"
        metadata = import_rels[0][3]
        assert len(metadata['specifiers']) == 1
        assert metadata['specifiers'][0]['name'] == 'lodash'
        assert metadata['specifiers'][0]['type'] == 'namespace'

    def test_default_import(self, js_parser):
        """Default imports are captured with type."""
        source = '''
import React from 'react';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        assert import_rels[0][1] == "react"
        metadata = import_rels[0][3]
        assert len(metadata['specifiers']) == 1
        assert metadata['specifiers'][0]['name'] == 'React'
        assert metadata['specifiers'][0]['type'] == 'default'

    def test_mixed_imports(self, js_parser):
        """Mixed default and named imports are captured."""
        source = '''
import React, { useState, useEffect } from 'react';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        metadata = import_rels[0][3]
        specs = metadata['specifiers']
        assert len(specs) == 3
        default_specs = [s for s in specs if s['type'] == 'default']
        named_specs = [s for s in specs if s['type'] == 'named']
        assert len(default_specs) == 1
        assert default_specs[0]['name'] == 'React'
        assert len(named_specs) == 2
        assert set(s['name'] for s in named_specs) == {'useState', 'useEffect'}

    def test_aliased_imports(self, js_parser):
        """Aliased imports include original name."""
        source = '''
import { foo as f, bar as b } from './utils';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        metadata = import_rels[0][3]
        specs = metadata['specifiers']
        assert len(specs) == 2
        f_spec = next(s for s in specs if s['name'] == 'f')
        assert f_spec['original'] == 'foo'
        b_spec = next(s for s in specs if s['name'] == 'b')
        assert b_spec['original'] == 'bar'


class TestCommonJSRequire:
    """Tests for CommonJS require() extraction."""

    def test_simple_require(self, js_parser):
        """Simple require statements are captured."""
        source = '''
const fs = require('fs');
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        assert import_rels[0][1] == "fs"
        metadata = import_rels[0][3]
        assert metadata.get('style') == 'commonjs'
        assert len(metadata['specifiers']) == 1
        assert metadata['specifiers'][0]['name'] == 'fs'
        assert metadata['specifiers'][0]['type'] == 'default'

    def test_destructured_require(self, js_parser):
        """Destructured require statements are captured."""
        source = '''
const { readFile, writeFile } = require('fs/promises');
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        assert import_rels[0][1] == "fs/promises"
        metadata = import_rels[0][3]
        assert metadata.get('style') == 'commonjs'
        specs = metadata['specifiers']
        assert len(specs) == 2
        names = [s['name'] for s in specs]
        assert 'readFile' in names
        assert 'writeFile' in names


class TestExportRelationships:
    """Tests for export relationship extraction."""

    def test_exported_function_has_exports_relationship(self, js_parser):
        """Exported functions create exports relationships."""
        source = '''
export function greet(name) {
    return `Hello, ${name}!`;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        export_rels = [r for r in result.relationships if r[2] == "exports"]
        assert len(export_rels) == 1
        assert "greet" in export_rels[0][1]
        metadata = export_rels[0][3]
        assert metadata['name'] == 'greet'
        assert metadata['is_default'] == False

    def test_default_export_marked(self, js_parser):
        """Default exports are marked in metadata."""
        source = '''
export default function main() {
    console.log("main");
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        export_rels = [r for r in result.relationships if r[2] == "exports"]
        assert len(export_rels) == 1
        metadata = export_rels[0][3]
        assert metadata['is_default'] == True

        # Check entity metadata too
        func = next(e for e in result.entities if e['kind'] == 'function')
        assert func['metadata']['is_default_export'] == True

    def test_exported_class_has_exports_relationship(self, js_parser):
        """Exported classes create exports relationships."""
        source = '''
export class UserService {
    getUser(id) {
        return id;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        export_rels = [r for r in result.relationships if r[2] == "exports"]
        assert len(export_rels) == 1
        assert "UserService" in export_rels[0][1]
        metadata = export_rels[0][3]
        assert metadata['name'] == 'UserService'

    def test_named_exports(self, js_parser):
        """Named exports (export { x, y }) are captured."""
        source = '''
function foo() {}
function bar() {}
export { foo, bar };
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        export_rels = [r for r in result.relationships if r[2] == "exports"]
        assert len(export_rels) == 2
        names = [r[3]['name'] for r in export_rels]
        assert 'foo' in names
        assert 'bar' in names

    def test_aliased_exports(self, js_parser):
        """Aliased exports include original name."""
        source = '''
function internalLog() {}
export { internalLog as log };
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        export_rels = [r for r in result.relationships if r[2] == "exports"]
        assert len(export_rels) == 1
        metadata = export_rels[0][3]
        assert metadata['name'] == 'log'
        assert metadata['original'] == 'internalLog'


class TestReExports:
    """Tests for re-export statement extraction."""

    def test_re_export_named(self, js_parser):
        """Re-exports from other modules are captured."""
        source = '''
export { foo, bar } from './utils';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        re_export_rels = [r for r in result.relationships if r[2] == "re_exports"]
        assert len(re_export_rels) == 2
        assert all(r[1] == "./utils" for r in re_export_rels)
        names = [r[3]['name'] for r in re_export_rels]
        assert 'foo' in names
        assert 'bar' in names

    def test_re_export_with_alias(self, js_parser):
        """Re-exports with aliases include original name."""
        source = '''
export { default as myDefault } from './module';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        re_export_rels = [r for r in result.relationships if r[2] == "re_exports"]
        assert len(re_export_rels) == 1
        assert re_export_rels[0][1] == "./module"
        metadata = re_export_rels[0][3]
        assert metadata['name'] == 'myDefault'
        assert metadata['original'] == 'default'


class TestExportMetadata:
    """Tests for exported entity metadata."""

    def test_exported_function_metadata(self, js_parser):
        """Exported functions have exported flag in metadata."""
        source = '''
export function greet() {}
function internal() {}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        funcs = [e for e in result.entities if e['kind'] == 'function']
        greet = next(f for f in funcs if 'greet' in f['name'])
        internal = next(f for f in funcs if 'internal' in f['name'])

        assert greet['metadata'].get('exported') == True
        assert internal['metadata'].get('exported', False) == False

    def test_exported_arrow_function_metadata(self, js_parser):
        """Exported arrow functions have exported flag in metadata."""
        source = '''
export const greet = () => {};
const internal = () => {};
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        funcs = [e for e in result.entities if e['kind'] == 'function']
        greet = next(f for f in funcs if 'greet' in f['name'])
        internal = next(f for f in funcs if 'internal' in f['name'])

        assert greet['metadata'].get('exported') == True
        assert internal['metadata'].get('exported', False) == False

    def test_exported_class_metadata(self, js_parser):
        """Exported classes have exported flag in metadata."""
        source = '''
export class PublicClass {}
class PrivateClass {}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = js_parser.parse_file(Path(f.name))

        classes = [e for e in result.entities if e['kind'] == 'class']
        public = next(c for c in classes if 'PublicClass' in c['name'])
        private = next(c for c in classes if 'PrivateClass' in c['name'])

        assert public['metadata'].get('exported') == True
        assert private['metadata'].get('exported', False) == False


class TestMultiFileProject:
    """Integration tests using the multi-file JS project fixture."""

    @pytest.fixture
    def project_path(self):
        """Path to the test fixture project."""
        return Path(__file__).parent.parent / "tests" / "fixtures" / "js_project"

    def test_parse_utils_module(self, js_parser, project_path):
        """Parse utils.js and verify entities and relationships."""
        utils_path = project_path / "utils.js"
        if not utils_path.exists():
            pytest.skip("Fixture not available")

        result = js_parser.parse_file(utils_path)

        # Check entities
        funcs = [e for e in result.entities if e['kind'] == 'function']
        func_names = [f['name'].split('.')[-1] for f in funcs]
        assert 'formatDate' in func_names
        assert 'parseDate' in func_names
        assert 'logInternal' in func_names

        # Check exports
        export_rels = [r for r in result.relationships if r[2] == "exports"]
        exported_names = [r[3]['name'] for r in export_rels]
        assert 'formatDate' in exported_names
        assert 'parseDate' in exported_names
        assert 'log' in exported_names  # Aliased export

    def test_parse_api_module(self, js_parser, project_path):
        """Parse api.js and verify imports and exports."""
        api_path = project_path / "api.js"
        if not api_path.exists():
            pytest.skip("Fixture not available")

        result = js_parser.parse_file(api_path)

        # Check ES6 imports
        import_rels = [r for r in result.relationships if r[2] == "imports"]
        imported_modules = [r[1] for r in import_rels]
        assert './utils' in imported_modules
        assert 'lodash' in imported_modules
        assert 'axios' in imported_modules
        assert 'fs' in imported_modules  # CommonJS
        assert 'util' in imported_modules  # CommonJS

        # Check CommonJS imports
        commonjs_rels = [r for r in import_rels if r[3].get('style') == 'commonjs']
        assert len(commonjs_rels) == 2

        # Check exports
        export_rels = [r for r in result.relationships if r[2] == "exports"]
        exported_names = [r[3]['name'] for r in export_rels]
        assert 'fetchUser' in exported_names
        assert 'fetchAllUsers' in exported_names
        assert 'UserApiClient' in exported_names

    def test_parse_index_module_reexports(self, js_parser, project_path):
        """Parse index.js and verify re-exports."""
        index_path = project_path / "index.js"
        if not index_path.exists():
            pytest.skip("Fixture not available")

        result = js_parser.parse_file(index_path)

        # Check re-exports
        re_export_rels = [r for r in result.relationships if r[2] == "re_exports"]
        assert len(re_export_rels) >= 3

        # Check re-export from utils
        utils_reexports = [r for r in re_export_rels if r[1] == "./utils"]
        utils_names = [r[3]['name'] for r in utils_reexports]
        assert 'formatDate' in utils_names
        assert 'log' in utils_names

        # Check aliased re-export
        client_reexport = next((r for r in re_export_rels if r[3]['name'] == 'Client'), None)
        assert client_reexport is not None
        assert client_reexport[3]['original'] == 'UserApiClient'

    def test_parse_typescript_module(self, ts_parser, project_path):
        """Parse types.ts and verify TypeScript-specific exports."""
        types_path = project_path / "types.ts"
        if not types_path.exists():
            pytest.skip("Fixture not available")

        result = ts_parser.parse_file(types_path)

        # Check entities
        interfaces = [e for e in result.entities if e['kind'] == 'interface']
        types = [e for e in result.entities if e['kind'] == 'type']
        enums = [e for e in result.entities if e['kind'] == 'enum']
        classes = [e for e in result.entities if e['kind'] == 'class']

        assert len(interfaces) >= 2  # User, ApiResponse
        assert len(types) >= 2  # UserId, UserRole
        assert len(enums) >= 1  # Status
        assert len(classes) >= 1  # UserService
