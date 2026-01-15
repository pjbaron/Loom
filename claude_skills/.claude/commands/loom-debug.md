# /loom-debug - Debug Context for Errors

THE PRIMARY DEBUGGING TOOL. Get comprehensive context for understanding and fixing an error. Use this immediately after a test fails or an error occurs.

## Usage
```
/loom-debug <error_message> [file_path]
```

## Examples
- `/loom-debug "AttributeError: 'NoneType' object has no attribute 'id'"`
- `/loom-debug "KeyError: 'user'" src/auth.py`
- `/loom-debug "ImportError: cannot import name 'foo'"`

## Instructions

Run the Loom debug context command:

```bash
/mnt/f/experiments/Loom/loom debug "$ARGUMENTS"
```

This automatically includes:
- Trace data from recent test runs
- Call stack analysis
- Static analysis of involved functions
- Previous hypotheses about similar errors
- Similar past failures and their resolutions

**USE THIS FIRST** when debugging any failure. It provides everything needed to understand the problem in one block.
