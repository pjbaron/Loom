#!/usr/bin/env python3
"""
core_tools - Core query functions for Claude Code to understand codebases.

This module provides the primary query tools:
- understand: Semantic search for code
- what_calls: Find callers of a function
- what_breaks_if_i_change: Impact analysis
- which_tests: Find relevant tests
- explain_module: Module overview
- explain_class: Class overview

All functions auto-discover the .loom/store.db database.
"""

from pathlib import Path
from typing import Optional, List

from codestore import CodeStore

# Import shared utilities from loom_base
from loom_base import (
    _log_usage,
    _find_store,
    _find_entity_by_name,
    _get_file_location,
    _get_code_preview,
    _kind_label,
)


def _find_method_by_class_dot_name(store: CodeStore, name: str) -> Optional[dict]:
    """
    Find a method entity by 'ClassName.method_name' format.

    Uses the CodeStore API to query for methods with member_of relationship.
    """
    if "." not in name:
        return None

    parts = name.split(".")
    if len(parts) != 2:
        return None

    class_name, method_name = parts

    # First find the class
    classes = store.find_entities(name=class_name, kind="class")
    if not classes:
        return None

    # Prefer exact class name match
    exact_class = None
    for cls in classes:
        if cls["name"].split(".")[-1] == class_name:
            exact_class = cls
            break

    if not exact_class:
        exact_class = classes[0]

    # Now find method via member_of relationship
    methods = store.find_related(exact_class["id"], relation="member_of", direction="incoming")

    for method in methods:
        if method["kind"] == "method" and method["name"].split(".")[-1] == method_name:
            return method

    return None


def _format_entity_display_name(entity: dict) -> str:
    """Format entity name nicely for display, handling methods specially."""
    name = entity["name"]
    kind = entity.get("kind", "")

    if kind == "method":
        parts = name.split(".")
        if len(parts) >= 2:
            return f"{parts[-2]}.{parts[-1]}"

    return name


