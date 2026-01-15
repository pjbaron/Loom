# /loom-central - Find Most Connected Code

Find the most connected entities in the codebase - the core functions and classes that everything depends on.

## Usage
```
/loom-central [count]
```

## Examples
- `/loom-central` (default: top 10)
- `/loom-central 20`

## Instructions

Run the Loom central entities command:

```bash
/mnt/f/experiments/Loom/loom central $ARGUMENTS
```

The output shows:
- Entities ranked by connectivity (callers + callees)
- Connection counts
- File locations

These are the most important entities to understand - changes to them have the widest impact.
