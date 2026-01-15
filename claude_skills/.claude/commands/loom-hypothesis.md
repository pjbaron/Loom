# /loom-hypothesis - Record Debugging Hypothesis

Record a hypothesis during debugging. This helps track what you've considered and prevents circular debugging.

## Usage
```
/loom-hypothesis <hypothesis_text> [--about <entity>]
```

## Examples
- `/loom-hypothesis "The null pointer is from the cache returning stale data"`
- `/loom-hypothesis "Race condition between threads" --about process_queue`

## Instructions

Run the Loom hypothesis command:

```bash
/mnt/f/experiments/Loom/loom hypothesis "$ARGUMENTS"
```

After testing, resolve the hypothesis with `/loom-resolve`.

Hypotheses are tracked and shown in `/loom-debug` output to remind you what's been considered.
