# /loom-failure-log - Log Failed Fix Attempt

Record a failed fix attempt to avoid repeating unsuccessful approaches. Essential for complex debugging sessions.

## Usage
```
/loom-failure-log <what_you_tried> [options]
```

## Options
- `--context <text>` - What you were working on
- `--entity <name>` - Related function/class
- `--file <path>` - Related file
- `--reason <text>` - Why it failed
- `--error <text>` - Error message

## Examples
- `/loom-failure-log "Added null check before access" --entity validate_user --reason "Error still occurs, null comes from caller"`
- `/loom-failure-log "Increased timeout to 30s" --context "Connection timeout issue" --reason "Timeout not the root cause"`

## Instructions

Run the Loom failure-log command:

```bash
/mnt/f/experiments/Loom/loom failure-log "$ARGUMENTS"
```

This prevents wasting time on approaches that have already been tried and failed.
