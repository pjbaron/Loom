"""ActionScript 3 parser using tree-sitter."""

import logging
from pathlib import Path
from typing import List, Optional

try:
    from tree_sitter_language_pack import get_language, get_parser
    from tree_sitter import Node
    TREE_SITTER_AS3_AVAILABLE = True
except ImportError:
    TREE_SITTER_AS3_AVAILABLE = False

from parsers.base import BaseParser, ParseResult


class ActionScript3Parser(BaseParser):
    """Parser for ActionScript 3 source files using tree-sitter."""

    def __init__(self):
        if not TREE_SITTER_AS3_AVAILABLE:
            raise ImportError(
                "tree-sitter-language-pack is required for ActionScript 3 support. "
                "Install with: pip install tree-sitter-language-pack"
            )
        self._parser = get_parser("actionscript")

    @property
    def language(self) -> str:
        return "actionscript3"

    @property
    def file_extensions(self) -> List[str]:
        return [".as"]

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.file_extensions

    def parse_file(self, file_path: Path, source: str = None) -> ParseResult:
        """Parse an ActionScript 3 file and extract entities and relationships."""
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
        # Try utf-8-sig first to properly handle BOM
        encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
        for encoding in encodings:
            try:
                content = file_path.read_text(encoding=encoding)
                # Also strip BOM manually if still present
                if content.startswith('\ufeff'):
                    content = content[1:]
                return content
            except UnicodeDecodeError:
                continue
        return file_path.read_text(encoding="utf-8", errors="ignore")

    def _compute_module_name(self, file_path: Path) -> str:
        """Compute module name from file path."""
        return file_path.stem

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

    def _find_child_any(self, node: 'Node', type_names: List[str]) -> Optional['Node']:
        """Find first child matching any of the given types."""
        for child in node.children:
            if child.type in type_names:
                return child
        return None

    def _extract_docstring(self, node: 'Node', source: str) -> Optional[str]:
        """Extract ASDoc comment preceding a node."""
        parent = node.parent
        if parent is None:
            return None

        prev_sibling = None
        for child in parent.children:
            if child == node:
                break
            if child.type in ('block_comment', 'multiline_comment', 'comment'):
                prev_sibling = child
            elif child.type not in ('block_comment', 'multiline_comment', 'comment',
                                    'line_comment', 'class_attribut', 'property_attribut'):
                prev_sibling = None

        if prev_sibling:
            comment_text = self._get_node_text(prev_sibling, source)
            if comment_text.startswith('/**'):
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
                    if line and not line.startswith('@'):
                        cleaned.append(line)
                return ' '.join(cleaned) if cleaned else None

        return None

    def _extract_visibility(self, node: 'Node', source: str) -> str:
        """Extract visibility modifier from a declaration."""
        # Check class_attribut or property_attribut children
        for child in node.children:
            if child.type in ('class_attribut', 'property_attribut'):
                for subchild in child.children:
                    if subchild.type in ('public', 'private', 'protected', 'internal'):
                        return subchild.type
            if child.type in ('public', 'private', 'protected', 'internal'):
                return child.type
        return "internal"  # AS3 default

    def _extract_modifiers(self, node: 'Node', source: str) -> dict:
        """Extract all modifiers (static, override, final, etc.)."""
        modifiers = {
            "visibility": "internal",
            "is_static": False,
            "is_override": False,
            "is_final": False,
        }

        for child in node.children:
            # Handle class_attribut and property_attribut
            if child.type in ('class_attribut', 'property_attribut'):
                for subchild in child.children:
                    text = subchild.type
                    if text in ('public', 'private', 'protected', 'internal'):
                        modifiers["visibility"] = text
                    elif text == 'static':
                        modifiers["is_static"] = True
                    elif text == 'override':
                        modifiers["is_override"] = True
                    elif text == 'final':
                        modifiers["is_final"] = True
            # Direct modifiers
            text = child.type
            if text in ('public', 'private', 'protected', 'internal'):
                modifiers["visibility"] = text
            elif text == 'static':
                modifiers["is_static"] = True
            elif text == 'override':
                modifiers["is_override"] = True
            elif text == 'final':
                modifiers["is_final"] = True

        return modifiers

    def _build_signature(self, params_node: Optional['Node'], source: str) -> str:
        """Build a function signature from parameters node."""
        if params_node is None:
            return "()"

        params = []
        for child in params_node.children:
            if child.type in ('parameter', 'required_parameter', 'optional_parameter',
                              'rest_parameter', 'formal_parameter', 'function_parameter'):
                param_text = self._get_node_text(child, source)
                params.append(param_text)
            elif child.type == 'identifier':
                # Plain identifier parameter
                params.append(self._get_node_text(child, source))

        return f"({', '.join(params)})"

    def _extract_type_annotation(self, node: 'Node', source: str) -> Optional[str]:
        """Extract return type annotation from a function."""
        # Look for type_hint child
        type_hint = self._find_child(node, 'type_hint')
        if type_hint:
            # type_hint contains : and the type
            text = self._get_node_text(type_hint, source)
            return text.lstrip(':').strip()
        return None

    def _extract_entities(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        package_name: str = None,
        parent_class: str = None,
    ) -> None:
        """Extract entities from AST node recursively."""

        # Root program node
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

        for child in node.children:
            # Package declaration
            if child.type == 'package_declaration':
                pkg_name = self._extract_package_name(child, source)
                # Recurse into package body (statement_block)
                body = self._find_child(child, 'statement_block')
                if body:
                    self._extract_entities(body, source, module_name, file_path, result,
                                           package_name=pkg_name, parent_class=parent_class)

            # Import statement
            elif child.type == 'import_statement':
                self._extract_import(child, source, module_name, package_name, result)

            # Class declaration
            elif child.type == 'class_declaration':
                self._extract_class(child, source, module_name, file_path, result,
                                    package_name=package_name)

            # Interface declaration
            elif child.type == 'interface_declaration':
                self._extract_interface(child, source, module_name, file_path, result,
                                        package_name=package_name)

            # Top-level function (rare in AS3 but possible)
            elif child.type == 'function_declaration' and parent_class is None:
                self._extract_function(child, source, module_name, file_path, result,
                                       package_name=package_name)

    def _extract_package_name(self, node: 'Node', source: str) -> Optional[str]:
        """Extract package name from package declaration."""
        # Look for identifier or scoped_identifier after 'package' keyword
        for child in node.children:
            if child.type in ('identifier', 'scoped_identifier', 'scoped_data_type'):
                return self._get_node_text(child, source)
        return None  # Anonymous package

    def _extract_import(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        package_name: str,
        result: ParseResult,
    ) -> None:
        """Extract import statement."""
        # Find the imported path (scoped_data_type)
        import_path = None
        for child in node.children:
            if child.type == 'scoped_data_type':
                import_path = self._get_node_text(child, source)
                break
            if child.type in ('identifier', 'qualified_identifier', 'scoped_identifier'):
                import_path = self._get_node_text(child, source)
                break

        if import_path:
            is_wildcard = import_path.endswith('.*')
            result.relationships.append((module_name, import_path, "imports", {
                'is_wildcard': is_wildcard
            }))

    def _extract_class(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        package_name: str = None,
    ) -> None:
        """Extract a class declaration and its members."""
        # Find class name (identifier after 'class' keyword)
        name_node = self._find_child(node, 'identifier')
        if name_node is None:
            return

        class_name = self._get_node_text(name_node, source)
        if package_name:
            qualified_name = f"{package_name}.{class_name}"
        else:
            qualified_name = f"{module_name}.{class_name}"

        docstring = self._extract_docstring(node, source)
        modifiers = self._extract_modifiers(node, source)
        code = self._get_node_text(node, source)

        # Extract base class (extends)
        bases = []
        extends_node = self._find_child(node, 'extends_clause')
        if extends_node:
            for subchild in extends_node.children:
                if subchild.type in ('identifier', 'scoped_data_type'):
                    bases.append(self._get_node_text(subchild, source))

        # Extract implemented interfaces
        implements = []
        implements_node = self._find_child(node, 'implements_clause')
        if implements_node:
            for subchild in implements_node.children:
                if subchild.type in ('identifier', 'scoped_data_type'):
                    implements.append(self._get_node_text(subchild, source))

        # Find class body (statement_block) and extract method names
        body = self._find_child(node, 'statement_block')
        method_names = []
        if body:
            for child in body.children:
                if child.type == 'function_declaration':
                    method_name_node = self._find_child(child, 'identifier')
                    if method_name_node:
                        method_names.append(self._get_node_text(method_name_node, source))

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
                "visibility": modifiers["visibility"],
                "is_final": modifiers["is_final"],
                "bases": bases,
                "implements": implements,
                "methods": method_names,
                "language": self.language,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        # Extract methods from class body
        if body:
            for child in body.children:
                if child.type == 'function_declaration':
                    self._extract_method(child, source, qualified_name, file_path, result)
                elif child.type in ('getter_declaration', 'setter_declaration',
                                    'get_accessor', 'set_accessor'):
                    self._extract_accessor(child, source, qualified_name, file_path, result)

    def _extract_interface(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        package_name: str = None,
    ) -> None:
        """Extract an interface declaration."""
        name_node = self._find_child(node, 'identifier')
        if name_node is None:
            return

        interface_name = self._get_node_text(name_node, source)
        if package_name:
            qualified_name = f"{package_name}.{interface_name}"
        else:
            qualified_name = f"{module_name}.{interface_name}"

        docstring = self._extract_docstring(node, source)
        modifiers = self._extract_modifiers(node, source)
        code = self._get_node_text(node, source)

        # Extract extended interfaces
        extends = []
        extends_node = self._find_child(node, 'extends_clause')
        if extends_node:
            for subchild in extends_node.children:
                if subchild.type in ('identifier', 'scoped_data_type'):
                    extends.append(self._get_node_text(subchild, source))

        # Extract method signatures from body
        body = self._find_child(node, 'statement_block')
        method_names = []
        if body:
            for child in body.children:
                if child.type == 'function_declaration':
                    method_name_node = self._find_child(child, 'identifier')
                    if method_name_node:
                        method_names.append(self._get_node_text(method_name_node, source))

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
                "visibility": modifiers["visibility"],
                "extends": extends,
                "methods": method_names,
                "language": self.language,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

    def _extract_method(
        self,
        node: 'Node',
        source: str,
        class_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract a method definition."""
        name_node = self._find_child(node, 'identifier')
        if name_node is None:
            return

        method_name = self._get_node_text(name_node, source)
        qualified_name = f"{class_name}.{method_name}"
        docstring = self._extract_docstring(node, source)
        modifiers = self._extract_modifiers(node, source)

        # Find parameters (function_parameters)
        params_node = self._find_child(node, 'function_parameters')
        signature = self._build_signature(params_node, source)

        # Extract return type
        return_type = self._extract_type_annotation(node, source)

        code = self._get_node_text(node, source)

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
                "return_type": return_type,
                "visibility": modifiers["visibility"],
                "is_static": modifiers["is_static"],
                "is_override": modifiers["is_override"],
                "is_final": modifiers["is_final"],
                "language": self.language,
            },
        })

        result.relationships.append((qualified_name, class_name, "member_of"))

        # Extract calls from method body
        body = self._find_child(node, 'statement_block')
        if body:
            self._extract_calls(body, source, qualified_name, result)

    def _extract_accessor(
        self,
        node: 'Node',
        source: str,
        class_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract a getter or setter."""
        is_getter = 'get' in node.type.lower()

        name_node = self._find_child(node, 'identifier')
        if name_node is None:
            return

        property_name = self._get_node_text(name_node, source)
        accessor_type = "get" if is_getter else "set"
        qualified_name = f"{class_name}.{property_name}"
        docstring = self._extract_docstring(node, source)
        modifiers = self._extract_modifiers(node, source)
        code = self._get_node_text(node, source)

        return_type = self._extract_type_annotation(node, source) if is_getter else None

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
                "accessor_type": accessor_type,
                "return_type": return_type,
                "visibility": modifiers["visibility"],
                "is_static": modifiers["is_static"],
                "language": self.language,
            },
        })

        result.relationships.append((qualified_name, class_name, "member_of"))

    def _extract_function(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        package_name: str = None,
    ) -> None:
        """Extract a top-level function declaration."""
        name_node = self._find_child(node, 'identifier')
        if name_node is None:
            return

        func_name = self._get_node_text(name_node, source)
        if package_name:
            qualified_name = f"{package_name}.{func_name}"
        else:
            qualified_name = f"{module_name}.{func_name}"

        docstring = self._extract_docstring(node, source)
        modifiers = self._extract_modifiers(node, source)

        params_node = self._find_child(node, 'function_parameters')
        signature = self._build_signature(params_node, source)
        return_type = self._extract_type_annotation(node, source)
        code = self._get_node_text(node, source)

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
                "signature": signature,
                "return_type": return_type,
                "visibility": modifiers["visibility"],
                "language": self.language,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        body = self._find_child(node, 'statement_block')
        if body:
            self._extract_calls(body, source, qualified_name, result)

    def _extract_calls(
        self,
        node: 'Node',
        source: str,
        caller_name: str,
        result: ParseResult,
    ) -> None:
        """Extract function calls from a node recursively."""
        if node.type == 'call_expression':
            # Find the function/method being called
            func = self._find_child(node, 'identifier')
            if func:
                callee = self._get_node_text(func, source)
                result.relationships.append((caller_name, callee, "calls"))
            else:
                # Check for member expression (obj.method())
                member = self._find_child_any(node, ['member_expression', 'field_expression',
                                                      'member_access', 'property_access'])
                if member:
                    prop = None
                    for child in member.children:
                        if child.type == 'identifier':
                            prop = child
                    if prop:
                        callee = self._get_node_text(prop, source)
                        result.relationships.append((caller_name, callee, "calls"))

        for child in node.children:
            self._extract_calls(child, source, caller_name, result)
