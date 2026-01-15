#!/usr/bin/env python3
"""
detection_tools - Static analysis issue detection for incomplete/broken code.

- TODO/FIXME/STUB comments indicating incomplete code
- Callbacks checked but never assigned (unconnected callbacks)
- Functions defined but never called (dead code, via orphans)
- Method calls on objects that lack those methods

These detections complement the cross-reference validation in validation.py.
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field

from codestore import CodeStore
from loom_base import _log_usage, _find_store


@dataclass
class DetectedIssue:
    """Represents a single detected issue."""
    category: str  # 'todo', 'callback', 'dead_code', 'missing_method'
    severity: str  # 'critical', 'high', 'medium', 'low'
    description: str
    file: str
    line: int
    entity: str = ""
    details: Dict = field(default_factory=dict)
    auto_fixable: bool = False
    fix_hint: str = ""

    def to_dict(self) -> Dict:
        return {
            'category': self.category,
            'severity': self.severity,
            'description': self.description,
            'file': self.file,
            'line': self.line,
            'entity': self.entity,
            'details': self.details,
            'auto_fixable': self.auto_fixable,
            'fix_hint': self.fix_hint
        }


@dataclass
class DetectionResult:
    """Result of detection run."""
    issues: List[DetectedIssue] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'issues': [i.to_dict() for i in self.issues],
            'stats': self.stats,
            'counts': {
                'total': len(self.issues),
                'critical': len([i for i in self.issues if i.severity == 'critical']),
                'high': len([i for i in self.issues if i.severity == 'high']),
                'medium': len([i for i in self.issues if i.severity == 'medium']),
                'low': len([i for i in self.issues if i.severity == 'low']),
                'auto_fixable': len([i for i in self.issues if i.auto_fixable])
            }
        }


# Patterns indicating incomplete code
TODO_PATTERNS = [
    # High priority - explicit incomplete markers
    (r'\bTODO\b[:\s]*(.{0,100})', 'todo', 'medium'),
    (r'\bFIXME\b[:\s]*(.{0,100})', 'fixme', 'high'),
    (r'\bHACK\b[:\s]*(.{0,100})', 'hack', 'medium'),
    (r'\bXXX\b[:\s]*(.{0,100})', 'xxx', 'high'),
    (r'\bSTUB\b[:\s]*(.{0,100})', 'stub', 'high'),

    # Code patterns indicating incomplete implementation
    (r'throw\s+new\s+Error\s*\(\s*[\'"]not\s+implemented', 'not_implemented', 'critical'),
    (r'throw\s+new\s+Error\s*\(\s*[\'"]TODO', 'not_implemented', 'critical'),
    (r'console\.(log|warn)\s*\(\s*[\'"]TODO', 'todo_log', 'high'),

    # Placeholder patterns
    (r'//\s*placeholder', 'placeholder', 'medium'),
    (r'//\s*temporary', 'temporary', 'medium'),
    (r'//\s*not\s+implemented', 'not_implemented', 'high'),
    (r'//\s*incomplete', 'incomplete', 'high'),

    # Empty implementations (function body is just a comment or pass)
    (r'{\s*//\s*TODO[^}]*}', 'empty_todo', 'high'),
]

# Callback patterns - these indicate callback-based APIs
CALLBACK_PATTERNS = [
    # JavaScript/TypeScript patterns
    (r'if\s*\(\s*(?:this\.)?(\w+Callback)\s*\)', 'callback_check'),
    (r'if\s*\(\s*(?:this\.)?on(\w+)\s*\)', 'on_handler_check'),
    (r'(?:this\.)?(\w+Callback)\s*&&', 'callback_guard'),
    (r'(?:this\.)?on(\w+)\s*&&', 'on_handler_guard'),
    (r'typeof\s+(?:this\.)?(\w+)\s*===?\s*[\'"]function[\'"]', 'typeof_function_check'),

    # Common callback property patterns
    (r'if\s*\(\s*(?:this\.)?(\w+Handler)\s*\)', 'handler_check'),
    (r'(?:this\.)?(\w+Handler)\s*&&', 'handler_guard'),
]

# Assignment patterns for callbacks
CALLBACK_ASSIGNMENT_PATTERNS = [
    r'\.(\w+Callback)\s*=',
    r'\.on(\w+)\s*=',
    r'\.(\w+Handler)\s*=',
    r'\[[\'"](on\w+)[\'"]\]\s*=',
]


class IssueDetector:
    """Detects incomplete code and wiring issues."""

    def __init__(self, store: CodeStore):
        self.store = store
        self.project_root = self._get_project_root()

    def _get_project_root(self) -> Path:
        """Get the project root from the store."""
        try:
            cursor = self.store.conn.execute(
                "SELECT value FROM metadata WHERE key = 'project_root'"
            )
            row = cursor.fetchone()
            if row:
                return Path(row[0])
        except Exception:
            pass  # metadata table may not exist in older databases

        # Fallback: try to get from file paths in entities
        try:
            cursor = self.store.conn.execute("""
                SELECT json_extract(metadata, '$.file_path') as fp
                FROM entities
                WHERE json_extract(metadata, '$.file_path') IS NOT NULL
                LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row[0]:
                # Try to find common parent directory
                return Path('.').resolve()
        except Exception:
            pass

        return Path('.')

    def detect_all(self, include_low: bool = False) -> DetectionResult:
        """Run all detections and return combined result."""
        result = DetectionResult()

        # Run each detection type
        todo_result = self.detect_todo_comments()
        callback_result = self.detect_unassigned_callbacks()
        dead_result = self.detect_dead_code()

        # Combine issues
        result.issues.extend(todo_result.issues)
        result.issues.extend(callback_result.issues)
        result.issues.extend(dead_result.issues)

        # Filter by severity if requested
        if not include_low:
            result.issues = [i for i in result.issues if i.severity != 'low']

        # Sort by severity (critical first)
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        result.issues.sort(key=lambda x: (severity_order.get(x.severity, 99), x.file, x.line))

        # Combine stats
        result.stats = {
            'todo': todo_result.stats,
            'callback': callback_result.stats,
            'dead_code': dead_result.stats,
        }

        return result

    def detect_todo_comments(self) -> DetectionResult:
        """Detect TODO/FIXME/STUB comments and incomplete implementations."""
        result = DetectionResult()

        # Get all source files from the store
        cursor = self.store.conn.execute("""
            SELECT DISTINCT
                json_extract(metadata, '$.file_path') as file_path
            FROM entities
            WHERE json_extract(metadata, '$.file_path') IS NOT NULL
        """)

        files_scanned = 0
        todos_found = 0

        for row in cursor.fetchall():
            file_path = row[0]
            if not file_path:
                continue

            full_path = self.project_root / file_path
            if not full_path.exists():
                continue

            files_scanned += 1

            try:
                content = full_path.read_text(encoding='utf-8', errors='ignore')
                lines = content.split('\n')

                for line_num, line in enumerate(lines, 1):
                    for pattern, marker_type, severity in TODO_PATTERNS:
                        match = re.search(pattern, line, re.IGNORECASE)
                        if match:
                            todos_found += 1
                            description = match.group(1).strip() if match.groups() else line.strip()

                            # Determine if this is auto-fixable
                            auto_fixable = False
                            fix_hint = ""

                            # Certain patterns are more actionable
                            if marker_type in ('stub', 'not_implemented', 'empty_todo'):
                                fix_hint = "Implementation required - check AS3 reference if available"
                            elif marker_type == 'todo':
                                fix_hint = "Review and implement or remove if obsolete"

                            result.issues.append(DetectedIssue(
                                category='todo',
                                severity=severity,
                                description=f"[{marker_type.upper()}] {description[:100]}",
                                file=file_path,
                                line=line_num,
                                entity="",
                                details={
                                    'marker_type': marker_type,
                                    'full_line': line.strip()[:200]
                                },
                                auto_fixable=auto_fixable,
                                fix_hint=fix_hint
                            ))
                            break  # One match per line is enough

            except Exception as e:
                pass  # Skip unreadable files

        result.stats = {
            'files_scanned': files_scanned,
            'todos_found': todos_found
        }

        return result

    def detect_unassigned_callbacks(self) -> DetectionResult:
        """
        Detect callbacks that are checked but never assigned.

        This finds patterns like:
            if (this.onComplete) { this.onComplete(); }
        where onComplete is never assigned anywhere in the codebase.
        """
        result = DetectionResult()

        # Get all source files
        cursor = self.store.conn.execute("""
            SELECT DISTINCT
                json_extract(metadata, '$.file_path') as file_path
            FROM entities
            WHERE json_extract(metadata, '$.file_path') IS NOT NULL
        """)

        # Track callback usage and assignments
        callback_checks: Dict[str, List[Tuple[str, int, str]]] = {}  # name -> [(file, line, context)]
        callback_assignments: Set[str] = set()

        files_scanned = 0

        for row in cursor.fetchall():
            file_path = row[0]
            if not file_path:
                continue

            full_path = self.project_root / file_path
            if not full_path.exists():
                continue

            files_scanned += 1

            try:
                content = full_path.read_text(encoding='utf-8', errors='ignore')
                lines = content.split('\n')

                for line_num, line in enumerate(lines, 1):
                    # Check for callback usage patterns
                    for pattern, pattern_type in CALLBACK_PATTERNS:
                        match = re.search(pattern, line)
                        if match:
                            callback_name = match.group(1)
                            # Normalize: onFoo -> onFoo, fooCallback -> fooCallback
                            if pattern_type.startswith('on_'):
                                callback_name = 'on' + callback_name

                            if callback_name not in callback_checks:
                                callback_checks[callback_name] = []
                            callback_checks[callback_name].append((file_path, line_num, line.strip()[:100]))

                    # Check for callback assignments
                    for pattern in CALLBACK_ASSIGNMENT_PATTERNS:
                        match = re.search(pattern, line)
                        if match:
                            callback_name = match.group(1)
                            callback_assignments.add(callback_name)
                            # Also add common variations
                            if callback_name.startswith('on'):
                                callback_assignments.add(callback_name)

            except Exception:
                pass

        # Find callbacks that are checked but never assigned
        unassigned = 0
        for callback_name, usages in callback_checks.items():
            # Check if this callback is ever assigned
            is_assigned = (
                callback_name in callback_assignments or
                callback_name.lower() in {c.lower() for c in callback_assignments}
            )

            if not is_assigned:
                unassigned += 1
                # Report the first usage as the issue location
                file_path, line_num, context = usages[0]

                result.issues.append(DetectedIssue(
                    category='callback',
                    severity='high',
                    description=f"Callback '{callback_name}' is checked but never assigned",
                    file=file_path,
                    line=line_num,
                    entity=callback_name,
                    details={
                        'callback_name': callback_name,
                        'usage_count': len(usages),
                        'usages': usages[:5],  # First 5 usages
                        'context': context
                    },
                    auto_fixable=False,
                    fix_hint=f"Wire up {callback_name} where the object is created/initialized"
                ))

        result.stats = {
            'files_scanned': files_scanned,
            'callbacks_found': len(callback_checks),
            'unassigned_callbacks': unassigned
        }

        return result

    def detect_dead_code(self) -> DetectionResult:
        """
        Detect likely dead code using the call graph.

        Focuses on:
        - Setup/init methods that are never called (likely wiring issues)
        - Public methods that are never called (potential dead code)
        """
        result = DetectionResult()

        # Get uncalled methods from store
        uncalled = self.store.get_uncalled_methods(exclude_private=True)

        if not uncalled:
            result.stats = {'uncalled_methods': 0, 'wiring_issues': 0}
            return result

        wiring_issues = 0

        # Patterns that indicate setup/wiring methods
        setup_patterns = ('set', 'init', 'configure', 'register', 'connect', 'wire', 'bind', 'attach', 'setup')

        for method in uncalled:
            name = method.get('name', '')
            short_name = name.split('.')[-1].lower()
            metadata = method.get('metadata') or {}
            file_path = metadata.get('file_path', '')
            line = metadata.get('lineno', metadata.get('start_line', 0))

            # Skip constructors
            if short_name in ('constructor', '__init__', '__new__'):
                continue

            # Determine severity based on method name pattern
            is_setup = any(short_name.startswith(p) for p in setup_patterns)

            if is_setup:
                severity = 'high'
                wiring_issues += 1
                description = f"Setup method '{name}' is never called - likely wiring issue"
                fix_hint = f"Call {name}() during initialization or remove if obsolete"
            else:
                severity = 'medium'
                description = f"Method '{name}' is defined but never called"
                fix_hint = "Verify if method is needed, wire it up or remove"

            result.issues.append(DetectedIssue(
                category='dead_code',
                severity=severity,
                description=description,
                file=file_path,
                line=line,
                entity=name,
                details={
                    'method_name': name,
                    'is_setup_method': is_setup
                },
                auto_fixable=False,
                fix_hint=fix_hint
            ))

        result.stats = {
            'uncalled_methods': len(uncalled),
            'wiring_issues': wiring_issues
        }

        return result


