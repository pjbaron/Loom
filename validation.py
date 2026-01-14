"""
Code validation module for cross-language reference checking.

Validates:
- DOM references: JS getElementById/querySelector calls vs HTML element IDs
- Import resolution: JS/TS imports vs actual file existence
- JS Syntax: Real AST parsing via esprima for syntax errors
- Function arity: Function calls vs function definitions (future)

Reports:
- ERRORS: Verifiable issues that must be fixed
- WARNINGS: Patterns that cannot be verified statically (LLM should review)
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

# Optional esprima for JS syntax validation
try:
    import esprima
    HAS_ESPRIMA = True
except ImportError:
    esprima = None
    HAS_ESPRIMA = False


@dataclass
class ValidationIssue:
    """Represents a single validation issue."""
    level: str  # 'error' or 'warning'
    category: str  # 'dom_reference', 'import', 'arity', etc.
    message: str
    file: str
    line: int
    details: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'level': self.level,
            'category': self.category,
            'message': self.message,
            'file': self.file,
            'line': self.line,
            'details': self.details
        }


@dataclass
class ValidationResult:
    """Result of validation run."""
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def to_dict(self) -> Dict:
        return {
            'errors': [e.to_dict() for e in self.errors],
            'warnings': [w.to_dict() for w in self.warnings],
            'stats': self.stats
        }


class CodeValidator:
    """Validates code for cross-language reference issues."""

    def __init__(self, store):
        """Initialize with a CodeStore instance."""
        self.store = store

    def validate_all(self) -> ValidationResult:
        """Run all validations and return combined result."""
        result = ValidationResult()

        # Run validations for each cross-file ref type
        dom_result = self.validate_dom_references()
        import_result = self.validate_unresolved_imports()
        method_result = self.validate_method_calls()
        syntax_result = self.validate_js_syntax()

        # Combine results
        result.errors.extend(dom_result.errors)
        result.errors.extend(import_result.errors)
        result.errors.extend(method_result.errors)
        result.errors.extend(syntax_result.errors)
        result.warnings.extend(dom_result.warnings)
        result.warnings.extend(import_result.warnings)
        result.warnings.extend(method_result.warnings)
        result.warnings.extend(syntax_result.warnings)

        # Combine stats
        result.stats = {
            'dom': dom_result.stats,
            'imports': import_result.stats,
            'methods': method_result.stats,
            'syntax': syntax_result.stats,
            'total_errors': len(result.errors),
            'total_warnings': len(result.warnings)
        }

        return result

    def validate_unresolved_imports(self) -> ValidationResult:
        """Validate that unresolved import statements reference existing files.

        Reads from cross_file_refs table where ref_type = 'imports'.
        These are imports where the target module wasn't found during ingestion.
        """
        result = ValidationResult()

        # Get all unresolved imports from cross_file_refs
        cursor = self.store.conn.execute("""
            SELECT
                cfr.target_name,
                cfr.source_file,
                cfr.line_number,
                cfr.verifiable,
                cfr.verification_reason,
                cfr.metadata,
                e.name as source_entity_name
            FROM cross_file_refs cfr
            JOIN entities e ON cfr.source_entity_id = e.id
            WHERE cfr.ref_type = 'imports'
        """)

        total_refs = 0
        relative_imports = 0
        missing_imports = 0
        external_imports = 0

        for row in cursor.fetchall():
            total_refs += 1
            import_path = row['target_name']
            source_file = row['source_file'] or 'unknown'
            line = row['line_number'] or 0
            source_entity = row['source_entity_name']

            # Check if it's a relative import (can be validated)
            if import_path.startswith('./') or import_path.startswith('../'):
                relative_imports += 1

                # Resolve the import path relative to source file
                if source_file != 'unknown':
                    source_dir = Path(source_file).parent
                    resolved = self._resolve_import(source_dir, import_path)

                    if resolved is None:
                        missing_imports += 1
                        result.errors.append(ValidationIssue(
                            level='error',
                            category='import',
                            message=f"Import '{import_path}' not found",
                            file=source_file,
                            line=line,
                            details={
                                'import_path': import_path,
                                'source_module': source_entity,
                            }
                        ))
            else:
                # External/node_modules import - not validated
                external_imports += 1

        result.stats = {
            'total_unresolved': total_refs,
            'relative_imports': relative_imports,
            'missing_imports': missing_imports,
            'external_imports': external_imports
        }

        return result

    def validate_dom_references(self) -> ValidationResult:
        """Validate that JS DOM references point to existing HTML elements.

        Checks:
        - getElementById('id') references exist in HTML files
        - querySelector('#id') references exist in HTML files
        - Reports unverifiable dynamic references as warnings
        """
        result = ValidationResult()

        # Get all HTML element IDs (dom_element entities)
        html_ids = set()
        html_id_files = {}  # Map ID -> file where it's defined

        cursor = self.store.conn.execute("""
            SELECT name, metadata FROM entities
            WHERE kind = 'dom_element'
        """)

        for row in cursor.fetchall():
            # Name format is "filename#elementId"
            name = row['name']
            if '#' in name:
                element_id = name.split('#', 1)[1]
                html_ids.add(element_id)
                metadata = json.loads(row['metadata']) if row['metadata'] else {}
                html_id_files[element_id] = metadata.get('file_path', 'unknown')

        # Get all DOM references from cross_file_refs table
        cursor = self.store.conn.execute("""
            SELECT
                cfr.target_name,
                cfr.source_file,
                cfr.line_number,
                cfr.verifiable,
                cfr.verification_reason,
                cfr.metadata,
                e.name as source_entity_name
            FROM cross_file_refs cfr
            JOIN entities e ON cfr.source_entity_id = e.id
            WHERE cfr.ref_type = 'dom_reference'
        """)

        total_refs = 0
        verifiable_refs = 0
        unverifiable_refs = 0
        missing_refs = 0

        for row in cursor.fetchall():
            total_refs += 1
            target_name = row['target_name']
            source_file = row['source_file'] or 'unknown'
            line = row['line_number'] or 0
            verifiable = row['verifiable']
            reason = row['verification_reason']
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            source_entity = row['source_entity_name']

            method = metadata.get('method', 'getElementById')
            selector = metadata.get('selector', target_name)

            if not verifiable:
                # Cannot verify - add warning
                unverifiable_refs += 1
                result.warnings.append(ValidationIssue(
                    level='warning',
                    category='dom_reference',
                    message=f"Cannot verify DOM reference: {method}({selector}) - {reason or 'Dynamic value'}",
                    file=source_file,
                    line=line,
                    details={
                        'method': method,
                        'selector': selector,
                        'reason': reason or 'Dynamic value',
                        'caller': source_entity
                    }
                ))
            else:
                verifiable_refs += 1
                # Check if element exists
                if target_name not in html_ids:
                    missing_refs += 1
                    result.errors.append(ValidationIssue(
                        level='error',
                        category='dom_reference',
                        message=f"DOM element '{target_name}' not found - {method}('{selector}') references non-existent element",
                        file=source_file,
                        line=line,
                        details={
                            'method': method,
                            'selector': selector,
                            'element_id': target_name,
                            'caller': source_entity,
                            'available_ids': list(html_ids)[:10]  # Show some available IDs
                        }
                    ))

        result.stats = {
            'total_references': total_refs,
            'verifiable': verifiable_refs,
            'unverifiable': unverifiable_refs,
            'missing': missing_refs,
            'html_elements': len(html_ids)
        }

        return result

    def validate_method_calls(self) -> ValidationResult:
        """Validate method calls against known class definitions.

        Detects issues like:
        - Calling obj.getFoo() when class only has obj.foo (getter pattern mismatch)
        - Calling methods that don't exist on any known class

        Uses heuristics since JavaScript is dynamically typed:
        - Matches method calls against all class methods in the codebase
        - Special detection for getFoo/setFoo patterns vs foo properties
        """
        import re

        result = ValidationResult()

        # Build lookup of all class methods and properties
        # Maps method_name -> list of (class_name, is_getter)
        class_methods: Dict[str, List[Tuple[str, bool]]] = {}
        class_properties: Dict[str, List[str]] = {}  # property_name -> [class_names]

        # Get all class entities with their methods
        cursor = self.store.conn.execute("""
            SELECT name, metadata FROM entities
            WHERE kind = 'class'
        """)

        for row in cursor.fetchall():
            class_name = row['name']
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            methods = metadata.get('methods', [])

            for method in methods:
                if method not in class_methods:
                    class_methods[method] = []
                # Check if it's a getter (starts with 'get' followed by uppercase)
                is_getter = method.startswith('get') and len(method) > 3 and method[3].isupper()
                class_methods[method].append((class_name, is_getter))

        # Get all method entities to find getters/setters
        cursor = self.store.conn.execute("""
            SELECT e.name, e.metadata, r.target_id
            FROM entities e
            JOIN relationships r ON e.id = r.source_id
            WHERE e.kind = 'method' AND r.relation = 'member_of'
        """)

        for row in cursor.fetchall():
            method_name = row['name'].split('.')[-1]  # Get just the method name
            class_id = row['target_id']

            # Get class name
            class_row = self.store.conn.execute(
                "SELECT name FROM entities WHERE id = ?", (class_id,)
            ).fetchone()
            if not class_row:
                continue
            class_name = class_row['name']

            # Track in class_methods if not already there
            if method_name not in class_methods:
                class_methods[method_name] = []
            if (class_name, False) not in class_methods[method_name]:
                class_methods[method_name].append((class_name, False))

            # Check if this looks like a property accessor (getter/setter in JS)
            # JS getters are defined as `get propName()` in class body
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            code = metadata.get('code', '')

            # Detect JS getter syntax: get foo() { ... }
            if re.match(r'^\s*get\s+', code):
                prop_name = method_name
                if prop_name not in class_properties:
                    class_properties[prop_name] = []
                if class_name not in class_properties[prop_name]:
                    class_properties[prop_name].append(class_name)

        # Also check entity code for getter patterns in classes
        cursor = self.store.conn.execute("""
            SELECT name, code FROM entities
            WHERE kind = 'class' AND code IS NOT NULL
        """)

        for row in cursor.fetchall():
            class_name = row['name']
            code = row['code'] or ''

            # Find getter definitions: get propertyName() { ... }
            getter_pattern = r'\bget\s+(\w+)\s*\(\s*\)'
            for match in re.finditer(getter_pattern, code):
                prop_name = match.group(1)
                if prop_name not in class_properties:
                    class_properties[prop_name] = []
                if class_name not in class_properties[prop_name]:
                    class_properties[prop_name].append(class_name)

                # Also add as a "method" for matching
                if prop_name not in class_methods:
                    class_methods[prop_name] = []
                if (class_name, True) not in class_methods[prop_name]:
                    class_methods[prop_name].append((class_name, True))

        # Get all method_call references
        cursor = self.store.conn.execute("""
            SELECT
                cfr.target_name,
                cfr.source_file,
                cfr.line_number,
                cfr.metadata,
                e.name as caller_name
            FROM cross_file_refs cfr
            JOIN entities e ON cfr.source_entity_id = e.id
            WHERE cfr.ref_type = 'method_call'
        """)

        total_calls = 0
        getter_mismatches = 0
        unknown_methods = 0

        for row in cursor.fetchall():
            total_calls += 1
            method_name = row['target_name']
            source_file = row['source_file'] or 'unknown'
            line = row['line_number'] or 0
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            caller = row['caller_name']
            full_expr = metadata.get('full_expression', method_name)
            obj_path = metadata.get('object_path', [])

            # Check for getFoo() when foo property exists
            if method_name.startswith('get') and len(method_name) > 3:
                # Extract property name: getFoo -> foo (lowercase first letter)
                prop_name = method_name[3].lower() + method_name[4:]

                # Check if this method exists on any class
                method_exists = method_name in class_methods

                # Check if property exists but method doesn't
                if not method_exists and prop_name in class_properties:
                    getter_mismatches += 1
                    classes_with_prop = class_properties[prop_name]

                    result.errors.append(ValidationIssue(
                        level='error',
                        category='method_call',
                        message=f"'{method_name}()' not found - did you mean '{prop_name}'? "
                                f"(property exists on {', '.join(classes_with_prop)})",
                        file=source_file,
                        line=line,
                        details={
                            'called_method': method_name,
                            'suggested_property': prop_name,
                            'full_expression': full_expr,
                            'classes_with_property': classes_with_prop,
                            'caller': caller
                        }
                    ))
                    continue

            # Check for setFoo() when foo property exists
            if method_name.startswith('set') and len(method_name) > 3:
                prop_name = method_name[3].lower() + method_name[4:]
                method_exists = method_name in class_methods

                if not method_exists and prop_name in class_properties:
                    getter_mismatches += 1
                    classes_with_prop = class_properties[prop_name]

                    result.errors.append(ValidationIssue(
                        level='error',
                        category='method_call',
                        message=f"'{method_name}()' not found - did you mean '{prop_name} = ...'? "
                                f"(property exists on {', '.join(classes_with_prop)})",
                        file=source_file,
                        line=line,
                        details={
                            'called_method': method_name,
                            'suggested_property': prop_name,
                            'full_expression': full_expr,
                            'classes_with_property': classes_with_prop,
                            'caller': caller
                        }
                    ))
                    continue

        result.stats = {
            'total_method_calls': total_calls,
            'getter_mismatches': getter_mismatches,
            'unknown_methods': unknown_methods,
            'known_class_methods': len(class_methods),
            'known_properties': len(class_properties)
        }

        return result

    def validate_js_syntax(self) -> ValidationResult:
        """Validate JavaScript files using esprima AST parsing.

        Detects:
        - Syntax errors with precise line/column information
        - Duplicate top-level identifiers
        - Dangerous patterns (eval, with, debugger, Function constructor)
        - Leftover template markers

        Requires esprima: pip install esprima
        """
        result = ValidationResult()

        if not HAS_ESPRIMA:
            result.warnings.append(ValidationIssue(
                level='warning',
                category='syntax',
                message="esprima not installed - run 'pip install esprima' for JS syntax validation",
                file='',
                line=0,
                details={}
            ))
            result.stats = {'skipped': True, 'reason': 'esprima not installed'}
            return result

        # Get all JavaScript files from entities (file_path is in metadata JSON)
        cursor = self.store.conn.execute("""
            SELECT DISTINCT json_extract(metadata, '$.file_path') as file_path
            FROM entities
            WHERE metadata IS NOT NULL
              AND (json_extract(metadata, '$.file_path') LIKE '%.js'
                   OR json_extract(metadata, '$.file_path') LIKE '%.mjs'
                   OR json_extract(metadata, '$.file_path') LIKE '%.cjs')
        """)

        js_files = [row['file_path'] for row in cursor.fetchall() if row['file_path']]

        total_files = 0
        valid_files = 0
        syntax_errors = 0
        duplicate_warnings = 0
        dangerous_patterns = 0

        for file_path in js_files:
            total_files += 1
            path = Path(file_path)

            if not path.exists():
                continue

            try:
                js_code = path.read_text(encoding='utf-8', errors='replace')
            except Exception as e:
                result.warnings.append(ValidationIssue(
                    level='warning',
                    category='syntax',
                    message=f"Could not read file: {e}",
                    file=file_path,
                    line=0,
                    details={}
                ))
                continue

            # Validate this file
            validation = self._validate_js_file(js_code, file_path)

            if validation['is_valid']:
                valid_files += 1

                # Check for duplicates
                top_ids = validation.get('top_level_identifiers', {})
                duplicates = top_ids.get('duplicates', [])
                for dup in duplicates:
                    duplicate_warnings += 1
                    result.warnings.append(ValidationIssue(
                        level='warning',
                        category='syntax',
                        message=f"Duplicate identifier '{dup}' at top level",
                        file=file_path,
                        line=0,
                        details={
                            'identifier': dup,
                            'type': 'duplicate'
                        }
                    ))

                # Check for dangerous patterns
                dangers = validation.get('dangerous_patterns', [])
                for danger in dangers:
                    dangerous_patterns += 1
                    pattern = danger.get('pattern', 'unknown')
                    loc = danger.get('loc', {})
                    line = loc.get('line', 0) if loc else 0

                    result.warnings.append(ValidationIssue(
                        level='warning',
                        category='syntax',
                        message=f"Dangerous pattern: {pattern}",
                        file=file_path,
                        line=line,
                        details={
                            'pattern': pattern,
                            'location': loc
                        }
                    ))

                # Check for leftover markers
                markers = validation.get('leftover_markers', [])
                for marker in markers:
                    result.warnings.append(ValidationIssue(
                        level='warning',
                        category='syntax',
                        message=f"Leftover template marker: {marker}",
                        file=file_path,
                        line=0,
                        details={'marker': marker}
                    ))
            else:
                syntax_errors += 1
                error_msg = validation.get('syntax_error', 'Unknown syntax error')
                error_line = validation.get('error_line', 0)
                error_col = validation.get('error_column', 0)

                # Build context snippet
                context = validation.get('error_context_snippet', {})
                snippet_lines = context.get('lines', []) if context else []

                # Get enclosing function info if available
                enclosing = validation.get('enclosing_function', {})

                details = {
                    'error_column': error_col,
                    'module_type': validation.get('module_type', 'script')
                }

                if snippet_lines:
                    details['context'] = '\n'.join(snippet_lines[:7])

                if enclosing and enclosing.get('name'):
                    details['enclosing_function'] = enclosing.get('name')
                    details['function_start'] = enclosing.get('start_line')
                    details['function_end'] = enclosing.get('end_line')

                result.errors.append(ValidationIssue(
                    level='error',
                    category='syntax',
                    message=error_msg,
                    file=file_path,
                    line=error_line,
                    details=details
                ))

        result.stats = {
            'total_files': total_files,
            'valid_files': valid_files,
            'syntax_errors': syntax_errors,
            'duplicate_warnings': duplicate_warnings,
            'dangerous_patterns': dangerous_patterns
        }

        return result

    def _validate_js_file(self, js_code: str, file_path: str) -> Dict[str, Any]:
        """Validate a single JavaScript file using esprima.

        Returns a dict with:
        - is_valid: bool
        - syntax_error: error message if invalid
        - error_line, error_column: location if invalid
        - error_context_snippet: nearby code lines
        - enclosing_function: function containing the error
        - top_level_identifiers: {functions, variables, duplicates}
        - dangerous_patterns: list of {pattern, loc}
        - leftover_markers: list of marker types found
        """
        report: Dict[str, Any] = {
            'module_type': None,
            'is_valid': False,
            'syntax_error': None,
            'node_counts_by_type': {},
            'top_level_identifiers': {
                'functions': [],
                'variables': [],
                'duplicates': [],
            },
            'dangerous_patterns': [],
            'leftover_markers': [],
        }

        # Decide module vs script parsing based on import statements
        is_module = (re.search(r'^\s*import\s', js_code, flags=re.MULTILINE) is not None or
                     re.search(r'^\s*export\s', js_code, flags=re.MULTILINE) is not None)
        parse_fn = esprima.parseModule if is_module else esprima.parseScript
        report['module_type'] = 'module' if is_module else 'script'

        try:
            program = parse_fn(js_code, tolerant=False, loc=True, range=True)
            report['is_valid'] = True
        except Exception as exc:
            msg = str(exc)
            report['syntax_error'] = msg
            loc = self._extract_error_location(exc)
            report['syntax_error_detail'] = loc

            lines = js_code.splitlines()
            err_line = int(loc.get('line') or 0)
            err_col = int(loc.get('column') or 0)

            if err_line > 0:
                report['error_line'] = err_line
                report['error_column'] = err_col
                report['error_context_snippet'] = self._build_context_snippet(lines, err_line)

                # Try to extract enclosing function
                func_info = self._extract_function_at_error(js_code, err_line, err_col)
                if func_info:
                    report['enclosing_function'] = func_info

            report['is_valid'] = False
            return report

        # Analyze valid code
        self._analyze_valid_js(program, js_code, report)
        return report

    def _extract_error_location(self, exc: Exception) -> Dict[str, Optional[int]]:
        """Extract line/column from esprima exception."""
        line_num: Optional[int] = None
        col_num: Optional[int] = None

        try:
            line_num = getattr(exc, 'lineNumber', None) or getattr(exc, 'line', None)
            col_num = getattr(exc, 'column', None)
        except Exception:
            pass

        if line_num is None or col_num is None:
            text = str(exc)
            m = re.search(r'Line\s+(?P<line>\d+)(?::(?P<col>\d+))?', text)
            if m:
                try:
                    line_num = int(m.group('line'))
                    col_str = m.group('col')
                    col_num = int(col_str) if col_str else col_num
                except Exception:
                    pass

            if line_num is None or col_num is None:
                m2 = re.search(r'\((?P<line>\d+):(?P<col>\d+)\)', text)
                if m2:
                    try:
                        line_num = int(m2.group('line'))
                        col_num = int(m2.group('col'))
                    except Exception:
                        pass

        return {'line': line_num, 'column': col_num}

    def _build_context_snippet(self, lines: List[str], error_line: int, radius: int = 6) -> Dict[str, Any]:
        """Build error context snippet around error line."""
        start = max(1, error_line - radius)
        end = min(len(lines), error_line + radius)
        snippet = lines[start - 1:end]
        return {'start_line': start, 'end_line': end, 'lines': snippet}

    def _traverse_ast(self, node) -> List[Any]:
        """Depth-first AST traversal."""
        stack = [node]
        seen: set = set()
        out: List[Any] = []

        while stack:
            cur = stack.pop()
            try:
                node_id = id(cur)
            except Exception:
                continue

            if node_id in seen:
                continue
            seen.add(node_id)

            if getattr(cur, 'type', None) is None:
                continue

            out.append(cur)

            for attr_name in dir(cur):
                if attr_name.startswith('_') or attr_name in ('type', 'range', 'loc'):
                    continue
                try:
                    value = getattr(cur, attr_name)
                except Exception:
                    continue

                if getattr(value, 'type', None) is not None:
                    stack.append(value)
                elif isinstance(value, (list, tuple)):
                    for item in value:
                        if getattr(item, 'type', None) is not None:
                            stack.append(item)

        return out

    def _extract_function_at_error(self, js_code: str, error_line: int, error_column: int = 0) -> Optional[Dict[str, Any]]:
        """Extract the innermost function containing the error location."""
        is_module = (re.search(r'^\s*import\s', js_code, flags=re.MULTILINE) is not None or
                     re.search(r'^\s*export\s', js_code, flags=re.MULTILINE) is not None)
        parse_fn = esprima.parseModule if is_module else esprima.parseScript

        try:
            program = parse_fn(js_code, tolerant=True, loc=True, range=True)
        except Exception:
            return None

        def _within_bounds(s_line: int, s_col: int, e_line: int, e_col: int) -> bool:
            if error_line < s_line or error_line > e_line:
                return False
            if error_line == s_line and error_column < s_col:
                return False
            if error_line == e_line and error_column > e_col:
                return False
            return True

        best_function = None
        smallest_span = None

        for node in self._traverse_ast(program):
            node_type = getattr(node, 'type', '')
            if node_type not in ('FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'):
                continue

            loc = getattr(node, 'loc', None)
            if not loc:
                continue

            start = getattr(loc, 'start', None)
            end = getattr(loc, 'end', None)
            if not start or not end:
                continue

            s_line = int(getattr(start, 'line', 0) or 0)
            s_col = int(getattr(start, 'column', 0) or 0)
            e_line = int(getattr(end, 'line', 0) or 0)
            e_col = int(getattr(end, 'column', 0) or 0)

            if not _within_bounds(s_line, s_col, e_line, e_col):
                continue

            rng = getattr(node, 'range', None)
            span = None
            if isinstance(rng, (list, tuple)) and len(rng) == 2:
                try:
                    span = int(rng[1]) - int(rng[0])
                except Exception:
                    pass

            if best_function is None or (span is not None and (smallest_span is None or span < smallest_span)):
                best_function = node
                smallest_span = span

        if best_function is None:
            return None

        # Extract function details
        loc = getattr(best_function, 'loc', None)
        start = getattr(loc, 'start', None)
        end = getattr(loc, 'end', None)

        name = None
        func_id = getattr(best_function, 'id', None)
        if getattr(func_id, 'name', None) is not None:
            name = func_id.name

        return {
            'name': name,
            'start_line': int(getattr(start, 'line', 0) or 0),
            'end_line': int(getattr(end, 'line', 0) or 0),
            'type': getattr(best_function, 'type', 'function')
        }

    def _analyze_valid_js(self, program, js_code: str, report: Dict[str, Any]) -> None:
        """Analyze valid JavaScript code for patterns and statistics."""
        top_functions: List[str] = []
        top_variables: List[str] = []

        for node in getattr(program, 'body', []) or []:
            if node.type == 'FunctionDeclaration' and getattr(node, 'id', None) is not None:
                top_functions.append(node.id.name)
            elif node.type == 'VariableDeclaration':
                for decl in getattr(node, 'declarations', []) or []:
                    if getattr(getattr(decl, 'id', None), 'type', None) == 'Identifier':
                        top_variables.append(decl.id.name)

        # Check for duplicates
        seen: set = set()
        dups: List[str] = []
        for name in top_functions + top_variables:
            if name in seen:
                dups.append(name)
            else:
                seen.add(name)

        report['top_level_identifiers'] = {
            'functions': top_functions,
            'variables': top_variables,
            'duplicates': sorted(set(dups)),
        }

        # Node type counts and dangerous patterns
        node_counts: Dict[str, int] = {}
        dangers: List[Dict[str, Any]] = []

        for node in self._traverse_ast(program):
            node_type = getattr(node, 'type', '')
            if not node_type:
                continue

            node_counts[node_type] = node_counts.get(node_type, 0) + 1

            # Check for dangerous patterns
            if node_type == 'WithStatement':
                dangers.append({'pattern': 'with_statement', 'loc': self._get_node_location(node)})
            elif node_type == 'DebuggerStatement':
                dangers.append({'pattern': 'debugger_statement', 'loc': self._get_node_location(node)})
            elif node_type == 'CallExpression':
                callee = getattr(node, 'callee', None)
                if getattr(callee, 'type', None) == 'Identifier' and getattr(callee, 'name', None) == 'eval':
                    dangers.append({'pattern': 'eval_call', 'loc': self._get_node_location(node)})
                if getattr(callee, 'type', None) == 'Identifier' and getattr(callee, 'name', None) == 'Function':
                    dangers.append({'pattern': 'function_constructor', 'loc': self._get_node_location(node)})
            elif node_type == 'NewExpression':
                callee = getattr(node, 'callee', None)
                if getattr(callee, 'type', None) == 'Identifier' and getattr(callee, 'name', None) == 'Function':
                    dangers.append({'pattern': 'function_constructor', 'loc': self._get_node_location(node)})

        report['node_counts_by_type'] = dict(sorted(node_counts.items()))
        report['dangerous_patterns'] = dangers

        # Check for leftover template markers
        leftover = []
        if re.search(r'<slot:\w+>', js_code):
            leftover.append('slot_start_marker')
        if re.search(r'</slot:\w+>', js_code):
            leftover.append('slot_end_marker')
        if re.search(r'<section:\w+>', js_code):
            leftover.append('section_start_marker')
        if re.search(r'</section:\w+>', js_code):
            leftover.append('section_end_marker')

        report['leftover_markers'] = sorted(set(leftover))

    def _get_node_location(self, node) -> Optional[Dict[str, int]]:
        """Extract location information from AST node."""
        loc = getattr(node, 'loc', None)
        if not loc:
            return None

        try:
            start = getattr(loc, 'start', None)
            if start is not None:
                return {
                    'line': int(getattr(start, 'line', None) or 0),
                    'column': int(getattr(start, 'column', None) or 0),
                }
        except Exception:
            pass

        return None

    def _resolve_import(self, source_dir: Path, import_path: str) -> Optional[Path]:
        """Resolve a relative import path to an actual file.

        Tries common extensions: .js, .ts, .jsx, .tsx, /index.js, etc.
        """
        # Normalize the path
        target = source_dir / import_path

        # Extensions to try
        extensions = ['.js', '.ts', '.jsx', '.tsx', '.mjs', '.cjs']
        index_files = ['index.js', 'index.ts', 'index.jsx', 'index.tsx']

        # Try direct path with extensions
        for ext in extensions:
            check_path = target.with_suffix(ext)
            if check_path.exists():
                return check_path

        # Try as directory with index file
        if target.is_dir():
            for index_file in index_files:
                check_path = target / index_file
                if check_path.exists():
                    return check_path

        # Try adding extensions to already-suffixed path
        target_str = str(target)
        for ext in extensions:
            check_path = Path(target_str + ext)
            if check_path.exists():
                return check_path

        return None


def cmd_validate(args):
    """Run code validation and report issues."""
    from codestore import CodeStore

    store = CodeStore(args.db)
    validator = CodeValidator(store)

    # Run validation
    if args.check == 'all':
        result = validator.validate_all()
    elif args.check == 'dom':
        result = validator.validate_dom_references()
    elif args.check == 'imports':
        result = validator.validate_unresolved_imports()
    elif args.check == 'methods':
        result = validator.validate_method_calls()
    elif args.check == 'syntax':
        result = validator.validate_js_syntax()
    else:
        print(f"Unknown check type: {args.check}")
        store.close()
        return 1

    # Output format
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        store.close()
        return 0 if not result.has_errors else 1

    # Human-readable output
    print("=" * 60)
    print("LOOM VALIDATION REPORT")
    print("=" * 60)

    # Show errors
    if result.errors:
        print(f"\nERRORS ({len(result.errors)}):")
        print("-" * 40)
        for issue in result.errors:
            print(f"  {issue.file}:{issue.line}")
            print(f"    [{issue.category}] {issue.message}")
            if args.verbose and issue.details:
                for key, value in issue.details.items():
                    if key != 'available_ids':  # Skip verbose lists
                        print(f"      {key}: {value}")
        print()

    # Show warnings
    if result.warnings:
        if args.level in ('all', 'warn'):
            print(f"\nWARNINGS ({len(result.warnings)}):")
            print("-" * 40)
            for issue in result.warnings:
                print(f"  {issue.file}:{issue.line}")
                print(f"    [{issue.category}] {issue.message}")
                if args.verbose and issue.details:
                    for key, value in issue.details.items():
                        print(f"      {key}: {value}")
            print()
        else:
            print(f"\n({len(result.warnings)} warnings hidden - use --level warn to show)")

    # Summary
    print("\nSUMMARY:")
    print(f"  Errors:   {len(result.errors)}")
    print(f"  Warnings: {len(result.warnings)}")

    if result.stats:
        print("\nSTATISTICS:")
        for category, stats in result.stats.items():
            if isinstance(stats, dict):
                print(f"  {category}:")
                for key, value in stats.items():
                    print(f"    {key}: {value}")
            else:
                print(f"  {category}: {stats}")

    store.close()

    # Return non-zero if errors found (useful for CI)
    if result.has_errors:
        print(f"\nValidation FAILED with {len(result.errors)} error(s)")
        return 1

    print("\nValidation PASSED")
    return 0
