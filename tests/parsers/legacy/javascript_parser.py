from pathlib import Path
from typing import List, Optional
import tree_sitter_javascript as tsjs
from tree_sitter import Language, Parser, Node
from .base import BaseParser, ParseResult

class JavaScriptParser(BaseParser):

    def __init__(self):
        self._language = Language(tsjs.language())
        self._parser = Parser(self._language)

    @property
    def language(self) -> str:
        return 'javascript'

    @property
    def file_extensions(self) -> List[str]:
        return ['.js', '.mjs', '.cjs', '.jsx']

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.file_extensions

    def parse_file(self, file_path: Path, source: str = None) -> ParseResult:
        result = ParseResult()

        # Read file if source not provided
        if source is None:
            try:
                source = file_path.read_text(encoding='utf-8')
            except Exception as e:
                result.errors.append(f'Failed to read {file_path}: {e}')
                return result

        # Parse with tree-sitter
        tree = self._parser.parse(source.encode('utf-8'))

        # Module entity
        module_name = file_path.stem
        result.entities.append({
            'name': module_name,
            'kind': 'module',
            'file': str(file_path),
            'start_line': 1,
            'end_line': source.count('\n') + 1,
            'metadata': {'language': self.language},
            'intent': None
        })

        # Walk tree and extract entities
        self._extract_from_node(tree.root_node, source, file_path, module_name, result)

        return result

    def _extract_jsdoc(self, node: Node, source: str) -> Optional[str]:
        """Extract JSDoc comment preceding a node.

        Looks for comment node before this node. JSDoc starts with /** and ends with */.
        Returns the description portion, stripped of * prefixes.
        """
        parent = node.parent
        if parent is None:
            return None

        # Find the comment node immediately preceding this node
        prev_sibling = None
        for child in parent.children:
            if child == node:
                break
            if child.type == 'comment':
                prev_sibling = child
            elif child.type not in ('comment',):
                # Non-comment node resets the search
                prev_sibling = None

        if prev_sibling is None or prev_sibling.type != 'comment':
            return None

        comment_text = source[prev_sibling.start_byte:prev_sibling.end_byte]

        # Only process JSDoc comments (start with /**)
        if not comment_text.startswith('/**'):
            return None

        # Parse JSDoc to extract description
        lines = comment_text.split('\n')
        description_lines = []

        for line in lines:
            line = line.strip()
            # Remove /** prefix
            if line.startswith('/**'):
                line = line[3:].strip()
            # Remove */ suffix
            if line.endswith('*/'):
                line = line[:-2].strip()
            # Remove leading *
            if line.startswith('*'):
                line = line[1:].strip()

            # Skip empty lines and @-tags (params, returns, etc.)
            if not line or line.startswith('@'):
                continue

            description_lines.append(line)

        return ' '.join(description_lines) if description_lines else None

    def _extract_from_node(self, node, source, file_path, parent_name, result):
        """Recursively extract entities from AST nodes."""

        # Function declarations
        if node.type == 'function_declaration':
            self._extract_function(node, source, file_path, parent_name, result)

        # Arrow functions assigned to variables
        elif node.type == 'lexical_declaration' or node.type == 'variable_declaration':
            self._extract_variable_functions(node, source, file_path, parent_name, result)

        # Class declarations
        elif node.type == 'class_declaration':
            self._extract_class(node, source, file_path, parent_name, result)

        # Export statements (may contain functions/classes)
        elif node.type in ('export_statement', 'export_default_declaration'):
            for child in node.children:
                self._extract_from_node(child, source, file_path, parent_name, result)
            return  # Don't recurse further

        # Recurse into children
        for child in node.children:
            self._extract_from_node(child, source, file_path, parent_name, result)

    def _extract_function(self, node, source, file_path, parent_name, result):
        # Get function name
        name_node = node.child_by_field_name('name')
        if not name_node:
            return

        func_name = source[name_node.start_byte:name_node.end_byte]
        qualified_name = f'{parent_name}.{func_name}'

        # Get parameters
        params_node = node.child_by_field_name('parameters')
        params = source[params_node.start_byte:params_node.end_byte] if params_node else '()'

        # Extract JSDoc comment as intent
        intent = self._extract_jsdoc(node, source)

        result.entities.append({
            'name': qualified_name,
            'kind': 'function',
            'file': str(file_path),
            'start_line': node.start_point[0] + 1,
            'end_line': node.end_point[0] + 1,
            'metadata': {'signature': f'{func_name}{params}', 'language': self.language},
            'intent': intent
        })

        result.relationships.append((parent_name, qualified_name, 'contains'))

        # Extract calls within function body
        self._extract_calls(node, source, qualified_name, result)

    def _extract_class(self, node, source, file_path, parent_name, result):
        name_node = node.child_by_field_name('name')
        if not name_node:
            return

        class_name = source[name_node.start_byte:name_node.end_byte]
        qualified_name = f'{parent_name}.{class_name}'

        # Extract JSDoc comment as intent
        intent = self._extract_jsdoc(node, source)

        result.entities.append({
            'name': qualified_name,
            'kind': 'class',
            'file': str(file_path),
            'start_line': node.start_point[0] + 1,
            'end_line': node.end_point[0] + 1,
            'metadata': {'language': self.language},
            'intent': intent
        })

        result.relationships.append((parent_name, qualified_name, 'contains'))

        # Extract methods from class body
        body_node = node.child_by_field_name('body')
        if body_node:
            for child in body_node.children:
                if child.type == 'method_definition':
                    self._extract_method(child, source, file_path, qualified_name, result)

    def _extract_method(self, node, source, file_path, class_name, result):
        name_node = node.child_by_field_name('name')
        if not name_node:
            return

        method_name = source[name_node.start_byte:name_node.end_byte]
        qualified_name = f'{class_name}.{method_name}'

        params_node = node.child_by_field_name('parameters')
        params = source[params_node.start_byte:params_node.end_byte] if params_node else '()'

        # Extract JSDoc comment as intent
        intent = self._extract_jsdoc(node, source)

        result.entities.append({
            'name': qualified_name,
            'kind': 'method',
            'file': str(file_path),
            'start_line': node.start_point[0] + 1,
            'end_line': node.end_point[0] + 1,
            'metadata': {'signature': f'{method_name}{params}', 'language': self.language},
            'intent': intent
        })

        result.relationships.append((qualified_name, class_name, 'member_of'))
        self._extract_calls(node, source, qualified_name, result)

    def _extract_variable_functions(self, node, source, file_path, parent_name, result):
        """Extract arrow functions assigned to const/let/var."""
        for child in node.children:
            if child.type == 'variable_declarator':
                name_node = child.child_by_field_name('name')
                value_node = child.child_by_field_name('value')

                if name_node and value_node and value_node.type == 'arrow_function':
                    func_name = source[name_node.start_byte:name_node.end_byte]
                    qualified_name = f'{parent_name}.{func_name}'

                    params_node = value_node.child_by_field_name('parameters')
                    if params_node:
                        params = source[params_node.start_byte:params_node.end_byte]
                    else:
                        # Single param without parens
                        params = '(...)'

                    # Extract JSDoc comment - look at the declaration node (const/let/var)
                    intent = self._extract_jsdoc(node, source)

                    result.entities.append({
                        'name': qualified_name,
                        'kind': 'function',
                        'file': str(file_path),
                        'start_line': node.start_point[0] + 1,
                        'end_line': node.end_point[0] + 1,
                        'metadata': {'signature': f'{func_name}{params}', 'arrow': True, 'language': self.language},
                        'intent': intent
                    })

                    result.relationships.append((parent_name, qualified_name, 'contains'))
                    self._extract_calls(value_node, source, qualified_name, result)

    def _extract_calls(self, node, source, caller_name, result):
        """Extract function calls within a node."""
        if node.type == 'call_expression':
            func_node = node.child_by_field_name('function')
            if func_node:
                # Get the called function name
                if func_node.type == 'identifier':
                    callee = source[func_node.start_byte:func_node.end_byte]
                    result.relationships.append((caller_name, callee, 'calls'))
                elif func_node.type == 'member_expression':
                    # obj.method() - extract method name
                    prop = func_node.child_by_field_name('property')
                    if prop:
                        callee = source[prop.start_byte:prop.end_byte]
                        result.relationships.append((caller_name, callee, 'calls'))

        for child in node.children:
            self._extract_calls(child, source, caller_name, result)
