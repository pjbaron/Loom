"""TypeScript parser using tree-sitter - extends JavaScript parser."""

from pathlib import Path
from typing import List, Optional

try:
    import tree_sitter_typescript as tsts
    from tree_sitter import Language, Parser, Node
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

from .base import BaseParser, ParseResult
from .javascript_parser import JavaScriptParser


class TypeScriptParser(JavaScriptParser):
    """TypeScript parser - extends JavaScript parser with TS-specific handling."""

    def __init__(self):
        if not TREE_SITTER_AVAILABLE:
            raise ImportError(
                "tree-sitter and tree-sitter-typescript are required. "
                "Install with: pip install tree-sitter tree-sitter-typescript"
            )
        # Use TypeScript language instead of JavaScript
        self._language = Language(tsts.language_typescript())
        self._parser = Parser(self._language)

    @property
    def language(self) -> str:
        return 'typescript'

    @property
    def file_extensions(self) -> List[str]:
        return ['.ts']

    def _extract_from_node(self, node, source, file_path, parent_name, result):
        """Recursively extract entities from AST nodes, including TS-specific constructs."""

        # Interface declarations (TypeScript-specific)
        if node.type == 'interface_declaration':
            self._extract_interface(node, source, file_path, parent_name, result)

        # Type alias declarations (TypeScript-specific)
        elif node.type == 'type_alias_declaration':
            self._extract_type_alias(node, source, file_path, parent_name, result)

        # Enum declarations (TypeScript-specific)
        elif node.type == 'enum_declaration':
            self._extract_enum(node, source, file_path, parent_name, result)

        # Handle all JavaScript constructs via parent
        else:
            super()._extract_from_node(node, source, file_path, parent_name, result)
            return  # Parent already handles recursion

        # Recurse into children for TS-specific nodes
        for child in node.children:
            self._extract_from_node(child, source, file_path, parent_name, result)

    def _extract_interface(self, node, source, file_path, parent_name, result):
        """Extract TypeScript interface declaration."""
        name_node = node.child_by_field_name('name')
        if not name_node:
            # Fallback: look for type_identifier child
            for child in node.children:
                if child.type == 'type_identifier':
                    name_node = child
                    break
        if not name_node:
            return

        interface_name = source[name_node.start_byte:name_node.end_byte]
        qualified_name = f'{parent_name}.{interface_name}'

        # Extract properties
        properties = []
        body = node.child_by_field_name('body')
        if body:
            for child in body.children:
                if child.type == 'property_signature':
                    prop_name_node = child.child_by_field_name('name')
                    if prop_name_node:
                        properties.append(source[prop_name_node.start_byte:prop_name_node.end_byte])

        # Extract TSDoc comment as intent
        intent = self._extract_jsdoc(node, source)

        result.entities.append({
            'name': qualified_name,
            'kind': 'interface',
            'file': str(file_path),
            'start_line': node.start_point[0] + 1,
            'end_line': node.end_point[0] + 1,
            'metadata': {'properties': properties, 'language': 'typescript'},
            'intent': intent
        })

        result.relationships.append((parent_name, qualified_name, 'contains'))

    def _extract_type_alias(self, node, source, file_path, parent_name, result):
        """Extract TypeScript type alias declaration."""
        name_node = node.child_by_field_name('name')
        if not name_node:
            # Fallback: look for type_identifier child
            for child in node.children:
                if child.type == 'type_identifier':
                    name_node = child
                    break
        if not name_node:
            return

        type_name = source[name_node.start_byte:name_node.end_byte]
        qualified_name = f'{parent_name}.{type_name}'

        # Extract TSDoc comment as intent
        intent = self._extract_jsdoc(node, source)

        result.entities.append({
            'name': qualified_name,
            'kind': 'type',
            'file': str(file_path),
            'start_line': node.start_point[0] + 1,
            'end_line': node.end_point[0] + 1,
            'metadata': {'language': 'typescript'},
            'intent': intent
        })

        result.relationships.append((parent_name, qualified_name, 'contains'))

    def _extract_enum(self, node, source, file_path, parent_name, result):
        """Extract TypeScript enum declaration."""
        name_node = node.child_by_field_name('name')
        if not name_node:
            # Fallback: look for identifier child
            for child in node.children:
                if child.type == 'identifier':
                    name_node = child
                    break
        if not name_node:
            return

        enum_name = source[name_node.start_byte:name_node.end_byte]
        qualified_name = f'{parent_name}.{enum_name}'

        # Extract enum members
        members = []
        body = node.child_by_field_name('body')
        if body:
            for child in body.children:
                if child.type in ('enum_assignment', 'property_identifier'):
                    if child.type == 'enum_assignment':
                        member_node = child.child_by_field_name('name')
                        if member_node:
                            members.append(source[member_node.start_byte:member_node.end_byte])
                    else:
                        members.append(source[child.start_byte:child.end_byte])

        # Extract TSDoc comment as intent
        intent = self._extract_jsdoc(node, source)

        result.entities.append({
            'name': qualified_name,
            'kind': 'enum',
            'file': str(file_path),
            'start_line': node.start_point[0] + 1,
            'end_line': node.end_point[0] + 1,
            'metadata': {'members': members, 'language': 'typescript'},
            'intent': intent
        })

        result.relationships.append((parent_name, qualified_name, 'contains'))


class TSXParser(TypeScriptParser):
    """TSX parser - TypeScript with JSX support."""

    def __init__(self):
        if not TREE_SITTER_AVAILABLE:
            raise ImportError(
                "tree-sitter and tree-sitter-typescript are required. "
                "Install with: pip install tree-sitter tree-sitter-typescript"
            )
        # Use TSX language variant
        self._language = Language(tsts.language_tsx())
        self._parser = Parser(self._language)

    @property
    def language(self) -> str:
        return 'tsx'

    @property
    def file_extensions(self) -> List[str]:
        return ['.tsx']
