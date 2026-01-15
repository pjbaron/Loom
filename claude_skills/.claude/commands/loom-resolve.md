# /loom-resolve - Resolve a Hypothesis

Mark a hypothesis as confirmed or refuted after testing. This builds institutional knowledge about the codebase.

## Usage
```
/loom-resolve <note_id> <yes|no> [conclusion]
```

## Examples
- `/loom-resolve 42 yes "Confirmed: cache TTL was set to 0 in production config"`
- `/loom-resolve 42 no "Disproved: logs show no race condition"`

## Instructions

Run the Loom resolve command:

```bash
/mnt/f/experiments/Loom/loom resolve $ARGUMENTS
```

Get hypothesis IDs from `/loom-about` or `/loom-search-notes`.
