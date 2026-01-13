"""Python-specific parser using the ast module."""

import ast
import logging
from pathlib import Path
from typing import List, Optional, Union

from parsers.base import BaseParser, ParseResult


class PythonParser(BaseParser):
    """Parser for Python source files using the ast module."""

    @property
    def language(self) -> str:
        return "python"

    @property
    def file_extensions(self) -> List[str]:
        return [".py", ".pyw"]

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.file_extensions

    def parse_file(self, file_path: Path, source: str = None) -> ParseResult:
        """Parse a Python file and extract entities and relationships.

        Args:
            file_path: Path to the Python file
            source: Optional source code (if already read)

        Returns:
            ParseResult with entities, relationships, and any errors
        """
        result = ParseResult()

        # Read source if not provided
        if source is None:
            try:
                source = self._read_file(file_path)
            except Exception as e:
                result.errors.append(f"Failed to read {file_path}: {e}")
                return result

        # Parse the AST
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as e:
            result.errors.append(f"Syntax error in {file_path}: {e}")
            return result

        # Compute module name from file path
        module_name = self._compute_module_name(file_path)

        # Extract module entity
        module_docstring = ast.get_docstring(tree)
        result.entities.append({
            "name": module_name,
            "kind": "module",
            "file": str(file_path),
            "start_line": 1,
            "end_line": self._count_lines(source),
            "intent": module_docstring,
            "code": None,  # Don't store full module code
            "metadata": {"file_path": str(file_path), "language": self.language},
        })

        # Extract top-level entities
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._extract_function(node, source, module_name, result)
                # Add contains relationship
                func_name = f"{module_name}.{node.name}"
                result.relationships.append((module_name, func_name, "contains"))

            elif isinstance(node, ast.ClassDef):
                self._extract_class(node, source, module_name, str(file_path), result)
                # Add contains relationship
                class_name = f"{module_name}.{node.name}"
                result.relationships.append((module_name, class_name, "contains"))

        # Extract imports
        self._extract_imports(tree, module_name, result)

        # Extract calls from functions and methods
        self._extract_all_calls(tree, source, module_name, result)

        return result

    def _read_file(self, file_path: Path) -> str:
        """Read file with encoding handling."""
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]

        for encoding in encodings:
            try:
                return file_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue

        # Last resort: read with errors ignored
        return file_path.read_text(encoding="utf-8", errors="ignore")

    def _compute_module_name(self, file_path: Path) -> str:
        """Compute module name from file path."""
        if file_path.name == "__init__.py":
            # Package init - module name is the parent directory
            return file_path.parent.name
        else:
            return file_path.stem

    def _count_lines(self, source: str) -> int:
        """Count lines in source."""
        return len(source.splitlines())

    def _extract_function(
        self,
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        source: str,
        module_name: str,
        result: ParseResult,
    ) -> None:
        """Extract a function definition and add to result."""
        func_name = f"{module_name}.{node.name}"
        docstring = ast.get_docstring(node)
        code = self._get_node_source(node, source)
        signature = self._build_signature(node)

        result.entities.append({
            "name": func_name,
            "kind": "function",
            "file": None,  # Will be set by caller if needed
            "start_line": node.lineno,
            "end_line": getattr(node, "end_lineno", None),
            "intent": docstring,
            "code": code,
            "metadata": {
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "args": [arg.arg for arg in node.args.args],
                "signature": signature,
                "language": self.language,
            },
        })

    def _extract_class(
        self,
        node: ast.ClassDef,
        source: str,
        module_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract a class definition and its methods, add to result."""
        class_name = f"{module_name}.{node.name}"
        docstring = ast.get_docstring(node)
        code = self._get_node_source(node, source)

        # Extract base class names
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(ast.unparse(base))

        # Get method names for class metadata
        method_names = [
            n.name for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        result.entities.append({
            "name": class_name,
            "kind": "class",
            "file": file_path,
            "start_line": node.lineno,
            "end_line": getattr(node, "end_lineno", None),
            "intent": docstring,
            "code": code,
            "metadata": {
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
                "bases": bases,
                "methods": method_names,
                "language": self.language,
            },
        })

        # Extract methods
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._extract_method(child, source, class_name, file_path, result)
                # Add member_of relationship
                method_name = f"{class_name}.{child.name}"
                result.relationships.append((method_name, class_name, "member_of"))

    def _extract_method(
        self,
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        source: str,
        class_name: str,
        file_path: str,
        result: ParseResult,
    ) -> None:
        """Extract a method definition and add to result."""
        qualified_name = f"{class_name}.{node.name}"
        docstring = ast.get_docstring(node)
        code = self._get_node_source(node, source)
        signature = self._build_signature(node)

        result.entities.append({
            "name": qualified_name,
            "kind": "method",
            "file": file_path,
            "start_line": node.lineno,
            "end_line": getattr(node, "end_lineno", None),
            "intent": docstring,
            "code": code,
            "metadata": {
                "file": file_path,
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", None),
                "signature": signature,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "language": self.language,
            },
        })

    def _build_signature(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> str:
        """Build a function/method signature string from AST node."""
        args = node.args
        parts = []

        # Positional-only args (before /)
        for arg in args.posonlyargs:
            parts.append(arg.arg)

        # Regular args
        num_defaults = len(args.defaults)
        num_args = len(args.args)
        for i, arg in enumerate(args.args):
            default_idx = i - (num_args - num_defaults)
            if default_idx >= 0:
                parts.append(f"{arg.arg}=...")
            else:
                parts.append(arg.arg)

        # *args
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        elif args.kwonlyargs:
            parts.append("*")

        # Keyword-only args
        for i, arg in enumerate(args.kwonlyargs):
            if args.kw_defaults[i] is not None:
                parts.append(f"{arg.arg}=...")
            else:
                parts.append(arg.arg)

        # **kwargs
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")

        return f"({', '.join(parts)})"

    def _get_node_source(self, node: ast.AST, source: str) -> str:
        """Extract source code for an AST node."""
        # Use ast.get_source_segment if available (Python 3.8+)
        if hasattr(ast, "get_source_segment"):
            segment = ast.get_source_segment(source, node)
            if segment:
                return segment

        # Fallback: extract by line numbers
        lines = source.splitlines()
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        return "\n".join(lines[start:end])

    def _extract_imports(
        self,
        tree: ast.AST,
        module_name: str,
        result: ParseResult,
    ) -> None:
        """Extract import statements and add 'imports' relationships."""
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # Add imports relationship from this module to imported module
                    result.relationships.append((module_name, alias.name, "imports"))

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # Resolve relative imports
                    if node.level > 0:
                        # Relative import - we'd need the package context to resolve
                        # For now, just use the module name as-is with dots prefix
                        imported_module = "." * node.level + (node.module or "")
                    else:
                        imported_module = node.module
                    result.relationships.append((module_name, imported_module, "imports"))

    def _extract_all_calls(
        self,
        tree: ast.AST,
        source: str,
        module_name: str,
        result: ParseResult,
    ) -> None:
        """Extract function calls from all functions and methods in the tree."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Determine the caller's qualified name
                caller_name = self._get_qualified_name(node, tree, module_name)

                # Extract calls from this function/method
                calls = self._extract_calls_from_node(node)

                for call_name, call_type in calls:
                    # Add calls relationship
                    result.relationships.append((caller_name, call_name, "calls"))

    def _get_qualified_name(
        self,
        func_node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        tree: ast.AST,
        module_name: str,
    ) -> str:
        """Get the fully qualified name of a function or method."""
        # Check if this function is inside a class
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if child is func_node:
                        return f"{module_name}.{node.name}.{func_node.name}"

        # Top-level function
        return f"{module_name}.{func_node.name}"

    def _extract_calls_from_node(
        self,
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    ) -> List[tuple]:
        """Extract function calls from a function/method body.

        Returns list of (name, type) tuples where type is one of:
        - 'simple': direct function call like foo()
        - 'method': method call like self.foo() or obj.method()
        - 'chained': chained attribute call like a.b.c()
        """
        calls = []

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func

                if isinstance(func, ast.Name):
                    # Simple call: foo()
                    calls.append((func.id, "simple"))

                elif isinstance(func, ast.Attribute):
                    attr_name = func.attr

                    if isinstance(func.value, ast.Name):
                        if func.value.id == "self":
                            # self.method() - track just the method name
                            calls.append((attr_name, "method"))
                        else:
                            # module.function() or obj.method()
                            calls.append((f"{func.value.id}.{attr_name}", "chained"))
                    else:
                        # Chained call like a.b.c() - track the final attribute
                        calls.append((attr_name, "chained"))

        return calls
