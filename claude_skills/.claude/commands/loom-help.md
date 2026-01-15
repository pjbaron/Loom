# /loom-help - Loom Tools Reference

Show all available Loom commands and their purposes.

## Usage
```
/loom-help
```

## Instructions

Run the Loom help command:

```bash
/mnt/f/experiments/Loom/loom --help
```

## Quick Reference

**Debugging (use these first when fixing bugs):**
- `/loom-debug <error>` - Primary debugging tool, shows everything
- `/loom-last-failure` - Call tree from last failed test
- `/loom-attempted-fixes` - What's already been tried

**Understanding Code:**
- `/loom-understand <query>` - Semantic search
- `/loom-callers <name>` - What calls this
- `/loom-impact <name>` - What breaks if changed
- `/loom-class <name>` - Explain a class
- `/loom-module <name>` - Explain a module

**Architecture:**
- `/loom-architecture` - High-level overview
- `/loom-central` - Most connected code
- `/loom-path <from> <to>` - How entities connect

**Knowledge Management:**
- `/loom-note <content>` - Record finding
- `/loom-hypothesis <text>` - Record hypothesis
- `/loom-about <entity>` - All knowledge about entity

**Work Tracking:**
- `/loom-todo-add <title>` - Add TODO
- `/loom-todo-next` - Get next TODO
- `/loom-todo-done <id>` - Complete TODO

**Setup:**
- `/loom-ingest <path>` - Index a codebase
- `/loom-stats` - Codebase statistics
