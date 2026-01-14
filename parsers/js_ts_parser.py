"""JavaScript and TypeScript parser using tree-sitter."""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import tree_sitter_javascript as tsjs
    import tree_sitter_typescript as tsts
    from tree_sitter import Language, Parser, Node
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

from parsers.base import BaseParser, ParseResult


class JavaScriptParser(BaseParser):
    """Parser for JavaScript source files using tree-sitter."""

    def __init__(self):
        if not TREE_SITTER_AVAILABLE:
            raise ImportError(
                "tree-sitter and tree-sitter-javascript are required. "
                "Install with: pip install tree-sitter tree-sitter-javascript"
            )
        self._language = Language(tsjs.language())
        self._parser = Parser(self._language)

    @property
    def language(self) -> str:
        return "javascript"

    @property
    def file_extensions(self) -> List[str]:
        return [".js", ".mjs", ".cjs", ".jsx"]

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.file_extensions

    def parse_file(self, file_path: Path, source: str = None) -> ParseResult:
        """Parse a JavaScript file and extract entities and relationships."""
        result = ParseResult()

        if source is None:
            try:
                source = self._read_file(file_path)
            except Exception as e:
                result.errors.append(f"Failed to read {file_path}: {e}")
                return result

        try:
            tree = self._parser.parse(source.encode('utf-8'))
        except Exception as e:
            result.errors.append(f"Parse error in {file_path}: {e}")
            return result

        module_name = self._compute_module_name(file_path)
        self._extract_entities(tree.root_node, source, module_name, str(file_path), result)

        return result

    def _read_file(self, file_path: Path) -> str:
        """Read file with encoding handling."""
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
        for encoding in encodings:
            try:
                return file_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return file_path.read_text(encoding="utf-8", errors="ignore")

    def _compute_module_name(self, file_path: Path) -> str:
        """Compute module name from file path."""
        stem = file_path.stem
        if stem == "index":
            return file_path.parent.name
        return stem

    def _get_node_text(self, node: 'Node', source: str) -> str:
        """Get text content of a node."""
        return source[node.start_byte:node.end_byte]

    def _find_child(self, node: 'Node', type_name: str) -> Optional['Node']:
        """Find first child with given type."""
        for child in node.children:
            if child.type == type_name:
                return child
        return None

    def _find_children(self, node: 'Node', type_name: str) -> List['Node']:
        """Find all children with given type."""
        return [c for c in node.children if c.type == type_name]

    def _extract_docstring(self, node: 'Node', source: str) -> Optional[str]:
        """Extract JSDoc comment preceding a node."""
        # Look for a comment sibling before this node
        parent = node.parent
        if parent is None:
            return None

        prev_sibling = None
        for child in parent.children:
            if child == node:
                break
            if child.type == 'comment':
                prev_sibling = child
            elif child.type not in ('comment',):
                prev_sibling = None

        if prev_sibling and prev_sibling.type == 'comment':
            comment_text = self._get_node_text(prev_sibling, source)
            if comment_text.startswith('/**'):
                # Strip JSDoc markers
                lines = comment_text.split('\n')
                cleaned = []
                for line in lines:
                    line = line.strip()
                    if line.startswith('/**'):
                        line = line[3:].strip()
                    if line.endswith('*/'):
                        line = line[:-2].strip()
                    if line.startswith('*'):
                        line = line[1:].strip()
                    if line:
                        cleaned.append(line)
                return ' '.join(cleaned) if cleaned else None

        return None

    def _build_signature(self, params_node: Optional['Node'], source: str) -> str:
        """Build a function signature from formal_parameters node."""
        if params_node is None:
            return "()"

        params = []
        for child in params_node.children:
            if child.type in ('identifier', 'required_parameter', 'optional_parameter',
                              'rest_pattern', 'assignment_pattern'):
                param_text = self._get_node_text(child, source)
                # Simplify type annotations for readability
                if ':' in param_text:
                    param_text = param_text.split(':')[0].strip()
                params.append(param_text)

        return f"({', '.join(params)})"

    def _extract_entities(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        parent_class: str = None,
    ) -> None:
        """Extract entities from AST node recursively."""

        # Module entity (only at root)
        if node.type == 'program':
            result.entities.append({
                "name": module_name,
                "kind": "module",
                "file": file_path,
                "start_line": 1,
                "end_line": node.end_point[0] + 1,
                "intent": None,
                "code": None,
                "metadata": {"file_path": file_path, "language": self.language},
            })
            # Extract module-level calls (including DOM references)
            self._extract_calls(node, source, module_name, result)

        for child in node.children:
            if child.type == 'function_declaration':
                self._extract_function(child, source, module_name, file_path, result)

            elif child.type == 'class_declaration':
                self._extract_class(child, source, module_name, file_path, result)

            elif child.type == 'lexical_declaration' or child.type == 'variable_declaration':
                # Check for arrow function or function expression assignments
                for declarator in self._find_children(child, 'variable_declarator'):
                    self._extract_variable_function(declarator, source, module_name, file_path, result)
                    # Check for CommonJS require()
                    self._extract_require(declarator, source, module_name, result)

            elif child.type == 'import_statement':
                self._extract_import(child, source, module_name, result)

            elif child.type == 'export_statement':
                self._extract_export(child, source, module_name, file_path, result)

    def _extract_function(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        exported: bool = False,
        is_default: bool = False,
    ) -> None:
        """Extract a function declaration."""
        name_node = self._find_child(node, 'identifier')
        if name_node is None:
            return

        func_name = self._get_node_text(name_node, source)
        qualified_name = f"{module_name}.{func_name}"
        docstring = self._extract_docstring(node, source)
        params_node = self._find_child(node, 'formal_parameters')
        signature = self._build_signature(params_node, source)
        code = self._get_node_text(node, source)

        is_async = any(c.type == 'async' for c in node.children)

        result.entities.append({
            "name": qualified_name,
            "kind": "function",
            "file": file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "intent": docstring,
            "code": code,
            "metadata": {
                "lineno": node.start_point[0] + 1,
                "end_lineno": node.end_point[0] + 1,
                "is_async": is_async,
                "signature": signature,
                "exported": exported,
                "is_default_export": is_default,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        # Add exports relationship if exported
        if exported:
            result.relationships.append((module_name, qualified_name, "exports", {
                'name': func_name,
                'is_default': is_default
            }))

        # Extract calls from function body
        body = self._find_child(node, 'statement_block')
        if body:
            self._extract_calls(body, source, qualified_name, result)

    def _extract_variable_function(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        exported: bool = False,
        is_default: bool = False,
    ) -> None:
        """Extract arrow functions or function expressions assigned to variables."""
        name_node = self._find_child(node, 'identifier')
        if name_node is None:
            return

        # Check for arrow_function or function_expression
        func_node = None
        for child in node.children:
            if child.type in ('arrow_function', 'function_expression', 'function'):
                func_node = child
                break

        if func_node is None:
            return

        func_name = self._get_node_text(name_node, source)
        qualified_name = f"{module_name}.{func_name}"
        docstring = self._extract_docstring(node.parent, source)  # Check parent (declaration)
        params_node = self._find_child(func_node, 'formal_parameters')
        if params_node is None:
            # Arrow functions can have single identifier as parameter
            for c in func_node.children:
                if c.type == 'identifier':
                    params_node = c
                    break
        signature = self._build_signature(params_node, source) if params_node and params_node.type == 'formal_parameters' else "()"
        code = self._get_node_text(node.parent, source)  # Include const/let declaration

        is_async = any(c.type == 'async' for c in func_node.children)

        result.entities.append({
            "name": qualified_name,
            "kind": "function",
            "file": file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "intent": docstring,
            "code": code,
            "metadata": {
                "lineno": node.start_point[0] + 1,
                "end_lineno": node.end_point[0] + 1,
                "is_async": is_async,
                "is_arrow": func_node.type == 'arrow_function',
                "signature": signature,
                "exported": exported,
                "is_default_export": is_default,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        # Add exports relationship if exported
        if exported:
            result.relationships.append((module_name, qualified_name, "exports", {
                'name': func_name,
                'is_default': is_default
            }))

        # Extract calls from function body
        body = self._find_child(func_node, 'statement_block')
        if body:
            self._extract_calls(body, source, qualified_name, result)

    def _extract_class(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        exported: bool = False,
        is_default: bool = False,
    ) -> None:
        """Extract a class declaration and its methods."""
        name_node = self._find_child(node, 'identifier') or self._find_child(node, 'type_identifier')
        if name_node is None:
            return

        class_name = self._get_node_text(name_node, source)
        qualified_name = f"{module_name}.{class_name}"
        docstring = self._extract_docstring(node, source)
        code = self._get_node_text(node, source)

        # Extract base classes
        bases = []
        heritage = self._find_child(node, 'class_heritage')
        if heritage:
            for clause in heritage.children:
                if clause.type == 'extends_clause':
                    for c in clause.children:
                        if c.type in ('identifier', 'type_identifier'):
                            bases.append(self._get_node_text(c, source))

        body = self._find_child(node, 'class_body')
        method_names = []
        if body:
            for child in body.children:
                if child.type == 'method_definition':
                    prop_node = self._find_child(child, 'property_identifier')
                    if prop_node:
                        method_names.append(self._get_node_text(prop_node, source))

        result.entities.append({
            "name": qualified_name,
            "kind": "class",
            "file": file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "intent": docstring,
            "code": code,
            "metadata": {
                "lineno": node.start_point[0] + 1,
                "end_lineno": node.end_point[0] + 1,
                "bases": bases,
                "methods": method_names,
                "exported": exported,
                "is_default_export": is_default,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        # Add exports relationship if exported
        if exported:
            result.relationships.append((module_name, qualified_name, "exports", {
                'name': class_name,
                'is_default': is_default
            }))

        # Extract methods
        if body:
            for child in body.children:
                if child.type == 'method_definition':
                    self._extract_method(child, source, qualified_name, file_path, result)

    def _extract_method(
        self,
        node: 'Node',
        source: str,
        class_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract a method definition."""
        name_node = self._find_child(node, 'property_identifier')
        if name_node is None:
            return

        method_name = self._get_node_text(name_node, source)
        qualified_name = f"{class_name}.{method_name}"
        docstring = self._extract_docstring(node, source)
        params_node = self._find_child(node, 'formal_parameters')
        signature = self._build_signature(params_node, source)
        code = self._get_node_text(node, source)

        is_async = any(c.type == 'async' for c in node.children)
        is_static = any(c.type == 'static' for c in node.children)

        result.entities.append({
            "name": qualified_name,
            "kind": "method",
            "file": file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "intent": docstring,
            "code": code,
            "metadata": {
                "file": file_path,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "signature": signature,
                "is_async": is_async,
                "is_static": is_static,
            },
        })

        result.relationships.append((qualified_name, class_name, "member_of"))

        # Extract calls from method body
        body = self._find_child(node, 'statement_block')
        if body:
            self._extract_calls(body, source, qualified_name, result)

    def _extract_import(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        result: ParseResult,
    ) -> None:
        """Extract import statements with detailed specifiers.

        Handles:
        - import { foo, bar } from './utils';  (named imports)
        - import * as lodash from 'lodash';    (namespace imports)
        - import React from 'react';           (default imports)
        - import React, { useState } from 'react';  (default + named)
        """
        # Find the string node containing the module path
        string_node = self._find_child(node, 'string')
        if string_node is None:
            return

        # Get the actual module path from the string
        module_path = self._get_node_text(string_node, source)
        # Remove quotes
        module_path = module_path.strip("'\"")

        # Extract import specifiers
        import_clause = self._find_child(node, 'import_clause')
        specifiers = []

        if import_clause:
            for child in import_clause.children:
                if child.type == 'identifier':
                    # Default import: import React from 'react'
                    specifiers.append({
                        'name': self._get_node_text(child, source),
                        'type': 'default'
                    })
                elif child.type == 'namespace_import':
                    # Namespace import: import * as lodash from 'lodash'
                    ident = self._find_child(child, 'identifier')
                    if ident:
                        specifiers.append({
                            'name': self._get_node_text(ident, source),
                            'type': 'namespace'
                        })
                elif child.type == 'named_imports':
                    # Named imports: import { foo, bar } from './utils'
                    for spec in child.children:
                        if spec.type == 'import_specifier':
                            # Could have alias: import { foo as f } from './utils'
                            identifiers = self._find_children(spec, 'identifier')
                            if len(identifiers) >= 2:
                                # Has alias
                                specifiers.append({
                                    'name': self._get_node_text(identifiers[1], source),
                                    'original': self._get_node_text(identifiers[0], source),
                                    'type': 'named'
                                })
                            elif len(identifiers) == 1:
                                specifiers.append({
                                    'name': self._get_node_text(identifiers[0], source),
                                    'type': 'named'
                                })

        # Add the import relationship with specifiers metadata
        result.relationships.append((module_name, module_path, "imports", {
            'specifiers': specifiers
        }))

    def _extract_require(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        result: ParseResult,
    ) -> None:
        """Extract CommonJS require() statements.

        Handles:
        - const fs = require('fs');
        - const { readFile } = require('fs/promises');
        """
        # Check if this is a require() call
        call_expr = None
        var_name = None
        destructured = []

        for child in node.children:
            if child.type == 'identifier':
                var_name = self._get_node_text(child, source)
            elif child.type == 'object_pattern':
                # Destructured require: const { readFile } = require('fs/promises')
                for prop in child.children:
                    if prop.type == 'shorthand_property_identifier_pattern':
                        destructured.append(self._get_node_text(prop, source))
                    elif prop.type == 'pair_pattern':
                        # Handle { original: alias } pattern
                        key = self._find_child(prop, 'property_identifier')
                        value = self._find_child(prop, 'identifier')
                        if key and value:
                            destructured.append({
                                'name': self._get_node_text(value, source),
                                'original': self._get_node_text(key, source)
                            })
            elif child.type == 'call_expression':
                func = self._find_child(child, 'identifier')
                if func and self._get_node_text(func, source) == 'require':
                    call_expr = child

        if call_expr is None:
            return

        # Get the module path from require arguments
        args = self._find_child(call_expr, 'arguments')
        if args is None:
            return

        string_node = self._find_child(args, 'string')
        if string_node is None:
            return

        module_path = self._get_node_text(string_node, source).strip("'\"")

        # Build specifiers
        specifiers = []
        if destructured:
            for item in destructured:
                if isinstance(item, dict):
                    specifiers.append({
                        'name': item['name'],
                        'original': item['original'],
                        'type': 'named'
                    })
                else:
                    specifiers.append({
                        'name': item,
                        'type': 'named'
                    })
        elif var_name:
            specifiers.append({
                'name': var_name,
                'type': 'default'
            })

        result.relationships.append((module_name, module_path, "imports", {
            'specifiers': specifiers,
            'style': 'commonjs'
        }))

    def _extract_export(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract export statements.

        Handles:
        - export function foo() {}              (exported function)
        - export default class Bar {}           (default exported class)
        - export { baz, qux };                  (named exports)
        - export { default as myDefault } from './module';  (re-exports)
        """
        is_default = any(c.type == 'default' for c in node.children)

        # Check for exported declarations (function, class, variable)
        for subchild in node.children:
            if subchild.type == 'function_declaration':
                self._extract_function(subchild, source, module_name, file_path, result, exported=True, is_default=is_default)
            elif subchild.type == 'class_declaration':
                self._extract_class(subchild, source, module_name, file_path, result, exported=True, is_default=is_default)
            elif subchild.type in ('lexical_declaration', 'variable_declaration'):
                for declarator in self._find_children(subchild, 'variable_declarator'):
                    self._extract_variable_function(declarator, source, module_name, file_path, result, exported=True, is_default=is_default)

        # Check for export clause (named exports or re-exports)
        export_clause = self._find_child(node, 'export_clause')
        if export_clause:
            # Check if this is a re-export (has 'from' clause)
            string_node = self._find_child(node, 'string')
            source_module = None
            if string_node:
                source_module = self._get_node_text(string_node, source).strip("'\"")

            for spec in export_clause.children:
                if spec.type == 'export_specifier':
                    # Get exported name (possibly with alias)
                    identifiers = self._find_children(spec, 'identifier')
                    default_node = self._find_child(spec, 'default')

                    if default_node:
                        # export { default as alias } from './module'
                        if identifiers:
                            exported_name = self._get_node_text(identifiers[0], source)
                            original_name = 'default'
                        else:
                            continue
                    elif len(identifiers) >= 2:
                        # export { original as alias }
                        original_name = self._get_node_text(identifiers[0], source)
                        exported_name = self._get_node_text(identifiers[1], source)
                    elif len(identifiers) == 1:
                        # export { name }
                        original_name = self._get_node_text(identifiers[0], source)
                        exported_name = original_name
                    else:
                        continue

                    if source_module:
                        # Re-export from another module
                        result.relationships.append((module_name, source_module, "re_exports", {
                            'name': exported_name,
                            'original': original_name
                        }))
                    else:
                        # Local named export
                        qualified_name = f"{module_name}.{original_name}"
                        result.relationships.append((module_name, qualified_name, "exports", {
                            'name': exported_name,
                            'original': original_name,
                            'is_default': False
                        }))

    def _extract_calls(
        self,
        node: 'Node',
        source: str,
        caller_name: str,
        result: ParseResult,
    ) -> None:
        """Extract function calls from a node recursively."""
        if node.type == 'call_expression':
            func = self._find_child(node, 'identifier')
            if func:
                callee = self._get_node_text(func, source)
                result.relationships.append((caller_name, callee, "calls"))
            else:
                # Member expression call
                member = self._find_child(node, 'member_expression')
                if member:
                    prop = self._find_child(member, 'property_identifier')
                    if prop:
                        callee = self._get_node_text(prop, source)
                        result.relationships.append((caller_name, callee, "calls"))

                        # Check for DOM reference methods
                        self._extract_dom_reference(node, member, prop, source, caller_name, result)

                        # Track method call with object context for validation
                        self._extract_method_call(node, member, prop, source, caller_name, result)

        elif node.type == 'new_expression':
            # Handle `new ClassName()` - this calls the constructor
            # The class name can be an identifier or member expression
            for child in node.children:
                if child.type == 'identifier':
                    class_name = self._get_node_text(child, source)
                    # Track as call to constructor
                    result.relationships.append((caller_name, class_name, "calls"))
                    result.relationships.append((caller_name, "constructor", "calls"))
                    break
                elif child.type == 'member_expression':
                    # e.g., `new Module.ClassName()`
                    prop = self._find_child(child, 'property_identifier')
                    if prop:
                        class_name = self._get_node_text(prop, source)
                        result.relationships.append((caller_name, class_name, "calls"))
                        result.relationships.append((caller_name, "constructor", "calls"))
                    break

        for child in node.children:
            self._extract_calls(child, source, caller_name, result)

    def _get_member_expression_path(self, node: 'Node', source: str) -> List[str]:
        """Recursively extract the full path of a member expression.

        For `a.b.c`, returns ['a', 'b', 'c'].
        """
        parts = []
        current = node

        while current:
            if current.type == 'identifier':
                parts.insert(0, self._get_node_text(current, source))
                break
            elif current.type == 'member_expression':
                prop = self._find_child(current, 'property_identifier')
                if prop:
                    parts.insert(0, self._get_node_text(prop, source))
                # Move to the object part
                obj = None
                for child in current.children:
                    if child.type in ('identifier', 'member_expression', 'this'):
                        obj = child
                        break
                current = obj
            elif current.type == 'this':
                parts.insert(0, 'this')
                break
            else:
                break

        return parts

    def _extract_method_call(
        self,
        call_node: 'Node',
        member_node: 'Node',
        prop_node: 'Node',
        source: str,
        caller_name: str,
        result: ParseResult,
    ) -> None:
        """Extract method call with object context for validation.

        Tracks calls like `obj.method()` or `a.b.c.method()` to enable
        validation that the method exists on the target type.
        """
        method_name = self._get_node_text(prop_node, source)
        line_num = call_node.start_point[0] + 1

        # Get the object path (everything before the method)
        obj_path = self._get_member_expression_path(member_node, source)
        if obj_path:
            # Remove the method name (last element) if it got included
            if obj_path and obj_path[-1] == method_name:
                obj_path = obj_path[:-1]

        # Only track if we have an object path
        if not obj_path:
            return

        # Get the immediate object (last part of path before method)
        immediate_object = obj_path[-1] if obj_path else None

        # Store as a method_call reference for validation
        result.relationships.append((caller_name, method_name, "method_call", {
            'method': method_name,
            'object_path': obj_path,
            'full_expression': '.'.join(obj_path + [method_name]),
            'immediate_object': immediate_object,
            'line': line_num,
            'verifiable': True  # Can be verified against class definitions
        }))

    def _extract_dom_reference(
        self,
        call_node: 'Node',
        member_node: 'Node',
        prop_node: 'Node',
        source: str,
        caller_name: str,
        result: ParseResult,
    ) -> None:
        """Extract DOM element references from getElementById/querySelector calls.

        Tracks:
        - Static references: getElementById('myId') -> dom_reference relationship
        - Dynamic references: getElementById(variable) -> unverifiable_dom_reference
        """
        method_name = self._get_node_text(prop_node, source)

        # Check if this is a DOM query method
        if method_name not in ('getElementById', 'querySelector', 'querySelectorAll'):
            return

        # Verify it's called on document (or could be element for querySelector*)
        obj_node = None
        for child in member_node.children:
            if child.type == 'identifier':
                obj_node = child
                break
            elif child.type == 'member_expression':
                # Could be window.document or similar
                obj_node = child
                break

        # Get the arguments
        args_node = self._find_child(call_node, 'arguments')
        if args_node is None:
            return

        # Find the first argument
        first_arg = None
        for child in args_node.children:
            if child.type in ('string', 'template_string', 'identifier', 'member_expression'):
                first_arg = child
                break

        if first_arg is None:
            return

        line_num = call_node.start_point[0] + 1

        if first_arg.type == 'string':
            # Static string - we can verify this
            selector = self._get_node_text(first_arg, source).strip("'\"")

            # Extract the ID from the selector
            element_id = None
            if method_name == 'getElementById':
                element_id = selector
            elif method_name in ('querySelector', 'querySelectorAll'):
                # Extract ID from CSS selector like '#myId' or '#myId .child'
                if selector.startswith('#'):
                    # Get just the ID part (stop at space, dot, bracket, etc.)
                    id_match = selector[1:].split()[0] if ' ' in selector else selector[1:]
                    for delim in ('.', '[', ':', '>'):
                        if delim in id_match:
                            id_match = id_match.split(delim)[0]
                    element_id = id_match

            if element_id:
                result.relationships.append((caller_name, element_id, "dom_reference", {
                    'method': method_name,
                    'selector': selector,
                    'line': line_num,
                    'verifiable': True
                }))

        elif first_arg.type == 'template_string':
            # Template string - may contain dynamic parts
            template_text = self._get_node_text(first_arg, source)
            has_interpolation = '${' in template_text

            if has_interpolation:
                # Dynamic - cannot verify
                result.relationships.append((caller_name, template_text, "dom_reference", {
                    'method': method_name,
                    'selector': template_text,
                    'line': line_num,
                    'verifiable': False,
                    'reason': 'Template string with interpolation'
                }))
            else:
                # Static template string (no interpolation)
                selector = template_text.strip('`')
                element_id = None
                if method_name == 'getElementById':
                    element_id = selector
                elif selector.startswith('#'):
                    element_id = selector[1:].split()[0]

                if element_id:
                    result.relationships.append((caller_name, element_id, "dom_reference", {
                        'method': method_name,
                        'selector': selector,
                        'line': line_num,
                        'verifiable': True
                    }))

        else:
            # Variable or expression - cannot verify statically
            arg_text = self._get_node_text(first_arg, source)
            result.relationships.append((caller_name, arg_text, "dom_reference", {
                'method': method_name,
                'selector': arg_text,
                'line': line_num,
                'verifiable': False,
                'reason': 'Dynamic value (variable or expression)'
            }))


class TypeScriptParser(JavaScriptParser):
    """Parser for TypeScript source files using tree-sitter."""

    def __init__(self):
        if not TREE_SITTER_AVAILABLE:
            raise ImportError(
                "tree-sitter and tree-sitter-typescript are required. "
                "Install with: pip install tree-sitter tree-sitter-typescript"
            )
        self._language = Language(tsts.language_typescript())
        self._parser = Parser(self._language)

    @property
    def language(self) -> str:
        return "typescript"

    @property
    def file_extensions(self) -> List[str]:
        return [".ts", ".tsx"]

    def _extract_entities(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        parent_class: str = None,
    ) -> None:
        """Extract entities from TypeScript AST node."""
        # Call parent implementation for common constructs
        super()._extract_entities(node, source, module_name, file_path, result, parent_class)

        # Handle TypeScript-specific constructs
        for child in node.children:
            if child.type == 'interface_declaration':
                self._extract_interface(child, source, module_name, file_path, result)
            elif child.type == 'type_alias_declaration':
                self._extract_type_alias(child, source, module_name, file_path, result)
            elif child.type == 'enum_declaration':
                self._extract_enum(child, source, module_name, file_path, result)
            elif child.type == 'export_statement':
                # Handle exported TypeScript-specific constructs
                self._extract_ts_export(child, source, module_name, file_path, result)

    def _extract_ts_export(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract TypeScript-specific constructs from export statements."""
        is_default = any(c.type == 'default' for c in node.children)

        for subchild in node.children:
            if subchild.type == 'interface_declaration':
                self._extract_interface(subchild, source, module_name, file_path, result, exported=True, is_default=is_default)
            elif subchild.type == 'type_alias_declaration':
                self._extract_type_alias(subchild, source, module_name, file_path, result, exported=True, is_default=is_default)
            elif subchild.type == 'enum_declaration':
                self._extract_enum(subchild, source, module_name, file_path, result, exported=True, is_default=is_default)

    def _extract_interface(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        exported: bool = False,
        is_default: bool = False,
    ) -> None:
        """Extract a TypeScript interface declaration."""
        name_node = self._find_child(node, 'type_identifier')
        if name_node is None:
            return

        interface_name = self._get_node_text(name_node, source)
        qualified_name = f"{module_name}.{interface_name}"
        docstring = self._extract_docstring(node, source)
        code = self._get_node_text(node, source)

        # Extract properties
        body = self._find_child(node, 'interface_body') or self._find_child(node, 'object_type')
        properties = []
        if body:
            for child in body.children:
                if child.type == 'property_signature':
                    prop_node = self._find_child(child, 'property_identifier')
                    if prop_node:
                        properties.append(self._get_node_text(prop_node, source))

        result.entities.append({
            "name": qualified_name,
            "kind": "interface",
            "file": file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "intent": docstring,
            "code": code,
            "metadata": {
                "lineno": node.start_point[0] + 1,
                "end_lineno": node.end_point[0] + 1,
                "properties": properties,
                "exported": exported,
                "is_default_export": is_default,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        if exported:
            result.relationships.append((module_name, qualified_name, "exports", {
                'name': interface_name,
                'is_default': is_default
            }))

    def _extract_type_alias(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        exported: bool = False,
        is_default: bool = False,
    ) -> None:
        """Extract a TypeScript type alias declaration."""
        name_node = self._find_child(node, 'type_identifier')
        if name_node is None:
            return

        type_name = self._get_node_text(name_node, source)
        qualified_name = f"{module_name}.{type_name}"
        docstring = self._extract_docstring(node, source)
        code = self._get_node_text(node, source)

        result.entities.append({
            "name": qualified_name,
            "kind": "type",
            "file": file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "intent": docstring,
            "code": code,
            "metadata": {
                "lineno": node.start_point[0] + 1,
                "end_lineno": node.end_point[0] + 1,
                "exported": exported,
                "is_default_export": is_default,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        if exported:
            result.relationships.append((module_name, qualified_name, "exports", {
                'name': type_name,
                'is_default': is_default
            }))

    def _extract_enum(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        exported: bool = False,
        is_default: bool = False,
    ) -> None:
        """Extract a TypeScript enum declaration."""
        name_node = self._find_child(node, 'identifier')
        if name_node is None:
            return

        enum_name = self._get_node_text(name_node, source)
        qualified_name = f"{module_name}.{enum_name}"
        docstring = self._extract_docstring(node, source)
        code = self._get_node_text(node, source)

        # Extract enum members
        body = self._find_child(node, 'enum_body')
        members = []
        if body:
            for child in body.children:
                if child.type == 'enum_assignment':
                    member_node = self._find_child(child, 'property_identifier')
                    if member_node:
                        members.append(self._get_node_text(member_node, source))
                elif child.type == 'property_identifier':
                    members.append(self._get_node_text(child, source))

        result.entities.append({
            "name": qualified_name,
            "kind": "enum",
            "file": file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "intent": docstring,
            "code": code,
            "metadata": {
                "lineno": node.start_point[0] + 1,
                "end_lineno": node.end_point[0] + 1,
                "members": members,
                "exported": exported,
                "is_default_export": is_default,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        if exported:
            result.relationships.append((module_name, qualified_name, "exports", {
                'name': enum_name,
                'is_default': is_default
            }))
