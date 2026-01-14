"""
ingestion - Mixin class for code ingestion and parsing operations.

This module is extracted from codestore.py to reduce file size.
It provides file ingestion, AST parsing, import analysis, and call analysis.
"""

import ast
import logging
import os
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class IngestionMixin:
    """
    Mixin class providing code ingestion operations.

    This mixin expects the following attributes on the class:
    - self.conn: sqlite3 connection with Row factory
    - self.parser_registry: ParserRegistry instance for multi-language support
    - self.add_entity: method to add entities
    - self.add_relationship: method to add relationships
    - self.find_entities: method to find entities
    - self.track_file: method to track file mtimes
    - self.track_entity_file: method to track entity-file mappings
    - self.start_ingest_run: method to start ingest tracking
    - self.end_ingest_run: method to end ingest tracking

    Usage:
        class CodeStore(IngestionMixin, ...):
            ...
    """

    # Default patterns to exclude during ingestion
    DEFAULT_EXCLUDE_PATTERNS = ['.git', '__pycache__', '.claude/skills', 'node_modules', '.venv', 'venv']

    # Python builtins that should not be tracked as calls
    BUILTINS = frozenset({
        'abs', 'aiter', 'all', 'any', 'anext', 'ascii', 'bin', 'bool',
        'breakpoint', 'bytearray', 'bytes', 'callable', 'chr', 'classmethod',
        'compile', 'complex', 'delattr', 'dict', 'dir', 'divmod', 'enumerate',
        'eval', 'exec', 'filter', 'float', 'format', 'frozenset', 'getattr',
        'globals', 'hasattr', 'hash', 'help', 'hex', 'id', 'input', 'int',
        'isinstance', 'issubclass', 'iter', 'len', 'list', 'locals', 'map',
        'max', 'memoryview', 'min', 'next', 'object', 'oct', 'open', 'ord',
        'pow', 'print', 'property', 'range', 'repr', 'reversed', 'round',
        'set', 'setattr', 'slice', 'sorted', 'staticmethod', 'str', 'sum',
        'super', 'tuple', 'type', 'vars', 'zip', '__import__',
    })

    def ingest_files(self, paths: Union[str, List[str]], exclude_patterns: List[str] = None) -> Dict[str, Any]:
        """
        Recursively ingest source files from the given path(s).

        Uses the parser registry to find appropriate parsers for each file.
        Parses each supported file, extracts entities (modules, classes, functions, methods),
        and establishes relationships between them.

        Args:
            paths: Directory path or list of paths to recursively search
            exclude_patterns: Optional list of glob patterns to exclude.
                            If None, uses DEFAULT_EXCLUDE_PATTERNS.
                            Pass empty list [] to disable exclusions.

        Returns:
            Dict with 'modules', 'functions', 'classes', 'methods', 'errors' counts
        """
        from fnmatch import fnmatch

        # Normalize paths to a list
        if isinstance(paths, str):
            path_list = [paths]
        else:
            path_list = list(paths)

        # Use default patterns if not specified
        if exclude_patterns is None:
            exclude_patterns = self.DEFAULT_EXCLUDE_PATTERNS

        stats = {"modules": 0, "functions": 0, "classes": 0, "methods": 0, "errors": 0}

        # Start tracking this ingest operation
        ingest_run_id = self.start_ingest_run(path_list)

        # Get supported extensions from the registry
        supported_extensions = self.parser_registry.supported_extensions()

        try:
            for path in path_list:
                base_path = Path(path)
                if not base_path.exists():
                    raise ValueError(f"Path does not exist: {path}")

                # Find all files with supported extensions
                all_files = []
                for ext in supported_extensions:
                    all_files.extend(base_path.rglob(f"*{ext}"))

                for source_file in all_files:
                    # Check if any path component matches an exclude pattern
                    rel_path = source_file.relative_to(base_path)
                    skip = False
                    for part in rel_path.parts:
                        for pattern in exclude_patterns:
                            if fnmatch(part, pattern):
                                skip = True
                                break
                        if skip:
                            break
                    # Also check the full relative path for patterns like '.claude/skills'
                    if not skip:
                        rel_path_str = str(rel_path)
                        for pattern in exclude_patterns:
                            if fnmatch(rel_path_str, pattern) or fnmatch(rel_path_str, f'*{pattern}*'):
                                skip = True
                                break
                    if skip:
                        continue

                    # Get the appropriate parser for this file
                    parser = self.parser_registry.get_parser(source_file)
                    if parser is None:
                        continue

                    # Parse the file
                    parse_result = parser.parse_file(source_file)

                    # Handle parse errors
                    for error in parse_result.errors:
                        logging.warning(error)
                        stats["errors"] += 1

                    if parse_result.errors:
                        continue

                    # Track file mtime for change detection
                    self.track_file(str(source_file), ingest_run_id)

                    # Store entities and build name-to-id mapping for relationships
                    name_to_id: Dict[str, int] = {}

                    for entity in parse_result.entities:
                        entity_id = self.add_entity(
                            name=entity["name"],
                            kind=entity["kind"],
                            code=entity.get("code"),
                            intent=entity.get("intent"),
                            metadata=entity.get("metadata"),
                        )
                        name_to_id[entity["name"]] = entity_id

                        # Track entity-file mapping for change detection
                        self.track_entity_file(entity_id, str(source_file))

                        # Update stats
                        kind = entity["kind"]
                        if kind == "module":
                            stats["modules"] += 1
                        elif kind == "function":
                            stats["functions"] += 1
                        elif kind == "class":
                            stats["classes"] += 1
                        elif kind == "method":
                            stats["methods"] += 1

                    # Store relationships (handle both 3-tuple and 4-tuple formats)
                    for rel in parse_result.relationships:
                        if len(rel) == 4:
                            from_name, to_name, relation, rel_metadata = rel
                        else:
                            from_name, to_name, relation = rel
                            rel_metadata = None
                        from_id = name_to_id.get(from_name)
                        to_id = name_to_id.get(to_name)

                        if from_id and to_id:
                            self.add_relationship(from_id, to_id, relation, rel_metadata)
                        elif from_id and relation == 'dom_reference':
                            # DOM references may point to elements in other files
                            # Store as a special relationship with target as name
                            self._store_cross_file_reference(
                                from_id, to_name, relation, rel_metadata, str(source_file)
                            )

            # Mark ingest run as completed
            self.end_ingest_run(ingest_run_id, stats, "completed")
        except Exception as e:
            # Mark ingest run as failed
            self.end_ingest_run(ingest_run_id, stats, "failed")
            raise

        return stats

    def _store_cross_file_reference(
        self,
        source_entity_id: int,
        target_name: str,
        ref_type: str,
        metadata: dict,
        source_file: str
    ):
        """Store a cross-file reference (e.g., JS DOM reference to HTML element).

        These are references where the target may be in a different file
        and needs to be validated after all files are ingested.
        """
        import json

        line_number = metadata.get('line', 0) if metadata else 0
        verifiable = metadata.get('verifiable', True) if metadata else True
        reason = metadata.get('reason', None) if metadata else None

        self.conn.execute("""
            INSERT INTO cross_file_refs
            (source_entity_id, target_name, ref_type, source_file, line_number, verifiable, verification_reason, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            source_entity_id,
            target_name,
            ref_type,
            source_file,
            line_number,
            1 if verifiable else 0,
            reason,
            json.dumps(metadata) if metadata else None
        ))
        self.conn.commit()

    def _ingest_file(self, file_path: Path, base_path: Path, stats: Dict):
        """Ingest a single Python file.

        .. deprecated::
            Use the parser registry via ingest_files() instead.
            This method will be removed in a future version.
        """
        warnings.warn(
            "_ingest_file is deprecated; use parser registry via ingest_files()",
            DeprecationWarning,
            stacklevel=2,
        )
        source = file_path.read_text(encoding="utf-8")

        # Parse the file
        tree = ast.parse(source, filename=str(file_path))

        # Compute module name from path
        rel_path = file_path.relative_to(base_path)
        if file_path.name == "__init__.py":
            # Package init - module name is the parent directory
            module_name = str(rel_path.parent).replace(os.sep, ".")
            if module_name == ".":
                module_name = base_path.name
        else:
            module_name = str(rel_path.with_suffix("")).replace(os.sep, ".")

        # Get module docstring
        module_docstring = ast.get_docstring(tree)

        # Create module entity
        module_id = self.add_entity(
            name=module_name,
            kind="module",
            code=None,  # Don't store full file code, just extracted entities
            intent=module_docstring,
            metadata={"file_path": str(file_path)}
        )
        stats["modules"] += 1

        # Extract top-level functions and classes
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                entity_id = self._extract_function(node, source, module_name)
                self.add_relationship(module_id, entity_id, "contains")
                stats["functions"] += 1

            elif isinstance(node, ast.ClassDef):
                entity_id, method_count = self._extract_class(node, source, module_name, str(file_path))
                self.add_relationship(module_id, entity_id, "contains")
                stats["classes"] += 1
                stats["methods"] += method_count

    def _extract_function(self, node: ast.FunctionDef, source: str, module_name: str) -> int:
        """Extract a function definition and create an entity.

        .. deprecated::
            Use PythonParser from parsers.python_parser instead.
            This method will be removed in a future version.
        """
        warnings.warn(
            "_extract_function is deprecated; use PythonParser instead",
            DeprecationWarning,
            stacklevel=2,
        )
        func_name = f"{module_name}.{node.name}"
        docstring = ast.get_docstring(node)
        code = self._get_node_source(node, source)

        return self.add_entity(
            name=func_name,
            kind="function",
            code=code,
            intent=docstring,
            metadata={
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "args": [arg.arg for arg in node.args.args],
            }
        )

    def _extract_class(self, node: ast.ClassDef, source: str, module_name: str,
                       file_path: str = None) -> Tuple[int, int]:
        """Extract a class definition and create an entity, plus method entities.

        .. deprecated::
            Use PythonParser from parsers.python_parser instead.
            This method will be removed in a future version.

        Returns:
            Tuple of (class_entity_id, method_count)
        """
        warnings.warn(
            "_extract_class is deprecated; use PythonParser instead",
            DeprecationWarning,
            stacklevel=2,
        )
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
        method_names = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

        class_id = self.add_entity(
            name=class_name,
            kind="class",
            code=code,
            intent=docstring,
            metadata={
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
                "bases": bases,
                "methods": method_names,
            }
        )

        # Create separate method entities
        method_count = 0
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_id = self._extract_method(child, source, class_name, file_path)
                self.add_relationship(method_id, class_id, "member_of")
                method_count += 1

        return class_id, method_count

    def _extract_method(self, node: ast.FunctionDef, source: str, class_name: str,
                        file_path: str = None) -> int:
        """Extract a method definition and create an entity.

        .. deprecated::
            Use PythonParser from parsers.python_parser instead.
            This method will be removed in a future version.
        """
        warnings.warn(
            "_extract_method is deprecated; use PythonParser instead",
            DeprecationWarning,
            stacklevel=2,
        )
        qualified_name = f"{class_name}.{node.name}"
        docstring = ast.get_docstring(node)
        code = self._get_node_source(node, source)

        # Build signature from args
        signature = self._build_signature(node)

        return self.add_entity(
            name=qualified_name,
            kind="method",
            code=code,
            intent=docstring,
            metadata={
                "file": file_path,
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", None),
                "signature": signature,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            }
        )

    def _build_signature(self, node: ast.FunctionDef) -> str:
        """Build a function/method signature string from AST node.

        .. deprecated::
            Use PythonParser from parsers.python_parser instead.
            This method will be removed in a future version.
        """
        warnings.warn(
            "_build_signature is deprecated; use PythonParser instead",
            DeprecationWarning,
            stacklevel=2,
        )
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
        num_kw_defaults = len(args.kw_defaults)
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
        """Extract source code for an AST node.

        .. deprecated::
            Use PythonParser from parsers.python_parser instead.
            This method will be removed in a future version.
        """
        warnings.warn(
            "_get_node_source is deprecated; use PythonParser instead",
            DeprecationWarning,
            stacklevel=2,
        )
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

    # --- Import Analysis ---

    def analyze_imports(self) -> Dict[str, Any]:
        """
        Analyze all module entities to find and create 'imports' relationships.

        Parses the code of each module's source file, finds Import and ImportFrom
        statements, and creates 'imports' relationships to matching module entities.

        Handles:
        - 'import foo' - absolute imports
        - 'from foo import bar' - from imports
        - 'from foo import *' - star imports
        - 'from . import bar' - relative imports
        - 'from ..foo import bar' - parent relative imports

        Returns:
            Dict with 'analyzed', 'imports_found', 'relationships_created' counts
        """
        stats = {"analyzed": 0, "imports_found": 0, "relationships_created": 0}

        # Get all module entities
        modules = self.find_entities(kind="module")

        # Build a lookup of module names to IDs
        module_lookup = {m["name"]: m["id"] for m in modules}

        for module in modules:
            metadata = module.get("metadata") or {}
            file_path = metadata.get("file_path")

            if not file_path:
                continue

            # Skip non-Python modules (they handle imports during parsing)
            language = metadata.get("language", "python")
            if language != "python":
                continue

            # Read and parse the source file
            try:
                source = Path(file_path).read_text(encoding="utf-8")
                tree = ast.parse(source, filename=file_path)
            except (OSError, SyntaxError) as e:
                logging.warning(f"Could not parse {file_path}: {e}")
                continue

            stats["analyzed"] += 1
            importer_id = module["id"]
            importer_name = module["name"]

            # Extract all imports from the module
            imports = self._extract_imports(tree, importer_name)
            stats["imports_found"] += len(imports)

            # Create relationships for matching modules
            for imported_module, import_info in imports:
                imported_id = module_lookup.get(imported_module)

                if imported_id and imported_id != importer_id:
                    # Check if relationship already exists
                    existing = self.conn.execute(
                        "SELECT id FROM relationships WHERE source_id = ? AND target_id = ? AND relation = ?",
                        (importer_id, imported_id, "imports")
                    ).fetchone()

                    if not existing:
                        self.add_relationship(
                            importer_id, imported_id, "imports",
                            metadata=import_info
                        )
                        stats["relationships_created"] += 1

        return stats

    def _extract_imports(self, tree: ast.AST, importer_name: str) -> List[tuple]:
        """
        Extract all import statements from an AST.

        Args:
            tree: The parsed AST
            importer_name: The fully qualified name of the importing module

        Returns:
            List of (module_name, import_info) tuples where import_info is a dict
            containing 'names', 'aliases', 'is_relative', 'level', 'import_type'
        """
        imports = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                # Handle: import foo, import foo.bar, import foo as f
                for alias in node.names:
                    import_info = {
                        "names": [alias.name],
                        "aliases": {alias.name: alias.asname} if alias.asname else {},
                        "is_relative": False,
                        "level": 0,
                        "import_type": "import",
                    }
                    imports.append((alias.name, import_info))

            elif isinstance(node, ast.ImportFrom):
                # Handle: from foo import bar, from . import bar, from ..foo import *
                level = node.level  # Number of dots for relative imports
                module_name = node.module  # Can be None for 'from . import bar'

                # Resolve the base module name for relative imports
                resolved_base = self._resolve_relative_import(
                    importer_name, module_name, level
                )

                # Extract imported names
                names = [alias.name for alias in node.names]
                aliases = {
                    alias.name: alias.asname
                    for alias in node.names
                    if alias.asname
                }

                is_star = len(node.names) == 1 and node.names[0].name == "*"

                import_info = {
                    "names": names,
                    "aliases": aliases,
                    "is_relative": level > 0,
                    "level": level,
                    "import_type": "from_star" if is_star else "from",
                }

                if resolved_base:
                    # Add the base module import
                    imports.append((resolved_base, import_info))

                    # For 'from . import submod' (no module_name), each imported
                    # name could be a submodule - try resolving them too
                    if module_name is None and not is_star:
                        for name in names:
                            submodule = f"{resolved_base}.{name}" if resolved_base else name
                            submodule_info = {
                                "names": [name],
                                "aliases": {name: aliases.get(name)} if name in aliases else {},
                                "is_relative": level > 0,
                                "level": level,
                                "import_type": "from_submodule",
                            }
                            imports.append((submodule, submodule_info))

        return imports

    def _resolve_relative_import(self, importer_name: str, module_name: Optional[str],
                                  level: int) -> Optional[str]:
        """
        Resolve a relative import to an absolute module name.

        Args:
            importer_name: The fully qualified name of the importing module
            module_name: The module being imported (may be None for 'from . import x')
            level: Number of dots (0 = absolute, 1 = current package, 2 = parent, etc.)

        Returns:
            The resolved absolute module name, or None if it cannot be resolved
        """
        if level == 0:
            # Absolute import
            return module_name

        # Split the importer name into parts
        parts = importer_name.split(".")

        # Go up 'level' packages
        # level=1 means current package (parent of current module)
        # level=2 means parent of current package, etc.
        if level > len(parts):
            # Can't go above the root
            logging.warning(
                f"Relative import level {level} exceeds package depth for {importer_name}"
            )
            return None

        # Get the base package by going up 'level' levels
        base_parts = parts[:-level] if level <= len(parts) else []

        if module_name:
            # from ..foo import bar -> combine base with module_name
            return ".".join(base_parts + [module_name]) if base_parts else module_name
        else:
            # from . import bar -> just the base package
            return ".".join(base_parts) if base_parts else None

    # --- Call Analysis ---

    def analyze_calls(self, skip_builtins: bool = True) -> Dict[str, Any]:
        """
        Analyze all function entities to find and create 'calls' relationships.

        Parses the code of each function entity, finds function calls, and
        creates 'calls' relationships to any matching entities in the store.

        Args:
            skip_builtins: If True, skip calls to Python builtin functions

        Returns:
            Dict with 'analyzed', 'calls_found', 'relationships_created' counts
        """
        stats = {"analyzed": 0, "calls_found": 0, "relationships_created": 0}

        # Get all function entities
        functions = self.find_entities(kind="function")

        # Build a lookup of entity names for quick matching
        all_entities = self.conn.execute("SELECT id, name, kind FROM entities").fetchall()
        entity_lookup = {}
        for row in all_entities:
            # Store by full name and by short name
            entity_lookup[row["name"]] = row["id"]
            # Also store by short name (last component)
            short_name = row["name"].split(".")[-1]
            if short_name not in entity_lookup:
                entity_lookup[short_name] = row["id"]

        for func in functions:
            if not func.get("code"):
                continue

            # Skip non-Python functions (they handle calls during parsing)
            metadata = func.get("metadata") or {}
            language = metadata.get("language", "python")
            if language != "python":
                continue

            stats["analyzed"] += 1
            caller_id = func["id"]
            caller_module = ".".join(func["name"].split(".")[:-1])

            # Parse the function code
            try:
                tree = ast.parse(func["code"])
            except SyntaxError:
                logging.warning(f"Could not parse code for {func['name']}")
                continue

            # Find all calls
            calls = self._extract_calls(tree)
            stats["calls_found"] += len(calls)

            # Create relationships for matching entities
            for call_name, call_type in calls:
                if skip_builtins and call_name in self.BUILTINS:
                    continue

                callee_id = self._resolve_call_target(
                    call_name, call_type, caller_module, entity_lookup
                )
                if callee_id and callee_id != caller_id:
                    # Check if relationship already exists
                    existing = self.conn.execute(
                        "SELECT id FROM relationships WHERE source_id = ? AND target_id = ? AND relation = ?",
                        (caller_id, callee_id, "calls")
                    ).fetchone()
                    if not existing:
                        self.add_relationship(caller_id, callee_id, "calls")
                        stats["relationships_created"] += 1

        return stats

    def _extract_calls(self, tree: ast.AST) -> List[tuple]:
        """
        Extract all function calls from an AST.

        Returns list of (name, type) tuples where type is one of:
        - 'simple': direct function call like foo()
        - 'method': method call like self.foo() or obj.method()
        - 'chained': chained attribute call like a.b.c()
        """
        calls = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func

                if isinstance(func, ast.Name):
                    # Simple call: foo()
                    calls.append((func.id, "simple"))

                elif isinstance(func, ast.Attribute):
                    # Could be method call: self.foo(), obj.method(), or chained: a.b.c()
                    attr_name = func.attr

                    if isinstance(func.value, ast.Name):
                        # x.foo() - could be self.foo() or module.func()
                        if func.value.id == "self":
                            calls.append((attr_name, "method"))
                        else:
                            # Could be module.function or object.method
                            calls.append((f"{func.value.id}.{attr_name}", "chained"))
                            # Also track just the attribute name
                            calls.append((attr_name, "simple"))
                    else:
                        # Chained call like a.b.c() - just track the final method name
                        calls.append((attr_name, "chained"))

        return calls

    def _resolve_call_target(self, call_name: str, call_type: str,
                             caller_module: str, entity_lookup: Dict[str, int]) -> Optional[int]:
        """
        Resolve a call name to an entity ID.

        Attempts to match in order:
        1. Full qualified name in same module
        2. Short name match
        3. Dotted name if it looks like module.function
        """
        # Try full qualified name in same module
        qualified_name = f"{caller_module}.{call_name}"
        if qualified_name in entity_lookup:
            return entity_lookup[qualified_name]

        # Try direct lookup (handles both short names and qualified names)
        if call_name in entity_lookup:
            return entity_lookup[call_name]

        # For chained calls like "module.func", try the full name
        if "." in call_name:
            if call_name in entity_lookup:
                return entity_lookup[call_name]

        return None
