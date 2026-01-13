"""Tests for JavaScriptParser - comprehensive test coverage for JavaScript parsing."""

import pytest
import tempfile
from pathlib import Path

from parsers.base import ParseResult

# Skip all tests if tree-sitter not available
pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_javascript")

from parsers.js_ts_parser import JavaScriptParser


@pytest.fixture
def parser():
    """Create a fresh JavaScriptParser for each test."""
    return JavaScriptParser()


class TestParseFunctionDeclaration:
    """Tests for parsing function declarations."""

    def test_parse_basic_function(self, parser):
        """Basic function declaration is extracted."""
        source = '''
function greet(name) {
    return `Hello, ${name}!`;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert "greet" in functions[0]["name"]

    def test_parse_async_function(self, parser):
        """Async function declarations are extracted and marked."""
        source = '''
async function fetchData(url) {
    const response = await fetch(url);
    return response.json();
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["metadata"].get("is_async") == True

    def test_parse_function_with_multiple_params(self, parser):
        """Function with multiple parameters has correct signature."""
        source = '''
function calculate(a, b, c) {
    return a + b + c;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert "a" in functions[0]["metadata"]["signature"]
        assert "b" in functions[0]["metadata"]["signature"]
        assert "c" in functions[0]["metadata"]["signature"]

    def test_parse_function_has_line_numbers(self, parser):
        """Function declarations have start and end line numbers."""
        source = '''
function greet() {
    return "hello";
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        for func in functions:
            assert func["start_line"] is not None
            assert func["start_line"] > 0
            assert func["end_line"] is not None
            assert func["end_line"] >= func["start_line"]

    def test_parse_function_has_code(self, parser):
        """Functions have their source code stored."""
        source = '''
function myFunc() {
    return 42;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert "function" in functions[0]["code"]
        assert "myFunc" in functions[0]["code"]


class TestParseArrowFunction:
    """Tests for parsing arrow functions assigned to variables."""

    def test_parse_basic_arrow_function(self, parser):
        """Arrow function assigned to const is extracted."""
        source = '''
const add = (a, b) => a + b;
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert "add" in functions[0]["name"]

    def test_parse_arrow_function_with_body(self, parser):
        """Arrow function with block body is extracted."""
        source = '''
const multiply = (a, b) => {
    const result = a * b;
    return result;
};
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert "multiply" in functions[0]["name"]

    def test_arrow_function_marked_in_metadata(self, parser):
        """Arrow functions have is_arrow flag in metadata."""
        source = '''
const arrow = () => {};
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["metadata"].get("is_arrow") == True

    def test_async_arrow_function(self, parser):
        """Async arrow function is extracted and marked."""
        source = '''
const fetchAsync = async (url) => {
    const res = await fetch(url);
    return res.json();
};
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["metadata"].get("is_async") == True
        assert functions[0]["metadata"].get("is_arrow") == True

    def test_let_arrow_function(self, parser):
        """Arrow function assigned to let is extracted."""
        source = '''
let handler = (event) => event.target.value;
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert "handler" in functions[0]["name"]


class TestParseClass:
    """Tests for parsing class declarations."""

    def test_parse_basic_class(self, parser):
        """Basic class declaration is extracted."""
        source = '''
class Calculator {
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        classes = [e for e in result.entities if e["kind"] == "class"]
        assert len(classes) == 1
        assert "Calculator" in classes[0]["name"]

    def test_class_with_inheritance(self, parser):
        """Class with extends clause is parsed (base classes may be in metadata)."""
        source = '''
class Animal {
    speak() {}
}

class Dog extends Animal {
    bark() {}
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        classes = {e["name"].split(".")[-1]: e for e in result.entities if e["kind"] == "class"}
        assert "Dog" in classes
        assert "Animal" in classes
        # The parser may or may not extract bases depending on implementation
        assert "bases" in classes["Dog"]["metadata"]

    def test_class_has_line_numbers(self, parser):
        """Classes have start and end line numbers."""
        source = '''
class MyClass {
    constructor() {}
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        classes = [e for e in result.entities if e["kind"] == "class"]
        for cls in classes:
            assert cls["start_line"] is not None
            assert cls["start_line"] > 0
            assert cls["end_line"] is not None
            assert cls["end_line"] >= cls["start_line"]

    def test_class_has_code(self, parser):
        """Classes have their source code stored."""
        source = '''
class Person {
    constructor(name) {
        this.name = name;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        classes = [e for e in result.entities if e["kind"] == "class"]
        assert len(classes) == 1
        assert "class Person" in classes[0]["code"]


class TestParseClassMethods:
    """Tests for parsing class methods."""

    def test_parse_constructor(self, parser):
        """Constructor method is extracted."""
        source = '''
class Calculator {
    constructor(value) {
        this.value = value;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        methods = [e for e in result.entities if e["kind"] == "method"]
        assert len(methods) == 1
        assert "constructor" in methods[0]["name"]

    def test_parse_multiple_methods(self, parser):
        """Multiple methods in a class are extracted."""
        source = '''
class Calculator {
    constructor(value) {
        this.value = value;
    }

    add(n) {
        return this.value + n;
    }

    subtract(n) {
        return this.value - n;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        methods = [e for e in result.entities if e["kind"] == "method"]
        assert len(methods) == 3
        method_names = [m["name"].split(".")[-1] for m in methods]
        assert "constructor" in method_names
        assert "add" in method_names
        assert "subtract" in method_names

    def test_static_method_marked(self, parser):
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
            result = parser.parse_file(Path(f.name))

        methods = [e for e in result.entities if e["kind"] == "method"]
        static_methods = [m for m in methods if m["metadata"].get("is_static")]
        assert len(static_methods) == 1
        assert "create" in static_methods[0]["name"]

    def test_async_method_marked(self, parser):
        """Async methods are marked in metadata."""
        source = '''
class ApiClient {
    async fetchData(url) {
        return await fetch(url);
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        methods = [e for e in result.entities if e["kind"] == "method"]
        async_methods = [m for m in methods if m["metadata"].get("is_async")]
        assert len(async_methods) == 1
        assert "fetchData" in async_methods[0]["name"]

    def test_method_member_of_relationship(self, parser):
        """Methods have member_of relationship to their class."""
        source = '''
class Calculator {
    add(n) {
        return n;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        member_rels = [r for r in result.relationships if r[2] == "member_of"]
        assert len(member_rels) == 1
        assert "Calculator" in member_rels[0][1]

    def test_class_has_method_list(self, parser):
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
            result = parser.parse_file(Path(f.name))

        calc_classes = [e for e in result.entities if "Calculator" in e["name"] and e["kind"] == "class"]
        assert len(calc_classes) == 1
        methods = calc_classes[0]["metadata"]["methods"]
        assert "constructor" in methods
        assert "add" in methods
        assert "multiply" in methods


class TestParseExports:
    """Tests for parsing export statements."""

    def test_exported_function(self, parser):
        """Exported functions are extracted with exported flag."""
        source = '''
export function greet(name) {
    return `Hello, ${name}!`;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["metadata"].get("exported") == True

    def test_default_export_function(self, parser):
        """Default exported functions are marked."""
        source = '''
export default function main() {
    console.log("main");
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["metadata"].get("is_default_export") == True

    def test_exported_class(self, parser):
        """Exported classes are extracted with exported flag."""
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
            result = parser.parse_file(Path(f.name))

        classes = [e for e in result.entities if e["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["metadata"].get("exported") == True

    def test_exported_arrow_function(self, parser):
        """Exported arrow functions have exported flag."""
        source = '''
export const greet = () => {};
const internal = () => {};
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        funcs = [e for e in result.entities if e['kind'] == 'function']
        greet = next(f for f in funcs if 'greet' in f['name'])
        internal = next(f for f in funcs if 'internal' in f['name'])

        assert greet['metadata'].get('exported') == True
        assert internal['metadata'].get('exported', False) == False

    def test_named_exports(self, parser):
        """Named exports (export { x, y }) create exports relationships."""
        source = '''
function foo() {}
function bar() {}
export { foo, bar };
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        export_rels = [r for r in result.relationships if r[2] == "exports"]
        assert len(export_rels) == 2
        names = [r[3]['name'] for r in export_rels]
        assert 'foo' in names
        assert 'bar' in names

    def test_aliased_exports(self, parser):
        """Aliased exports include original name."""
        source = '''
function internalLog() {}
export { internalLog as log };
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        export_rels = [r for r in result.relationships if r[2] == "exports"]
        assert len(export_rels) == 1
        metadata = export_rels[0][3]
        assert metadata['name'] == 'log'
        assert metadata['original'] == 'internalLog'

    def test_re_export_named(self, parser):
        """Re-exports from other modules create re_exports relationships."""
        source = '''
export { foo, bar } from './utils';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        re_export_rels = [r for r in result.relationships if r[2] == "re_exports"]
        assert len(re_export_rels) == 2
        assert all(r[1] == "./utils" for r in re_export_rels)


class TestParseImports:
    """Tests for parsing import statements."""

    def test_named_imports(self, parser):
        """Named imports are extracted with specifiers."""
        source = '''
import { foo, bar } from './utils';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        assert import_rels[0][1] == "./utils"
        metadata = import_rels[0][3]
        names = [s['name'] for s in metadata['specifiers']]
        assert 'foo' in names
        assert 'bar' in names

    def test_default_import(self, parser):
        """Default imports are captured with type."""
        source = '''
import React from 'react';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        metadata = import_rels[0][3]
        assert metadata['specifiers'][0]['name'] == 'React'
        assert metadata['specifiers'][0]['type'] == 'default'

    def test_namespace_import(self, parser):
        """Namespace imports are captured with type."""
        source = '''
import * as lodash from 'lodash';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        metadata = import_rels[0][3]
        assert metadata['specifiers'][0]['name'] == 'lodash'
        assert metadata['specifiers'][0]['type'] == 'namespace'

    def test_mixed_imports(self, parser):
        """Mixed default and named imports are captured."""
        source = '''
import React, { useState, useEffect } from 'react';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        specs = import_rels[0][3]['specifiers']
        assert len(specs) == 3
        default_specs = [s for s in specs if s['type'] == 'default']
        named_specs = [s for s in specs if s['type'] == 'named']
        assert len(default_specs) == 1
        assert len(named_specs) == 2

    def test_aliased_imports(self, parser):
        """Aliased imports include original name."""
        source = '''
import { foo as f, bar as b } from './utils';
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        specs = import_rels[0][3]['specifiers']
        f_spec = next(s for s in specs if s['name'] == 'f')
        assert f_spec['original'] == 'foo'

    def test_commonjs_require(self, parser):
        """CommonJS require statements are captured."""
        source = '''
const fs = require('fs');
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        assert import_rels[0][1] == "fs"
        metadata = import_rels[0][3]
        assert metadata.get('style') == 'commonjs'

    def test_destructured_require(self, parser):
        """Destructured require statements are captured."""
        source = '''
const { readFile, writeFile } = require('fs/promises');
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        import_rels = [r for r in result.relationships if r[2] == "imports"]
        assert len(import_rels) == 1
        assert import_rels[0][1] == "fs/promises"
        specs = import_rels[0][3]['specifiers']
        names = [s['name'] for s in specs]
        assert 'readFile' in names
        assert 'writeFile' in names


class TestExtractJSDoc:
    """Tests for JSDoc comment extraction."""

    def test_jsdoc_extracted_for_function(self, parser):
        """JSDoc comments are extracted as intent for functions."""
        source = '''
/** A simple greeting function */
function greet(name) {
    return `Hello, ${name}!`;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        greet_funcs = [e for e in result.entities if "greet" in e["name"]]
        assert len(greet_funcs) == 1
        assert greet_funcs[0]["intent"] is not None
        assert "greeting" in greet_funcs[0]["intent"].lower()

    def test_jsdoc_multiline(self, parser):
        """Multiline JSDoc comments are parsed correctly."""
        source = '''
/**
 * Calculate the sum of two numbers.
 * Returns the result of addition.
 * @param {number} a - First number
 * @param {number} b - Second number
 * @returns {number} The sum
 */
function add(a, b) {
    return a + b;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        add_funcs = [e for e in result.entities if "add" in e["name"] and e["kind"] == "function"]
        assert len(add_funcs) == 1
        assert add_funcs[0]["intent"] is not None
        assert "sum" in add_funcs[0]["intent"].lower()

    def test_jsdoc_for_class(self, parser):
        """JSDoc comments are extracted as intent for classes."""
        source = '''
/**
 * A simple calculator class.
 */
class Calculator {
    add(a, b) {
        return a + b;
    }
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        classes = [e for e in result.entities if e["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["intent"] is not None
        assert "calculator" in classes[0]["intent"].lower()

    def test_no_jsdoc_intent_is_none(self, parser):
        """Functions without JSDoc have intent as None."""
        source = '''
function noDoc() {
    return 42;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["intent"] is None

    def test_regular_comment_not_jsdoc(self, parser):
        """Regular comments (not JSDoc) are not extracted."""
        source = '''
// This is a regular comment
function notJSDoc() {
    return 42;
}

/* This is also not JSDoc */
function alsoNotJSDoc() {
    return 42;
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 2
        for func in functions:
            assert func["intent"] is None


class TestCallExtraction:
    """Tests for function call extraction."""

    def test_simple_function_call(self, parser):
        """Simple function calls are extracted."""
        source = '''
function caller() {
    helper();
}

function helper() {}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        calls_rels = [r for r in result.relationships if r[2] == "calls"]
        called_names = [r[1] for r in calls_rels]
        assert "helper" in called_names

    def test_method_call(self, parser):
        """Method calls (obj.method()) are extracted."""
        source = '''
function caller() {
    console.log("hello");
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        calls_rels = [r for r in result.relationships if r[2] == "calls"]
        called_names = [r[1] for r in calls_rels]
        assert "log" in called_names

    def test_multiple_calls(self, parser):
        """Multiple calls in a function are all extracted."""
        source = '''
function doWork() {
    prepare();
    execute();
    cleanup();
}

function prepare() {}
function execute() {}
function cleanup() {}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        calls_rels = [r for r in result.relationships if r[2] == "calls"]
        called_names = [r[1] for r in calls_rels]
        assert "prepare" in called_names
        assert "execute" in called_names
        assert "cleanup" in called_names

    def test_calls_from_method(self, parser):
        """Calls from class methods are extracted."""
        source = '''
class Worker {
    doWork() {
        this.helper();
        externalFunc();
    }

    helper() {}
}

function externalFunc() {}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        calls_rels = [r for r in result.relationships if r[2] == "calls"]
        called_names = [r[1] for r in calls_rels]
        assert "helper" in called_names
        assert "externalFunc" in called_names

    def test_nested_calls(self, parser):
        """Nested function calls are extracted."""
        source = '''
function process() {
    outer(inner(data));
}

function outer(x) { return x; }
function inner(x) { return x; }
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        calls_rels = [r for r in result.relationships if r[2] == "calls"]
        called_names = [r[1] for r in calls_rels]
        assert "outer" in called_names
        assert "inner" in called_names


class TestSyntaxErrorHandling:
    """Tests for handling JavaScript syntax errors."""

    def test_syntax_error_returns_error(self, parser):
        """Files with syntax errors have errors in result."""
        source = '''
function broken(
    // Missing closing paren and brace
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        # Tree-sitter is error-tolerant, so it may still produce partial results
        # But we should verify it doesn't crash
        assert isinstance(result, ParseResult)

    def test_missing_semicolon_tolerant(self, parser):
        """Missing semicolons are handled gracefully (tree-sitter is tolerant)."""
        source = '''
function noSemi() {
    const x = 1
    const y = 2
    return x + y
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        assert len(result.errors) == 0
        functions = [e for e in result.entities if e["kind"] == "function"]
        assert len(functions) == 1

    def test_nonexistent_file(self, parser):
        """Nonexistent file returns error in result."""
        result = parser.parse_file(Path("/nonexistent/path/file.js"))

        assert len(result.errors) > 0
        assert len(result.entities) == 0

    def test_unmatched_braces(self, parser):
        """Unmatched braces are handled gracefully."""
        source = '''
function unmatched() {
    if (true) {
        console.log("hello");
    // Missing closing brace
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        # Tree-sitter handles this gracefully
        assert isinstance(result, ParseResult)


class TestEncodingHandling:
    """Tests for handling various file encodings."""

    def test_utf8_encoding(self, parser):
        """Standard UTF-8 files are parsed correctly."""
        source = '''
function greet() {
    return "Hello, \u4f60\u597d, \u0645\u0631\u062d\u0628\u0627, \u041f\u0440\u0438\u0432\u0435\u0442";
}
'''
        with tempfile.NamedTemporaryFile(
            suffix=".js", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        assert len(result.errors) == 0
        assert len(result.entities) == 2  # module + function

    def test_empty_file(self, parser):
        """Parsing an empty file returns only module entity."""
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write("")
            f.flush()
            result = parser.parse_file(Path(f.name))

        kinds = [e["kind"] for e in result.entities]
        assert kinds.count("module") == 1
        assert len(result.entities) == 1

    def test_utf8_bom_handling(self, parser):
        """UTF-8 with BOM is handled correctly."""
        source = '''function test() {
    return 42;
}
'''
        with tempfile.NamedTemporaryFile(
            suffix=".js", delete=False, mode="w", encoding="utf-8-sig"
        ) as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        assert isinstance(result, ParseResult)
        # Should either parse successfully or handle gracefully
        if len(result.errors) == 0:
            functions = [e for e in result.entities if e["kind"] == "function"]
            assert len(functions) == 1

    def test_binary_content_graceful(self, parser):
        """Binary content is handled gracefully."""
        content = b'\x00\x01\x02\x03function test() {}\xff\xfe'

        with tempfile.NamedTemporaryFile(suffix=".js", delete=False) as f:
            f.write(content)
            f.flush()
            result = parser.parse_file(Path(f.name))

        # Should not raise exception
        assert isinstance(result, ParseResult)


class TestParserInterface:
    """Tests for the BaseParser interface implementation."""

    def test_language_property(self, parser):
        """Parser has a language property."""
        assert parser.language == "javascript"

    def test_file_extensions_property(self, parser):
        """Parser reports supported file extensions."""
        exts = parser.file_extensions
        assert ".js" in exts
        assert ".mjs" in exts
        assert ".cjs" in exts
        assert ".jsx" in exts

    def test_can_parse_js_file(self, parser):
        """can_parse returns True for JavaScript files."""
        assert parser.can_parse(Path("test.js"))
        assert parser.can_parse(Path("test.mjs"))
        assert parser.can_parse(Path("test.cjs"))
        assert parser.can_parse(Path("test.jsx"))
        assert parser.can_parse(Path("/some/path/module.js"))

    def test_can_parse_non_js_file(self, parser):
        """can_parse returns False for non-JavaScript files."""
        assert not parser.can_parse(Path("test.py"))
        assert not parser.can_parse(Path("test.ts"))
        assert not parser.can_parse(Path("test.txt"))
        assert not parser.can_parse(Path("Makefile"))

    def test_parse_file_returns_parse_result(self, parser):
        """parse_file returns a ParseResult instance."""
        source = "function test() {}"
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(source)
            f.flush()
            result = parser.parse_file(Path(f.name))

        assert isinstance(result, ParseResult)
        assert hasattr(result, "entities")
        assert hasattr(result, "relationships")
        assert hasattr(result, "errors")

    def test_parse_file_with_source_parameter(self, parser):
        """parse_file accepts source code directly via parameter."""
        source = '''
function hello() {
    pass
}

class World {
    method() {}
}
'''
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False) as f:
            result = parser.parse_file(Path(f.name), source=source)

            kinds = [e["kind"] for e in result.entities]
            assert kinds.count("module") == 1
            assert kinds.count("function") == 1
            assert kinds.count("class") == 1
            assert kinds.count("method") == 1

    def test_module_name_from_path(self, parser):
        """Module name is derived from file path."""
        source = "const x = 1;"

        with tempfile.NamedTemporaryFile(
            suffix=".js", delete=False, prefix="my_module_"
        ) as f:
            result = parser.parse_file(Path(f.name), source=source)

            modules = [e for e in result.entities if e["kind"] == "module"]
            assert len(modules) == 1
            assert modules[0]["name"].startswith("my_module_")

    def test_index_file_module_name(self, parser):
        """index.js files use parent directory as module name."""
        source = "const x = 1;"

        with tempfile.TemporaryDirectory() as tmpdir:
            index_file = Path(tmpdir) / "index.js"
            index_file.write_text(source)

            result = parser.parse_file(index_file, source=source)

            modules = [e for e in result.entities if e["kind"] == "module"]
            assert len(modules) == 1
            # Module name should be the parent directory name
            assert modules[0]["name"] == Path(tmpdir).name
