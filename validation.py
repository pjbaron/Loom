"""
Code validation module for cross-language reference checking.

Validates:
- DOM references: JS getElementById/querySelector calls vs HTML element IDs
- Import resolution: JS/TS imports vs actual file existence
- Function arity: Function calls vs function definitions (future)

Reports:
- ERRORS: Verifiable issues that must be fixed
- WARNINGS: Patterns that cannot be verified statically (LLM should review)
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


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

        # Combine results
        result.errors.extend(dom_result.errors)
        result.errors.extend(import_result.errors)
        result.warnings.extend(dom_result.warnings)
        result.warnings.extend(import_result.warnings)

        # Combine stats
        result.stats = {
            'dom': dom_result.stats,
            'imports': import_result.stats,
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
