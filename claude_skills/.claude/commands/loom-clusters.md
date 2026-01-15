# /loom-clusters - Analyze File Cohesion

Analyze cohesion within a file to identify refactoring opportunities. Shows which functions belong together.

## Usage
```
/loom-clusters <file_path> [--json]
```

## Examples
- `/loom-clusters src/auth.py`
- `/loom-clusters tracer.py --json`

## Instructions

Run the Loom clusters command:

```bash
/mnt/f/experiments/Loom/loom clusters "$ARGUMENTS"
```

Output shows:
- Groups of related functions
- Cohesion scores
- Suggestions for extraction
- Dependencies between clusters
