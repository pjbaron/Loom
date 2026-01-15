# /loom-callers - Find All Callers

Find all functions and methods that call a given entity. Use this to understand how code is used throughout the codebase.

## Usage
```
/loom-callers <entity_name>
```

## Examples
- `/loom-callers process_request`
- `/loom-callers CodeStore.add_entity`
- `/loom-callers validate`

## Instructions

Run the Loom callers command:

```bash
/mnt/f/experiments/Loom/loom callers "$ARGUMENTS"
```

Supports `ClassName.method_name` format for looking up specific methods.

The output shows:
- All direct callers with file locations
- Call context (what arguments are typically passed)
- Whether callers are in tests or production code
