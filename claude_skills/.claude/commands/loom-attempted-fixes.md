# /loom-attempted-fixes - Query Past Failed Attempts

See what fixes have already been tried for an entity or file. Use this before attempting a fix to avoid repeating failed approaches.

## Usage
```
/loom-attempted-fixes [options]
```

## Options
- `--entity <name>` - Filter by entity
- `--file <path>` - Filter by file
- `--tag <tag>` - Filter by tag
- `--search <text>` - Search in context

## Examples
- `/loom-attempted-fixes --entity validate_user`
- `/loom-attempted-fixes --file src/auth.py`
- `/loom-attempted-fixes recent --days 3`

## Instructions

Run the Loom attempted-fixes command:

```bash
/mnt/f/experiments/Loom/loom attempted-fixes $ARGUMENTS
```

**Check this BEFORE trying a fix** to avoid wasting time on approaches that have already failed.
