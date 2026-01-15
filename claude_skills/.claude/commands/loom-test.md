# /loom-test - Smart Test Runner

Run tests with smart selection and automatic tracing. Failed tests automatically capture trace data for debugging.

## Usage
```
/loom-test [path] [options]
```

## Options
- `--mode=full` - Full tracing (always persist)
- `--mode=fail` - Failure-focused mode (default, lower overhead)

## Examples
- `/loom-test` - Run all tests with smart selection
- `/loom-test test_auth.py` - Run specific test file
- `/loom-test --mode=full` - Full tracing for detailed analysis

## Instructions

Run the Loom test command:

```bash
/mnt/f/experiments/Loom/loom test $ARGUMENTS
```

When tests fail:
1. Trace data is automatically captured
2. Use `/loom-debug` with the error message for analysis
3. Use `/loom-last-failure` to see the call tree
