# /loom-tests - Find Relevant Tests

Find test files and test functions relevant to a given entity. Use this before modifying code to know which tests to run.

## Usage
```
/loom-tests <entity_name>
```

## Examples
- `/loom-tests CodeStore`
- `/loom-tests process_request`
- `/loom-tests validate_user`

## Instructions

Run the Loom tests command:

```bash
/mnt/f/experiments/Loom/loom tests "$ARGUMENTS"
```

The output shows:
- Test files that directly test the entity
- Test files that indirectly use the entity
- Suggested pytest commands to run relevant tests
