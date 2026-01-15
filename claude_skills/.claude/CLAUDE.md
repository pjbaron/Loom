# Project: ClaudeOnClaude

This project contains Loom (a code understanding toolkit) and the Drill Deep game.

## Loom Integration

**Loom** is a code understanding tool suite available via `/loom-*` slash commands. It provides:
- Static analysis and call graph navigation
- Semantic code search
- Debugging context with trace analysis
- Knowledge base for findings and hypotheses
- TODO/work item tracking

### When to Use Loom

**ALWAYS use Loom commands before making changes:**

1. **Before modifying any function/class:**
   - `/loom-impact <name>` - Check what breaks if you change it
   - `/loom-callers <name>` - See what depends on it
   - `/loom-about <name>` - Check existing knowledge

2. **When debugging errors:**
   - `/loom-debug <error_message>` - PRIMARY debugging tool
   - `/loom-attempted-fixes --entity <name>` - See what's been tried
   - `/loom-last-failure` - See call tree from failed test

3. **When exploring unfamiliar code:**
   - `/loom-understand <query>` - Semantic search
   - `/loom-class <name>` or `/loom-module <name>` - Get explanations
   - `/loom-architecture` - High-level overview

4. **When planning work:**
   - `/loom-todo-add <title>` - Track work items
   - `/loom-todo-next` - Get next item to work on
   - `/loom-clusters <file>` - Identify refactoring opportunities

5. **When recording findings:**
   - `/loom-note <content>` - Record analysis findings
   - `/loom-hypothesis <text>` - Record debugging hypotheses
   - `/loom-failure-log <what_tried>` - Record failed approaches

### Project Management

Loom supports multiple projects. Each project has its own `.loom/store.db` database.

**Setting up a new project:**
```bash
/loom-ingest "Drill Deep"    # Ingests and sets as active project
```

**Switching between projects:**
```bash
# Use --project flag with any command (also sets it as active)
/loom-stats --project Loom
/loom-architecture --project "Drill Deep"

# Or use the project subcommand directly
./loom project show          # Show current active project
./loom project set "Drill Deep"
./loom project clear
```

**How it works:**
- The active project is stored in `~/.config/loom/active_project`
- All Loom commands use the active project by default
- Using `--project <path>` switches the active project
- `/loom-ingest` automatically sets the ingested path as active

**Check current project:**
```bash
/loom-stats    # Shows "Project: /path/to/active/project" at the top
```

## Project Structure

```
ClaudeOnClaude/
├── Loom/                    # Code understanding toolkit (Python)
│   ├── loom                 # CLI entry point
│   ├── loom_tools.py        # Python API
│   └── ...
├── Drill Deep/              # HTML5 incremental game
│   ├── src/                 # JavaScript source
│   └── deep-drill-gdd.md    # Design document
├── Drill Deep tasks/        # Task batches for Loom task runner
├── task_runner.py           # Batch task executor
└── .claude/
    └── commands/            # Loom slash commands
```

## Task Batch Workflow

When working on task batches (via task_runner.py):

1. **Before writing tasks:** Use `/loom-understand` and `/loom-architecture` to understand the codebase
2. **For bug fixes:** Use `/loom-debug` to get full context
3. **For refactoring:** Use `/loom-impact` and `/loom-clusters`
4. **Track progress:** Use `/loom-todo-*` commands

## Languages Supported by Loom

- Python (full support with ast parsing)
- JavaScript/TypeScript (supported for ingestion and analysis)
- ActionScript 3 (supported via tree-sitter)
- C++ (supported via tree-sitter)
