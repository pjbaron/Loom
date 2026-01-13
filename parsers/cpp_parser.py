"""C++ parser using tree-sitter with Unreal Engine support."""

import logging
import re
from pathlib import Path
from typing import List, Optional, Dict, Any

try:
    import tree_sitter_cpp as tscpp
    from tree_sitter import Language, Parser, Node
    TREE_SITTER_CPP_AVAILABLE = True
except ImportError:
    TREE_SITTER_CPP_AVAILABLE = False

from parsers.base import BaseParser, ParseResult


class CppParser(BaseParser):
    """Parser for C++ source files using tree-sitter with Unreal Engine support."""

    # Unreal Engine macros that indicate important code constructs
    UE_CLASS_MACROS = {'UCLASS', 'USTRUCT', 'UINTERFACE', 'UENUM'}
    UE_FUNCTION_MACROS = {'UFUNCTION', 'UMETHOD'}
    UE_PROPERTY_MACROS = {'UPROPERTY'}
    UE_GENERATED_MACROS = {'GENERATED_BODY', 'GENERATED_UCLASS_BODY', 'GENERATED_USTRUCT_BODY'}

    def __init__(self):
        if not TREE_SITTER_CPP_AVAILABLE:
            raise ImportError(
                "tree-sitter and tree-sitter-cpp are required. "
                "Install with: pip install tree-sitter tree-sitter-cpp"
            )
        self._language = Language(tscpp.language())
        self._parser = Parser(self._language)

    @property
    def language(self) -> str:
        return "cpp"

    @property
    def file_extensions(self) -> List[str]:
        return [".h", ".hpp", ".hxx", ".h++", ".c", ".cpp", ".cc", ".cxx", ".c++"]

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.file_extensions

    def parse_file(self, file_path: Path, source: str = None) -> ParseResult:
        """Parse a C++ file and extract entities and relationships."""
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

    def _find_child_recursive(self, node: 'Node', type_name: str) -> Optional['Node']:
        """Find first descendant with given type (recursive search)."""
        if node.type == type_name:
            return node
        for child in node.children:
            result = self._find_child_recursive(child, type_name)
            if result:
                return result
        return None

    def _extract_comment(self, node: 'Node', source: str) -> Optional[str]:
        """Extract documentation comment preceding a node."""
        parent = node.parent
        if parent is None:
            return None

        prev_sibling = None
        for child in parent.children:
            if child == node:
                break
            if child.type == 'comment':
                prev_sibling = child
            elif child.type not in ('comment', 'preproc_call', 'preproc_if', 'preproc_ifdef'):
                prev_sibling = None

        if prev_sibling and prev_sibling.type == 'comment':
            comment_text = self._get_node_text(prev_sibling, source)
            return self._clean_comment(comment_text)

        return None

    def _clean_comment(self, comment: str) -> Optional[str]:
        """Clean comment text, handling C-style and C++ style comments."""
        lines = comment.split('\n')
        cleaned = []

        for line in lines:
            line = line.strip()
            # Handle /** ... */ style
            if line.startswith('/**'):
                line = line[3:].strip()
            if line.startswith('/*'):
                line = line[2:].strip()
            if line.endswith('*/'):
                line = line[:-2].strip()
            if line.startswith('*'):
                line = line[1:].strip()
            # Handle // style
            if line.startswith('//'):
                line = line[2:].strip()
                # Handle /// or //! (Doxygen)
                if line.startswith('/') or line.startswith('!'):
                    line = line[1:].strip()
            if line:
                cleaned.append(line)

        return ' '.join(cleaned) if cleaned else None

    def _extract_ue_specifiers(self, node: 'Node', source: str) -> Dict[str, Any]:
        """Extract Unreal Engine macro specifiers from preceding nodes."""
        specifiers = {
            'is_uclass': False,
            'is_ustruct': False,
            'is_ufunction': False,
            'is_uproperty': False,
            'ue_specifiers': [],
        }

        parent = node.parent
        if parent is None:
            return specifiers

        # Look at siblings before this node for UE macros
        for child in parent.children:
            if child == node:
                break
            if child.type in ('expression_statement', 'declaration'):
                text = self._get_node_text(child, source).strip()
                for macro in self.UE_CLASS_MACROS:
                    if text.startswith(macro):
                        specifiers['is_uclass'] = True
                        specifiers['ue_specifiers'].append(self._parse_macro_args(text))
                for macro in self.UE_FUNCTION_MACROS:
                    if text.startswith(macro):
                        specifiers['is_ufunction'] = True
                        specifiers['ue_specifiers'].append(self._parse_macro_args(text))
                for macro in self.UE_PROPERTY_MACROS:
                    if text.startswith(macro):
                        specifiers['is_uproperty'] = True
                        specifiers['ue_specifiers'].append(self._parse_macro_args(text))

        # Also check for UCLASS/USTRUCT in the source line above
        start_line = node.start_point[0]
        if start_line > 0:
            source_lines = source.split('\n')
            for i in range(max(0, start_line - 5), start_line):
                line = source_lines[i].strip()
                for macro in self.UE_CLASS_MACROS:
                    if line.startswith(macro):
                        if macro == 'USTRUCT':
                            specifiers['is_ustruct'] = True
                        else:
                            specifiers['is_uclass'] = True
                        specifiers['ue_specifiers'].append(self._parse_macro_args(line))

        return specifiers

    def _parse_macro_args(self, macro_text: str) -> str:
        """Extract and return the full macro including arguments."""
        # Find the macro and its arguments
        match = re.match(r'(\w+)\s*\(([^)]*)\)', macro_text)
        if match:
            return f"{match.group(1)}({match.group(2)})"
        return macro_text.split('(')[0].strip()

    def _build_signature(self, node: 'Node', source: str) -> str:
        """Build a function signature from a function declarator."""
        params_node = self._find_child(node, 'parameter_list')
        if params_node is None:
            return "()"

        params = []
        for child in params_node.children:
            if child.type == 'parameter_declaration':
                param_text = self._get_node_text(child, source).strip()
                params.append(param_text)
            elif child.type == 'optional_parameter_declaration':
                param_text = self._get_node_text(child, source).strip()
                params.append(param_text)
            elif child.type == 'variadic_parameter_declaration':
                params.append("...")

        return f"({', '.join(params)})"

    def _extract_return_type(self, node: 'Node', source: str) -> str:
        """Extract return type from a function definition."""
        # Try to get primitive_type or type_identifier
        type_node = self._find_child(node, 'primitive_type')
        if type_node is None:
            type_node = self._find_child(node, 'type_identifier')
        if type_node is None:
            type_node = self._find_child(node, 'sized_type_specifier')
        if type_node is None:
            type_node = self._find_child(node, 'template_type')

        if type_node:
            return self._get_node_text(type_node, source)

        # For more complex return types, look at the beginning of the node
        # before the function declarator
        declarator = self._find_child(node, 'function_declarator')
        if declarator and node.start_byte < declarator.start_byte:
            return_type_text = source[node.start_byte:declarator.start_byte].strip()
            # Clean up storage class specifiers
            for spec in ['virtual', 'static', 'inline', 'explicit', 'constexpr']:
                return_type_text = return_type_text.replace(spec, '').strip()
            return return_type_text if return_type_text else "void"

        return "void"

    def _extract_entities(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        current_namespace: str = None,
        current_class: str = None,
    ) -> None:
        """Extract entities from AST node recursively."""

        # Module entity (only at root)
        if node.type == 'translation_unit':
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
            if child.type == 'preproc_include':
                self._extract_include(child, source, module_name, result)

            elif child.type == 'namespace_definition':
                self._extract_namespace(child, source, module_name, file_path, result, current_namespace)

            elif child.type == 'class_specifier':
                self._extract_class(child, source, module_name, file_path, result, current_namespace)

            elif child.type == 'struct_specifier':
                self._extract_struct(child, source, module_name, file_path, result, current_namespace)

            elif child.type == 'enum_specifier':
                self._extract_enum(child, source, module_name, file_path, result, current_namespace)

            elif child.type == 'function_definition':
                # Check if this is actually a class (tree-sitter misparses UE macros)
                class_spec = self._find_child(child, 'class_specifier')
                if class_spec:
                    # This is a UE-style class definition parsed incorrectly
                    self._extract_ue_class(child, source, module_name, file_path, result, current_namespace)
                else:
                    self._extract_function(child, source, module_name, file_path, result, current_namespace, current_class)

            elif child.type == 'declaration':
                # Could be a function declaration or variable declaration
                self._extract_declaration(child, source, module_name, file_path, result, current_namespace, current_class)

            elif child.type == 'template_declaration':
                self._extract_template(child, source, module_name, file_path, result, current_namespace, current_class)

            elif child.type == 'linkage_specification':
                # extern "C" { ... }
                self._extract_entities(child, source, module_name, file_path, result, current_namespace, current_class)

    def _extract_include(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        result: ParseResult,
    ) -> None:
        """Extract #include directives."""
        path_node = self._find_child(node, 'string_literal')
        if path_node is None:
            path_node = self._find_child(node, 'system_lib_string')

        if path_node:
            include_path = self._get_node_text(path_node, source)
            # Remove quotes/brackets
            include_path = include_path.strip('"<>')

            result.relationships.append((module_name, include_path, "imports", {
                'style': 'include'
            }))

    def _extract_namespace(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        parent_namespace: str = None,
    ) -> None:
        """Extract a namespace definition."""
        name_node = self._find_child(node, 'namespace_identifier') or self._find_child(node, 'identifier')

        if name_node:
            ns_name = self._get_node_text(name_node, source)
            if parent_namespace:
                qualified_name = f"{parent_namespace}::{ns_name}"
            else:
                qualified_name = ns_name
        else:
            # Anonymous namespace
            qualified_name = parent_namespace or "<anonymous>"

        # Process contents with namespace context
        body = self._find_child(node, 'declaration_list')
        if body:
            for child in body.children:
                self._extract_entities_single(child, source, module_name, file_path, result, qualified_name, None)

    def _extract_entities_single(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        current_namespace: str = None,
        current_class: str = None,
    ) -> None:
        """Extract a single entity from a node."""
        if node.type == 'class_specifier':
            self._extract_class(node, source, module_name, file_path, result, current_namespace)
        elif node.type == 'struct_specifier':
            self._extract_struct(node, source, module_name, file_path, result, current_namespace)
        elif node.type == 'enum_specifier':
            self._extract_enum(node, source, module_name, file_path, result, current_namespace)
        elif node.type == 'function_definition':
            self._extract_function(node, source, module_name, file_path, result, current_namespace, current_class)
        elif node.type == 'declaration':
            self._extract_declaration(node, source, module_name, file_path, result, current_namespace, current_class)
        elif node.type == 'template_declaration':
            self._extract_template(node, source, module_name, file_path, result, current_namespace, current_class)
        elif node.type == 'namespace_definition':
            self._extract_namespace(node, source, module_name, file_path, result, current_namespace)

    def _extract_class(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        namespace: str = None,
    ) -> None:
        """Extract a class definition and its methods."""
        name_node = self._find_child(node, 'type_identifier') or self._find_child(node, 'name')
        if name_node is None:
            return

        class_name = self._get_node_text(name_node, source)
        if namespace:
            qualified_name = f"{module_name}.{namespace}::{class_name}"
        else:
            qualified_name = f"{module_name}.{class_name}"

        docstring = self._extract_comment(node, source)
        code = self._get_node_text(node, source)

        # Extract UE specifiers
        ue_specs = self._extract_ue_specifiers(node, source)

        # Extract base classes
        bases = []
        base_clause = self._find_child(node, 'base_class_clause')
        if base_clause:
            for child in base_clause.children:
                if child.type == 'base_class_specifier':
                    type_node = self._find_child(child, 'type_identifier')
                    if type_node:
                        bases.append(self._get_node_text(type_node, source))

        # Extract methods from class body
        body = self._find_child(node, 'field_declaration_list')
        method_names = []
        if body:
            for child in body.children:
                if child.type == 'function_definition':
                    func_decl = self._find_child(child, 'function_declarator')
                    if func_decl:
                        func_name_node = self._find_child(func_decl, 'identifier') or \
                                         self._find_child(func_decl, 'field_identifier') or \
                                         self._find_child(func_decl, 'destructor_name')
                        if func_name_node:
                            method_names.append(self._get_node_text(func_name_node, source))
                elif child.type == 'declaration':
                    # Could be a constructor/destructor declaration
                    declarator = self._find_child_recursive(child, 'function_declarator')
                    if declarator:
                        func_name_node = self._find_child(declarator, 'identifier') or \
                                         self._find_child(declarator, 'field_identifier') or \
                                         self._find_child(declarator, 'destructor_name')
                        if func_name_node:
                            method_names.append(self._get_node_text(func_name_node, source))
                elif child.type == 'field_declaration':
                    # Method declarations in class body are field_declarations
                    declarator = self._find_child_recursive(child, 'function_declarator')
                    if declarator:
                        func_name_node = self._find_child(declarator, 'identifier') or \
                                         self._find_child(declarator, 'field_identifier')
                        if func_name_node:
                            method_names.append(self._get_node_text(func_name_node, source))

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
                "namespace": namespace,
                "is_uclass": ue_specs['is_uclass'],
                "ue_specifiers": ue_specs['ue_specifiers'],
                "language": self.language,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        # Extract methods and members
        if body:
            self._extract_class_members(body, source, qualified_name, file_path, result)

    def _extract_ue_class(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        namespace: str = None,
    ) -> None:
        """Extract a UE-style class that was misparsed as a function_definition.

        Tree-sitter parses 'UCLASS(...) class AName : public ABase { ... };'
        as a function_definition with class_specifier as return type.
        """
        # Get the class name from the identifier child (what tree-sitter thinks is the function name)
        name_node = self._find_child(node, 'identifier')
        if name_node is None:
            return

        class_name = self._get_node_text(name_node, source)
        if namespace:
            qualified_name = f"{module_name}.{namespace}::{class_name}"
        else:
            qualified_name = f"{module_name}.{class_name}"

        docstring = self._extract_comment(node, source)
        code = self._get_node_text(node, source)

        # Extract UE specifiers from the source
        ue_specs = self._extract_ue_specifiers(node, source)

        # Try to extract base classes from ERROR node (contains ": public BaseClass")
        bases = []
        error_node = self._find_child(node, 'ERROR')
        if error_node:
            error_text = self._get_node_text(error_node, source)
            # Parse "public BaseClass" or "public BaseClass, public OtherBase"
            import re
            base_matches = re.findall(r'(?:public|private|protected)\s+(\w+)', error_text)
            bases = base_matches

        # Get method names from compound_statement (which is the class body)
        body = self._find_child(node, 'compound_statement')
        method_names = []
        if body:
            for child in body.children:
                if child.type == 'function_definition':
                    func_decl = self._find_child(child, 'function_declarator')
                    if func_decl:
                        func_name_node = self._find_child(func_decl, 'identifier') or \
                                         self._find_child(func_decl, 'field_identifier')
                        if func_name_node:
                            method_names.append(self._get_node_text(func_name_node, source))
                elif child.type == 'declaration':
                    declarator = self._find_child_recursive(child, 'function_declarator')
                    if declarator:
                        func_name_node = self._find_child(declarator, 'identifier') or \
                                         self._find_child(declarator, 'field_identifier')
                        if func_name_node:
                            method_names.append(self._get_node_text(func_name_node, source))
                elif child.type == 'field_declaration':
                    declarator = self._find_child_recursive(child, 'function_declarator')
                    if declarator:
                        func_name_node = self._find_child(declarator, 'identifier') or \
                                         self._find_child(declarator, 'field_identifier')
                        if func_name_node:
                            method_names.append(self._get_node_text(func_name_node, source))

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
                "namespace": namespace,
                "is_uclass": True,
                "ue_specifiers": ue_specs['ue_specifiers'],
                "language": self.language,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        # Extract methods from class body (compound_statement)
        if body:
            self._extract_class_members(body, source, qualified_name, file_path, result)

    def _extract_struct(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        namespace: str = None,
    ) -> None:
        """Extract a struct definition (similar to class but different default access)."""
        name_node = self._find_child(node, 'type_identifier') or self._find_child(node, 'name')
        if name_node is None:
            # Anonymous struct
            return

        struct_name = self._get_node_text(name_node, source)
        if namespace:
            qualified_name = f"{module_name}.{namespace}::{struct_name}"
        else:
            qualified_name = f"{module_name}.{struct_name}"

        docstring = self._extract_comment(node, source)
        code = self._get_node_text(node, source)

        # Extract UE specifiers
        ue_specs = self._extract_ue_specifiers(node, source)

        # Extract base structs
        bases = []
        base_clause = self._find_child(node, 'base_class_clause')
        if base_clause:
            for child in base_clause.children:
                if child.type == 'base_class_specifier':
                    type_node = self._find_child(child, 'type_identifier')
                    if type_node:
                        bases.append(self._get_node_text(type_node, source))

        # Extract fields
        body = self._find_child(node, 'field_declaration_list')
        field_names = []
        if body:
            for child in body.children:
                if child.type == 'field_declaration':
                    declarator = self._find_child(child, 'field_identifier')
                    if declarator:
                        field_names.append(self._get_node_text(declarator, source))

        result.entities.append({
            "name": qualified_name,
            "kind": "class",  # Treat struct as class for consistency
            "file": file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "intent": docstring,
            "code": code,
            "metadata": {
                "lineno": node.start_point[0] + 1,
                "end_lineno": node.end_point[0] + 1,
                "bases": bases,
                "fields": field_names,
                "is_struct": True,
                "namespace": namespace,
                "is_ustruct": ue_specs['is_ustruct'],
                "ue_specifiers": ue_specs['ue_specifiers'],
                "language": self.language,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        # Extract methods from struct body
        if body:
            self._extract_class_members(body, source, qualified_name, file_path, result)

    def _extract_enum(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        namespace: str = None,
    ) -> None:
        """Extract an enum definition."""
        name_node = self._find_child(node, 'type_identifier')
        if name_node is None:
            return

        enum_name = self._get_node_text(name_node, source)
        if namespace:
            qualified_name = f"{module_name}.{namespace}::{enum_name}"
        else:
            qualified_name = f"{module_name}.{enum_name}"

        docstring = self._extract_comment(node, source)
        code = self._get_node_text(node, source)

        # Extract UE specifiers
        ue_specs = self._extract_ue_specifiers(node, source)

        # Extract enum values
        body = self._find_child(node, 'enumerator_list')
        members = []
        if body:
            for child in body.children:
                if child.type == 'enumerator':
                    name = self._find_child(child, 'identifier')
                    if name:
                        members.append(self._get_node_text(name, source))

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
                "namespace": namespace,
                "ue_specifiers": ue_specs['ue_specifiers'],
                "language": self.language,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

    def _extract_class_members(
        self,
        body_node: 'Node',
        source: str,
        class_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract methods and other members from a class body."""
        for child in body_node.children:
            if child.type == 'function_definition':
                self._extract_method(child, source, class_name, file_path, result)
            elif child.type == 'declaration':
                # Could be a constructor/destructor declaration
                declarator = self._find_child_recursive(child, 'function_declarator')
                if declarator:
                    self._extract_method_declaration(child, source, class_name, file_path, result)
            elif child.type == 'field_declaration':
                # Method declarations in class body are field_declarations
                declarator = self._find_child_recursive(child, 'function_declarator')
                if declarator:
                    self._extract_field_method_declaration(child, source, class_name, file_path, result)
            elif child.type == 'template_declaration':
                # Template method
                inner = self._find_child(child, 'function_definition')
                if inner:
                    self._extract_method(inner, source, class_name, file_path, result, is_template=True)

    def _extract_method(
        self,
        node: 'Node',
        source: str,
        class_name: str,
        file_path: str,
        result: ParseResult,
        is_template: bool = False,
    ) -> None:
        """Extract a method definition."""
        declarator = self._find_child(node, 'function_declarator')
        if declarator is None:
            return

        # Get method name (handle constructors, destructors, operators)
        name_node = self._find_child(declarator, 'identifier') or \
                    self._find_child(declarator, 'field_identifier') or \
                    self._find_child(declarator, 'destructor_name') or \
                    self._find_child(declarator, 'operator_name')

        if name_node is None:
            # Try qualified identifier for out-of-class definitions
            qualified = self._find_child(declarator, 'qualified_identifier')
            if qualified:
                name_node = self._find_child(qualified, 'identifier')

        if name_node is None:
            return

        method_name = self._get_node_text(name_node, source)
        # Handle destructor names
        if method_name.startswith('~'):
            pass  # Keep as is
        elif node.type == 'destructor_name':
            method_name = '~' + method_name

        qualified_name = f"{class_name}.{method_name}"
        docstring = self._extract_comment(node, source)
        signature = self._build_signature(declarator, source)
        return_type = self._extract_return_type(node, source)
        code = self._get_node_text(node, source)

        # Extract UE specifiers
        ue_specs = self._extract_ue_specifiers(node, source)

        # Check for virtual, static, const qualifiers
        is_virtual = 'virtual' in source[node.start_byte:declarator.start_byte]
        is_static = 'static' in source[node.start_byte:declarator.start_byte]
        is_const = False
        # Check for const after parameter list
        for child in declarator.children:
            if child.type == 'type_qualifier' and self._get_node_text(child, source) == 'const':
                is_const = True

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
                "is_virtual": is_virtual,
                "is_static": is_static,
                "is_const": is_const,
                "is_template": is_template,
                "is_ufunction": ue_specs['is_ufunction'],
                "ue_specifiers": ue_specs['ue_specifiers'],
                "language": self.language,
            },
        })

        result.relationships.append((qualified_name, class_name, "member_of"))

        # Extract calls from method body
        body = self._find_child(node, 'compound_statement')
        if body:
            self._extract_calls(body, source, qualified_name, result)

    def _extract_method_declaration(
        self,
        node: 'Node',
        source: str,
        class_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract a method declaration (without body)."""
        declarator = self._find_child_recursive(node, 'function_declarator')
        if declarator is None:
            return

        name_node = self._find_child(declarator, 'identifier') or \
                    self._find_child(declarator, 'field_identifier')
        if name_node is None:
            return

        method_name = self._get_node_text(name_node, source)
        qualified_name = f"{class_name}.{method_name}"
        docstring = self._extract_comment(node, source)
        signature = self._build_signature(declarator, source)
        code = self._get_node_text(node, source)

        # Extract UE specifiers
        ue_specs = self._extract_ue_specifiers(node, source)

        # Check for virtual, static qualifiers
        node_text = self._get_node_text(node, source)
        is_virtual = 'virtual' in node_text
        is_static = 'static' in node_text
        is_pure_virtual = '= 0' in node_text

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
                "is_virtual": is_virtual,
                "is_static": is_static,
                "is_pure_virtual": is_pure_virtual,
                "is_declaration": True,
                "is_ufunction": ue_specs['is_ufunction'],
                "ue_specifiers": ue_specs['ue_specifiers'],
                "language": self.language,
            },
        })

        result.relationships.append((qualified_name, class_name, "member_of"))

    def _extract_field_method_declaration(
        self,
        node: 'Node',
        source: str,
        class_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract a method declaration from a field_declaration node."""
        declarator = self._find_child_recursive(node, 'function_declarator')
        if declarator is None:
            return

        name_node = self._find_child(declarator, 'identifier') or \
                    self._find_child(declarator, 'field_identifier')
        if name_node is None:
            return

        method_name = self._get_node_text(name_node, source)
        qualified_name = f"{class_name}.{method_name}"
        docstring = self._extract_comment(node, source)
        signature = self._build_signature(declarator, source)
        code = self._get_node_text(node, source)

        # Extract UE specifiers
        ue_specs = self._extract_ue_specifiers(node, source)

        # Check for virtual, static, const qualifiers
        node_text = self._get_node_text(node, source)
        is_virtual = 'virtual' in node_text.split('(')[0]  # Only check before params
        is_static = 'static' in node_text.split('(')[0]
        is_const = False
        # Check for const qualifier after parameters
        for child in declarator.children:
            if child.type == 'type_qualifier' and self._get_node_text(child, source) == 'const':
                is_const = True

        # Try to extract return type
        return_type = "void"
        for child in node.children:
            if child.type in ('primitive_type', 'type_identifier', 'sized_type_specifier', 'qualified_identifier'):
                return_type = self._get_node_text(child, source)
                break

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
                "is_virtual": is_virtual,
                "is_static": is_static,
                "is_const": is_const,
                "is_declaration": True,
                "is_ufunction": ue_specs['is_ufunction'],
                "ue_specifiers": ue_specs['ue_specifiers'],
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
        namespace: str = None,
        current_class: str = None,
    ) -> None:
        """Extract a free function definition."""
        declarator = self._find_child(node, 'function_declarator')
        if declarator is None:
            return

        # Get function name
        name_node = self._find_child(declarator, 'identifier')
        if name_node is None:
            # Check for qualified identifier (out-of-class method definition)
            qualified = self._find_child(declarator, 'qualified_identifier')
            if qualified:
                # This is an out-of-class method definition like ClassName::MethodName
                # The :: is a direct child with type '::'
                has_scope = any(c.type == '::' for c in qualified.children)
                if has_scope:
                    self._extract_out_of_class_method(node, source, module_name, file_path, result, namespace)
                    return
            return

        func_name = self._get_node_text(name_node, source)

        if namespace:
            qualified_name = f"{module_name}.{namespace}::{func_name}"
        else:
            qualified_name = f"{module_name}.{func_name}"

        docstring = self._extract_comment(node, source)
        signature = self._build_signature(declarator, source)
        return_type = self._extract_return_type(node, source)
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
                "namespace": namespace,
                "language": self.language,
            },
        })

        result.relationships.append((module_name, qualified_name, "contains"))

        # Extract calls from function body
        body = self._find_child(node, 'compound_statement')
        if body:
            self._extract_calls(body, source, qualified_name, result)

    def _extract_out_of_class_method(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        namespace: str = None,
    ) -> None:
        """Extract an out-of-class method definition like ClassName::MethodName."""
        declarator = self._find_child(node, 'function_declarator')
        if declarator is None:
            return

        qualified_id = self._find_child(declarator, 'qualified_identifier')
        if qualified_id is None:
            return

        # Get the full qualified name
        full_name = self._get_node_text(qualified_id, source)
        # Convert :: to .
        parts = full_name.split('::')
        if len(parts) >= 2:
            class_name = parts[-2]
            method_name = parts[-1]

            if namespace:
                qualified_class = f"{module_name}.{namespace}::{class_name}"
            else:
                qualified_class = f"{module_name}.{class_name}"

            qualified_name = f"{qualified_class}.{method_name}"

            docstring = self._extract_comment(node, source)
            signature = self._build_signature(declarator, source)
            return_type = self._extract_return_type(node, source)
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
                    "is_out_of_class_definition": True,
                    "language": self.language,
                },
            })

            result.relationships.append((qualified_name, qualified_class, "member_of"))

            # Extract calls
            body = self._find_child(node, 'compound_statement')
            if body:
                self._extract_calls(body, source, qualified_name, result)

    def _extract_declaration(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        namespace: str = None,
        current_class: str = None,
    ) -> None:
        """Extract a declaration (could be function or variable)."""
        # Check if this is a function declaration
        declarator = self._find_child_recursive(node, 'function_declarator')
        if declarator:
            # It's a function declaration
            name_node = self._find_child(declarator, 'identifier')
            if name_node:
                func_name = self._get_node_text(name_node, source)
                if namespace:
                    qualified_name = f"{module_name}.{namespace}::{func_name}"
                else:
                    qualified_name = f"{module_name}.{func_name}"

                docstring = self._extract_comment(node, source)
                signature = self._build_signature(declarator, source)
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
                        "is_declaration": True,
                        "namespace": namespace,
                        "language": self.language,
                    },
                })

                result.relationships.append((module_name, qualified_name, "contains"))

    def _extract_template(
        self,
        node: 'Node',
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
        namespace: str = None,
        current_class: str = None,
    ) -> None:
        """Extract a template declaration."""
        # Find the actual declaration inside the template
        for child in node.children:
            if child.type == 'class_specifier':
                self._extract_class(child, source, module_name, file_path, result, namespace)
            elif child.type == 'struct_specifier':
                self._extract_struct(child, source, module_name, file_path, result, namespace)
            elif child.type == 'function_definition':
                self._extract_function(child, source, module_name, file_path, result, namespace, current_class)
            elif child.type == 'declaration':
                self._extract_declaration(child, source, module_name, file_path, result, namespace, current_class)

    def _extract_calls(
        self,
        node: 'Node',
        source: str,
        caller_name: str,
        result: ParseResult,
    ) -> None:
        """Extract function calls from a node recursively."""
        if node.type == 'call_expression':
            func_node = self._find_child(node, 'identifier')
            if func_node:
                callee = self._get_node_text(func_node, source)
                result.relationships.append((caller_name, callee, "calls"))
            else:
                # Member function call or qualified call
                field_expr = self._find_child(node, 'field_expression')
                if field_expr:
                    field = self._find_child(field_expr, 'field_identifier')
                    if field:
                        callee = self._get_node_text(field, source)
                        result.relationships.append((caller_name, callee, "calls"))
                else:
                    # Qualified call like ClassName::StaticMethod()
                    qualified = self._find_child(node, 'qualified_identifier')
                    if qualified:
                        callee = self._get_node_text(qualified, source).replace('::', '.')
                        result.relationships.append((caller_name, callee, "calls"))

        for child in node.children:
            self._extract_calls(child, source, caller_name, result)