def detect_issues(
    check: str = "all",
    include_low: bool = False,
    output_json: bool = False
) -> str:
    """
    Detect incomplete code and wiring issues.

    Args:
        check: What to check - 'all', 'todo', 'callback', 'dead_code'
        include_low: Include low-severity issues
        output_json: Return JSON instead of formatted text

    Returns:
        Formatted issue report or JSON string
    """
    _log_usage('detect_issues', check, '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    try:
        detector = IssueDetector(store)

        if check == 'all':
            result = detector.detect_all(include_low)
        elif check == 'todo':
            result = detector.detect_todo_comments()
        elif check == 'callback':
            result = detector.detect_unassigned_callbacks()
        elif check == 'dead_code':
            result = detector.detect_dead_code()
        else:
            return f"Unknown check type: {check}"

        if output_json:
            return json.dumps(result.to_dict(), indent=2)

        return _format_detection_result(result)

    finally:
        store.close()


def detect_issues_json(check: str = "all", include_low: bool = False) -> Dict:
    """
    Detect issues and return as a dictionary (for programmatic use).

    Returns dict compatible with CRITICAL_ISSUES.json format.
    """
    _log_usage('detect_issues_json', check, '')
    store = _find_store()
    if not store:
        return {"error": "No Loom database found"}

    try:
        detector = IssueDetector(store)
        result = detector.detect_all(include_low)

        # Convert to CRITICAL_ISSUES.json format
        issues = []
        for issue in result.issues:
            issues.append({
                "type": issue.severity,
                "category": issue.category,
                "description": issue.description,
                "file": issue.file,
                "line": issue.line,
                "entity": issue.entity,
                "details": issue.fix_hint,
                "auto_fixable": issue.auto_fixable
            })

        return {
            "issues": issues,
            "stats": result.stats,
            "counts": result.to_dict()["counts"]
        }

    finally:
        store.close()


def _format_detection_result(result: DetectionResult) -> str:
    """Format detection result for human reading."""
    lines = []

    counts = result.to_dict()['counts']
    lines.append("=" * 60)
    lines.append("ISSUE DETECTION REPORT")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Total issues found: {counts['total']}")
    lines.append(f"  Critical: {counts['critical']}")
    lines.append(f"  High: {counts['high']}")
    lines.append(f"  Medium: {counts['medium']}")
    lines.append(f"  Low: {counts['low']}")
    lines.append(f"  Auto-fixable: {counts['auto_fixable']}")
    lines.append("")

    # Group by category
    by_category: Dict[str, List[DetectedIssue]] = {}
    for issue in result.issues:
        if issue.category not in by_category:
            by_category[issue.category] = []
        by_category[issue.category].append(issue)

    # Category display order and labels
    category_labels = {
        'todo': '📝 TODO/FIXME Comments',
        'callback': '🔗 Unassigned Callbacks',
        'dead_code': '💀 Dead/Uncalled Code',
        'missing_method': '❓ Missing Methods'
    }

    for category in ['callback', 'dead_code', 'todo', 'missing_method']:
        issues = by_category.get(category, [])
        if not issues:
            continue

        label = category_labels.get(category, category.title())
        lines.append("-" * 60)
        lines.append(f"{label} ({len(issues)} issues)")
        lines.append("-" * 60)

        # Group critical/high issues first
        critical_high = [i for i in issues if i.severity in ('critical', 'high')]
        other = [i for i in issues if i.severity not in ('critical', 'high')]

        for issue in critical_high[:20]:  # Limit display
            severity_icon = '🔴' if issue.severity == 'critical' else '🟠'
            lines.append(f"\n{severity_icon} [{issue.severity.upper()}] {issue.description}")
            lines.append(f"   File: {issue.file}:{issue.line}")
            if issue.entity:
                lines.append(f"   Entity: {issue.entity}")
            if issue.fix_hint:
                lines.append(f"   Fix: {issue.fix_hint}")

        if other:
            lines.append(f"\n  ... and {len(other)} more {category} issues (medium/low priority)")

        lines.append("")

    # Stats summary
    if result.stats:
        lines.append("-" * 60)
        lines.append("Detection Statistics")
        lines.append("-" * 60)
        for category, stats in result.stats.items():
            if isinstance(stats, dict):
                stat_str = ", ".join(f"{k}: {v}" for k, v in stats.items())
                lines.append(f"  {category}: {stat_str}")

    return "\n".join(lines)


def cmd_issues(args):
    """CLI handler for issue detection command."""
    from codestore import CodeStore

    store = CodeStore(args.db)
    detector = IssueDetector(store)

    # Run detection
    include_low = getattr(args, 'level', 'high') == 'all'

    if args.check == 'all':
        result = detector.detect_all(include_low)
    elif args.check == 'todo':
        result = detector.detect_todo_comments()
    elif args.check == 'callback':
        result = detector.detect_unassigned_callbacks()
    elif args.check == 'dead_code':
        result = detector.detect_dead_code()
    else:
        print(f"Unknown check type: {args.check}")
        store.close()
        return 1

    store.close()

    # Filter by severity level
    if not include_low:
        result.issues = [i for i in result.issues if i.severity != 'low']

    # Output format
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        # Return non-zero if critical/high issues found
        critical_high = len([i for i in result.issues if i.severity in ('critical', 'high')])
        return 1 if critical_high > 0 else 0

    # Output as CRITICAL_ISSUES.json format for task runner integration
    if getattr(args, 'critical_issues', False):
        issues = []
        for issue in result.issues:
            issues.append({
                "type": issue.severity,
                "category": issue.category,
                "description": issue.description,
                "file": issue.file,
                "line": issue.line,
                "entity": issue.entity,
                "details": issue.fix_hint
            })
        print(json.dumps(issues, indent=2))
        return 0

    # Human-readable output
    print(_format_detection_result(result))

    # Return non-zero if critical/high issues found
    critical_high = len([i for i in result.issues if i.severity in ('critical', 'high')])
    return 1 if critical_high > 0 else 0


# Export for use in other modules
__all__ = [
    'DetectedIssue',
    'DetectionResult',
    'IssueDetector',
    'detect_issues',
    'detect_issues_json',
    'cmd_issues',
]