def understand(query: str) -> str:
    """
    Semantic search for code related to a query.

    Args:
        query: Natural language description of what you're looking for
               (e.g., "authentication code", "database connection handling")

    Returns:
        Formatted string with top 5 relevant code sections
    """
    _log_usage('understand', query, '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    try:
        results = store.semantic_search(query, limit=5)
    except RuntimeError as e:
        store.close()
        return f"Error: {e}"

    if not results:
        store.close()
        return f"No relevant code sections found for '{query}'."

    output_lines = [f"Found {len(results)} relevant code sections for '{query}':", ""]

    for i, result in enumerate(results, 1):
        # Handle both tuple format (entity, distance) and dict format from semantic_search
        if isinstance(result, tuple):
            entity, distance = result
        else:
            entity = result
            distance = result.get("distance")

        kind = _kind_label(entity["kind"])
        name = entity["name"]
        intent = entity.get("intent") or "No docstring"
        # Truncate long intents
        if len(intent) > 150:
            intent = intent[:147] + "..."
        preview = _get_code_preview(entity)
        file_loc = _get_file_location(entity)

        # Format nicely based on entity kind
        if kind == "method":
            # For methods, show Class.method format
            parts = name.split(".")
            if len(parts) >= 2:
                display_name = f"{parts[-2]}.{parts[-1]}"
            else:
                display_name = name
            output_lines.append(f"{i}. [{kind}] {display_name}")
            # Get parent class info via member_of relationship
            member_of = store.find_related(entity["id"], relation="member_of", direction="outgoing")
            if member_of:
                parent_class = member_of[0]
                class_loc = _get_file_location(parent_class)
                output_lines.append(f"   Member of: {parent_class['name'].split('.')[-1]} ({class_loc})")
        else:
            output_lines.append(f"{i}. [{kind}] {name}")

        output_lines.append(f"   Intent: {intent}")
        output_lines.append(f"   Code preview:")
        for line in preview.split("\n"):
            output_lines.append(f"      {line}")
        output_lines.append(f"   File: {file_loc}")
        output_lines.append("")

    store.close()
    return "\n".join(output_lines)


def what_calls(name: str) -> str:
    """
    Find all functions that call a given entity.

    Args:
        name: Name of the function/method to find callers for
              Supports formats:
              - Simple name: "my_function"
              - Full qualified: "module.ClassName.method_name"
              - Class.method: "ClassName.method_name" (for methods)

    Returns:
        Formatted list of callers with their locations
    """
    _log_usage('what_calls', name, '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    # First try standard lookup
    entity = _find_entity_by_name(store, name)

    # If not found and name looks like ClassName.method_name, try method lookup
    if not entity and "." in name:
        entity = _find_method_by_class_dot_name(store, name)

    if not entity:
        store.close()
        return f"Entity not found: '{name}'"

    callers = store.get_callers(entity["id"])

    # Format display name nicely for methods
    display_name = entity["name"]
    if entity["kind"] == "method":
        parts = display_name.split(".")
        if len(parts) >= 2:
            display_name = f"{parts[-2]}.{parts[-1]}"

    if not callers:
        store.close()
        return f"No callers found for '{display_name}'."

    output_lines = [f"Functions that call '{display_name}':", ""]

    for caller in callers:
        file_loc = _get_file_location(caller)
        # Format caller name nicely too
        caller_display = caller["name"]
        if caller["kind"] == "method":
            caller_parts = caller_display.split(".")
            if len(caller_parts) >= 2:
                caller_display = f"{caller_parts[-2]}.{caller_parts[-1]}"
        output_lines.append(f"- {caller_display} ({file_loc})")

    store.close()
    return "\n".join(output_lines)


def what_breaks_if_i_change(name: str) -> str:
    """
    Analyze the blast radius of changing an entity.

    Args:
        name: Name of the entity you plan to modify
              Supports formats:
              - Simple name: "my_function"
              - Full qualified: "module.ClassName.method_name"
              - Class.method: "ClassName.method_name" (for methods)

    Returns:
        Formatted impact analysis including:
        - Direct callers
        - Indirect dependencies
        - Affected test files
        - Risk assessment
    """
    _log_usage('what_breaks_if_i_change', name, '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    # First try standard lookup
    entity = _find_entity_by_name(store, name)

    # If not found and name looks like ClassName.method_name, try method lookup
    if not entity and "." in name:
        entity = _find_method_by_class_dot_name(store, name)

    if not entity:
        store.close()
        return f"Entity not found: '{name}'"

    # Use CodeStore's impact_analysis method
    impact = store.impact_analysis(entity["id"])

    # Format display name nicely
    display_name = _format_entity_display_name(entity)

    output_lines = [
        f"Impact Analysis for '{display_name}':",
        "=" * 50,
        "",
        f"Risk Score: {impact['risk_score']} (higher = more impact)",
        "",
    ]

    if impact["direct_callers"]:
        output_lines.append("Direct Callers (will immediately break):")
        for caller in impact["direct_callers"][:10]:
            caller_display = _format_entity_display_name(caller)
            file_loc = _get_file_location(caller)
            output_lines.append(f"  - {caller_display} ({file_loc})")
        if len(impact["direct_callers"]) > 10:
            output_lines.append(f"  ... and {len(impact['direct_callers']) - 10} more")
        output_lines.append("")

    if impact["indirect_dependents"]:
        output_lines.append("Indirect Dependents (may break):")
        for dep in impact["indirect_dependents"][:10]:
            dep_display = _format_entity_display_name(dep)
            file_loc = _get_file_location(dep)
            output_lines.append(f"  - {dep_display} ({file_loc})")
        if len(impact["indirect_dependents"]) > 10:
            output_lines.append(f"  ... and {len(impact['indirect_dependents']) - 10} more")
        output_lines.append("")

    if impact["affected_tests"]:
        output_lines.append("Tests to Run:")
        for test in impact["affected_tests"][:10]:
            output_lines.append(f"  - {test}")
        if len(impact["affected_tests"]) > 10:
            output_lines.append(f"  ... and {len(impact['affected_tests']) - 10} more")
        output_lines.append("")

    # Summary
    output_lines.append("-" * 50)
    output_lines.append("Summary:")
    output_lines.append(f"  {len(impact['direct_callers'])} direct caller(s)")
    output_lines.append(f"  {len(impact['indirect_dependents'])} indirect dependent(s)")
    output_lines.append(f"  {len(impact['affected_tests'])} test(s) should be run")

    store.close()
    return "\n".join(output_lines)


def which_tests(name: str) -> str:
    """
    Find test files relevant to an entity.

    Args:
        name: Name of the entity to find tests for

    Returns:
        List of relevant test files, sorted by relevance
    """
    _log_usage('which_tests', name, '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    entity = _find_entity_by_name(store, name)
    if not entity:
        store.close()
        return f"Entity not found: '{name}'"

    tests = store.suggest_tests(entity["id"])

    if not tests:
        store.close()
        return f"No relevant test files found for '{entity['name']}'."

    output_lines = [f"Relevant tests for '{entity['name']}':", ""]

    for i, test_name in enumerate(tests, 1):
        # Try to get file path for the test module
        test_modules = store.find_entities(name=test_name, kind="module")
        if test_modules:
            metadata = test_modules[0].get("metadata") or {}
            file_path = metadata.get("file_path", test_name)
            output_lines.append(f"{i}. {file_path}")
        else:
            output_lines.append(f"{i}. {test_name}")

    output_lines.append("")
    output_lines.append(f"Run these {len(tests)} test file(s) after making changes.")

    store.close()
    return "\n".join(output_lines)


def explain_module(name: str) -> str:
    """
    Get a structured overview of a module's contents.

    Args:
        name: Name of the module to explain

    Returns:
        Structured overview: functions, classes, and their purposes
    """
    _log_usage('explain_module', name, '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    # Find the module
    entity = _find_entity_by_name(store, name)
    if not entity:
        store.close()
        return f"Entity not found: '{name}'"

    if entity["kind"] != "module":
        # Try to find module with this name specifically
        modules = store.find_entities(name=name, kind="module")
        if modules:
            entity = modules[0]
        else:
            store.close()
            return f"'{name}' is a {entity['kind']}, not a module. Use a module name."

    # Get all children of this module
    children = store.find_related(entity["id"], relation="contains", direction="outgoing")

    functions = [c for c in children if c["kind"] == "function"]
    classes = [c for c in children if c["kind"] == "class"]
    variables = [c for c in children if c["kind"] == "variable"]

    module_intent = entity.get("intent") or "No module docstring"
    file_loc = _get_file_location(entity)

    output_lines = [
        f"Module: {entity['name']}",
        f"File: {file_loc}",
        "=" * 60,
        "",
        f"Purpose: {module_intent}",
        "",
        f"Contains: {len(functions)} functions, {len(classes)} classes, {len(variables)} variables",
        "",
    ]

    if functions:
        output_lines.append("Functions:")
        for func in sorted(functions, key=lambda x: x["name"]):
            short_name = func["name"].split(".")[-1]
            intent = func.get("intent") or "No docstring"
            if len(intent) > 80:
                intent = intent[:77] + "..."
            output_lines.append(f"  - {short_name}: {intent}")
        output_lines.append("")

    if classes:
        output_lines.append("Classes:")
        for cls in sorted(classes, key=lambda x: x["name"]):
            short_name = cls["name"].split(".")[-1]
            intent = cls.get("intent") or "No docstring"
            if len(intent) > 80:
                intent = intent[:77] + "..."
            # Get class methods from metadata
            metadata = cls.get("metadata") or {}
            methods = metadata.get("methods", [])
            method_count = len(methods) if methods else "?"
            output_lines.append(f"  - {short_name} ({method_count} methods): {intent}")
        output_lines.append("")

    if variables:
        output_lines.append("Module-level variables:")
        for var in sorted(variables, key=lambda x: x["name"]):
            short_name = var["name"].split(".")[-1]
            output_lines.append(f"  - {short_name}")
        output_lines.append("")

    store.close()
    return "\n".join(output_lines)


def explain_class(name: str) -> str:
    """
    Get a structured overview of a class and all its methods.

    Uses CodeStore API to:
    1. Query for the class entity by name
    2. Query for all methods with member_of relationship to that class
    3. Format nicely for LLM consumption

    Args:
        name: Name of the class to explain (can be partial or full qualified)

    Returns:
        Structured overview: class info, inheritance, and all methods with their signatures
    """
    _log_usage('explain_class', name, '')
    store = _find_store()
    if not store:
        return "Error: No Loom database found. Run './loom ingest <path>' first."

    # Find the class entity
    entity = _find_entity_by_name(store, name)

    if not entity:
        store.close()
        return f"Entity not found: '{name}'"

    if entity["kind"] != "class":
        # Try to find a class with this name specifically
        classes = store.find_entities(name=name, kind="class")
        if classes:
            # Prefer exact match on short name
            for cls in classes:
                if cls["name"].split(".")[-1] == name:
                    entity = cls
                    break
            else:
                entity = classes[0]
        else:
            store.close()
            return f"'{name}' is a {entity['kind']}, not a class. Use explain_module() for modules."

    # Get class metadata
    metadata = entity.get("metadata") or {}
    file_loc = _get_file_location(entity)
    class_intent = entity.get("intent") or "No class docstring"
    bases = metadata.get("bases", [])
    short_name = entity["name"].split(".")[-1]

    # Query for all methods with member_of relationship to this class
    methods = store.find_related(entity["id"], relation="member_of", direction="incoming")
    methods = [m for m in methods if m["kind"] == "method"]

    output_lines = [
        f"Class: {short_name}",
        f"Full name: {entity['name']}",
        f"File: {file_loc}",
        "=" * 60,
        "",
    ]

    # Show inheritance
    if bases:
        output_lines.append(f"Inherits from: {', '.join(bases)}")
        output_lines.append("")

    # Class docstring
    output_lines.append(f"Purpose: {class_intent}")
    output_lines.append("")

    # Method summary
    output_lines.append(f"Methods ({len(methods)}):")
    output_lines.append("-" * 40)

    if not methods:
        output_lines.append("  (no methods found)")
    else:
        # Sort methods: __init__ first, then dunder methods, then public, then private
        def method_sort_key(m):
            method_name = m["name"].split(".")[-1]
            if method_name == "__init__":
                return (0, method_name)
            elif method_name.startswith("__") and method_name.endswith("__"):
                return (1, method_name)
            elif method_name.startswith("_"):
                return (3, method_name)
            else:
                return (2, method_name)

        sorted_methods = sorted(methods, key=method_sort_key)

        for method in sorted_methods:
            method_name = method["name"].split(".")[-1]
            method_metadata = method.get("metadata") or {}
            signature = method_metadata.get("signature", "()")
            method_intent = method.get("intent") or "No docstring"

            # Truncate long intents
            if len(method_intent) > 100:
                method_intent = method_intent[:97] + "..."

            # Mark async methods
            is_async = method_metadata.get("is_async", False)
            async_prefix = "async " if is_async else ""

            output_lines.append(f"  {async_prefix}{method_name}{signature}")
            output_lines.append(f"    {method_intent}")
            output_lines.append("")

    store.close()
    return "\n".join(output_lines)
