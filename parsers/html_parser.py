"""HTML parser using tree-sitter for DOM element extraction."""

import logging
from pathlib import Path
from typing import List, Optional

try:
    from tree_sitter_language_pack import get_language, get_parser
    from tree_sitter import Node
    TREE_SITTER_HTML_AVAILABLE = True
except ImportError:
    TREE_SITTER_HTML_AVAILABLE = False

from parsers.base import BaseParser, ParseResult


class HTMLParser(BaseParser):
    """Parser for HTML files using tree-sitter.

    Extracts DOM elements with IDs as entities, enabling cross-language
    validation between HTML and JavaScript (e.g., detecting getElementById
    calls that reference non-existent elements).
    """

    def __init__(self):
        if not TREE_SITTER_HTML_AVAILABLE:
            raise ImportError(
                "tree-sitter-language-pack is required for HTML support. "
                "Install with: pip install tree-sitter-language-pack"
            )
        self._parser = get_parser("html")

    @property
    def language(self) -> str:
        return "html"

    @property
    def file_extensions(self) -> List[str]:
        return [".html", ".htm"]

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.file_extensions

    def parse_file(self, file_path: Path, source: str = None) -> ParseResult:
        """Parse an HTML file and extract DOM elements with IDs."""
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

        module_name = file_path.stem

        # Add module entity for the HTML file itself
        result.entities.append({
            "name": module_name,
            "kind": "module",
            "file": str(file_path),
            "start_line": 1,
            "end_line": tree.root_node.end_point[0] + 1,
            "intent": None,
            "code": None,
            "metadata": {"file_path": str(file_path), "language": self.language},
        })

        # Extract DOM elements and relationships
        self._extract_elements(tree.root_node, source, module_name, str(file_path), result)

        return result

    def _read_file(self, file_path: Path) -> str:
        """Read file with encoding handling."""
        encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
        for encoding in encodings:
            try:
                content = file_path.read_text(encoding=encoding)
                if content.startswith('\ufeff'):
                    content = content[1:]
                return content
            except UnicodeDecodeError:
                continue
        return file_path.read_text(encoding="utf-8", errors="ignore")

    def _get_node_text(self, node: 'Node', source: str) -> str:
        """Get text content of a node."""
        return source[node.start_byte:node.end_byte]

    def _find_children(self, node: 'Node', type_name: str) -> List['Node']:
        """Find all children with given type."""
        return [c for c in node.children if c.type == type_name]

    def _extract_elements(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract DOM elements with IDs recursively."""

        # Handle element nodes (including self-closing)
        if node.type in ('element', 'self_closing_tag'):
            self._extract_element(node, source, module_name, file_path, result)

        # Handle script elements - extract src references
        elif node.type == 'script_element':
            self._extract_script_reference(node, source, module_name, result)

        # Handle link elements - extract href references (for CSS)
        elif node.type == 'style_element':
            pass  # Could extract inline styles if needed

        # Recurse into children
        for child in node.children:
            self._extract_elements(child, source, module_name, file_path, result)

    def _extract_element(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract a single DOM element if it has an ID."""

        # Find start_tag or self_closing_tag
        start_tag = None
        for child in node.children:
            if child.type in ('start_tag', 'self_closing_tag'):
                start_tag = child
                break

        if start_tag is None and node.type == 'self_closing_tag':
            start_tag = node

        if start_tag is None:
            return

        # Extract tag name
        tag_name = None
        for child in start_tag.children:
            if child.type == 'tag_name':
                tag_name = self._get_node_text(child, source)
                break

        if tag_name is None:
            return

        # Extract attributes
        element_id = None
        element_classes = []
        other_attrs = {}

        for child in start_tag.children:
            if child.type == 'attribute':
                attr_name = None
                attr_value = None

                for attr_child in child.children:
                    if attr_child.type == 'attribute_name':
                        attr_name = self._get_node_text(attr_child, source)
                    elif attr_child.type == 'quoted_attribute_value':
                        # Extract value from inside quotes
                        for val_child in attr_child.children:
                            if val_child.type == 'attribute_value':
                                attr_value = self._get_node_text(val_child, source)
                                break
                    elif attr_child.type == 'attribute_value':
                        attr_value = self._get_node_text(attr_child, source)

                if attr_name == 'id' and attr_value:
                    element_id = attr_value
                elif attr_name == 'class' and attr_value:
                    element_classes = attr_value.split()
                elif attr_name and attr_value:
                    other_attrs[attr_name] = attr_value

        # Only create entity if element has an ID
        if element_id:
            qualified_name = f"{module_name}#{element_id}"

            result.entities.append({
                "name": qualified_name,
                "kind": "dom_element",
                "file": file_path,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "intent": f"DOM element <{tag_name}> with id=\"{element_id}\"",
                "code": self._get_node_text(node, source)[:200],  # Truncate for large elements
                "metadata": {
                    "element_id": element_id,
                    "tag_name": tag_name,
                    "classes": element_classes,
                    "attributes": other_attrs,
                    "language": self.language,
                },
            })

            # Relationship: module contains this element
            result.relationships.append((module_name, qualified_name, "contains"))

    def _extract_script_reference(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        result: ParseResult,
    ) -> None:
        """Extract script src references for dependency tracking."""

        # Find start_tag
        start_tag = None
        for child in node.children:
            if child.type == 'start_tag':
                start_tag = child
                break

        if start_tag is None:
            return

        # Look for src attribute
        for child in start_tag.children:
            if child.type == 'attribute':
                attr_name = None
                attr_value = None

                for attr_child in child.children:
                    if attr_child.type == 'attribute_name':
                        attr_name = self._get_node_text(attr_child, source)
                    elif attr_child.type == 'quoted_attribute_value':
                        for val_child in attr_child.children:
                            if val_child.type == 'attribute_value':
                                attr_value = self._get_node_text(val_child, source)
                                break
                    elif attr_child.type == 'attribute_value':
                        attr_value = self._get_node_text(attr_child, source)

                if attr_name == 'src' and attr_value:
                    # Create imports relationship to the script
                    result.relationships.append((module_name, attr_value, "imports", {
                        'import_type': 'script'
                    }))
