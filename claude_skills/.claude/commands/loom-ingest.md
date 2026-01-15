# /loom-ingest - Index a Codebase

Ingest or re-ingest a codebase to build the Loom database. Run this when analyzing a new project or after significant code changes.

## Usage
```
/loom-ingest <path>
```

## Examples
- `/loom-ingest .`
- `/loom-ingest ../Drill\ Deep/src`
- `/loom-ingest /path/to/project`

## Instructions

Run the Loom ingest command:

```bash
/mnt/f/experiments/Loom/loom ingest "$ARGUMENTS"
```

This will:
- Parse all Python, JavaScript, and TypeScript files
- Build call graph and dependency analysis
- Generate embeddings for semantic search
- Store everything in `.loom/store.db`

**Run this before using other Loom commands on a new codebase.**
