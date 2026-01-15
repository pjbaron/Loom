# /loom-last-failure - Show Last Failed Trace

Show the call tree from the most recent failed trace run. Use this immediately after a test fails.

## Usage
```
/loom-last-failure
```

## Instructions

Run the Loom last-failure command:

```bash
cd /mnt/f/experiments/ClaudeOnClaude/Loom && python3 -c "from loom_tools import last_failure; print(last_failure())"
```

Shows:
- Exception type and message
- Failing function
- Full call stack with arguments
- Variable values at failure point
- Full traceback
