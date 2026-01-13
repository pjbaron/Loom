---
name: loom
description: >
  Code understanding and impact analysis for Python, JavaScript, TypeScript, and C++ codebases.
  Builds a semantic graph for intelligent navigation, debugging, and knowledge tracking.
  Use when:
  - Starting work on a new/unfamiliar codebase (index and analyze it first)
  - Modifying code (understand what exists, check what breaks)
  - Debugging errors (get comprehensive context)
  - Refactoring (find callers, check impact)
  - Finding usages of functions/classes
  - Tracking failed fix attempts to avoid repeating mistakes
  - Managing work queue and tracking tasks
  Trigger phrases: "study the project", "analyse the project", "analyze the codebase",
  "understand this codebase", "index the project", "what calls", "what uses", "what breaks",
  "understand this code", "find usages", "impact of changing", "explain this class",
  "debug this error", "what have we tried", "log failure", "attempted fixes",
  "add todo", "what's next", "todo list", "work queue", "codebase overview",
  "architecture overview", "how does this work"
---

# Loom: Code Understanding Tools

Loom provides semantic code understanding via a graph database. Use it to understand code BEFORE modifying it.

## First-Time Setup

When starting work on a new codebase, **always ingest first**:

```bash
loom ingest .
```

This indexes all supported files (Python, JavaScript, TypeScript, C++) and builds the semantic graph. The database is stored at `.loom/store.db`.

**Check if already indexed:**
```bash
loom stats
```

If stats shows 0 entities, run `loom ingest .` first.

## Quick Commands

| Task | Command |
|------|---------|
| **Index codebase** | `loom ingest .` |
| **Get overview** | `loom architecture` |
| **Search code** | `loom understand "query"` |
| **Explain class** | `loom class ClassName` |
| **Explain module** | `loom module module_name` |
| **Find callers** | `loom callers function_name` |
| **Check impact** | `loom impact function_name` |
| **Debug error** | `loom debug "error message"` |
| **Run tests** | `loom test` |
| **View stats** | `loom stats` |

## Studying a New Codebase

When asked to "study", "analyse", or "understand" a project:

```bash
# 1. Index the codebase (if not already done)
loom ingest .

# 2. Get high-level overview
loom architecture

# 3. See statistics
loom stats

# 4. Find central/important code
loom central 10

# 5. Search for specific functionality
loom understand "authentication"
loom understand "database queries"
```

## Impact Analysis Before Changes

**Always check impact before modifying shared code:**

```bash
# What breaks if I change this function?
loom impact process_user_data

# Who calls this?
loom callers validate_input

# Find relevant tests
loom tests validate_input
```

## Debugging Workflow

```bash
# 1. Run tests with tracing
loom test

# 2. Get debug context for error
loom debug "AttributeError: 'NoneType' has no attribute 'id'"

# 3. View last failure trace
loom last-failure
```

The `loom debug` command returns:
- Runtime trace data (call stack at failure)
- Static analysis (what the code does, what calls it)
- Related hypotheses from past debugging
- Similar past failures
- Suggested tests to run

## Knowledge Management

Record findings as you work:

```bash
# Add a note
loom note "The cache invalidation has a race condition"

# Document intent
loom intent process_legacy "Handles v1 API for backwards compatibility"

# Record hypothesis
loom hypothesis "Race condition in connection pool" --about ConnectionPool

# Get all knowledge about entity
loom about ConnectionPool

# Search notes
loom search-notes "race condition"
```

## Failure Tracking

Avoid repeating failed approaches:

```bash
# Log what didn't work
loom failure-log "Tried mutex lock" --context "Still deadlocks" --file pool.py

# Check what's been tried
loom attempted-fixes --entity ConnectionPool
```

## TODO Management

```bash
# Add task
loom todo add "Refactor auth module" --prompt "Split OAuth and JWT" --tag refactor

# View queue
loom todo list
loom todo next

# Complete task
loom todo done 42
```

## Architecture Analysis

```bash
# High-level overview
loom architecture

# Most connected code (refactoring targets)
loom central 10

# Dead code (no callers)
loom orphans

# Path between entities
loom path UserModel validate_credentials

# File cohesion analysis
loom clusters src/auth.py
```

## Supported Languages

| Language | Extensions |
|----------|------------|
| Python | `.py`, `.pyw` |
| JavaScript | `.js`, `.mjs`, `.cjs`, `.jsx` |
| TypeScript | `.ts`, `.tsx` |
| C++ | `.h`, `.hpp`, `.cpp`, `.cc`, `.cxx` |

## When To Use Loom

| Situation | Action |
|-----------|--------|
| "Study/analyze this project" | `loom ingest .` then `loom architecture` |
| "How does X work?" | `loom class X` or `loom module X` |
| "I need to change X" | `loom impact X` first |
| "Where is X used?" | `loom callers X` |
| "Find code that does Y" | `loom understand "Y"` |
| "Debug this error" | `loom debug "error"` |
| "What have we tried?" | `loom attempted-fixes --entity X` |
| "Track this work" | `loom todo add "title"` |
