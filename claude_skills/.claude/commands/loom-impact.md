# /loom-impact - Change Impact Analysis

Analyze what breaks if you change a function, class, or method. Use this BEFORE modifying code to understand the blast radius of your changes.

## Usage
```
/loom-impact <entity_name>
```

## Examples
- `/loom-impact validate_user`
- `/loom-impact DatabaseConnection`
- `/loom-impact CodeStore.get_entity`

## Instructions

Run the Loom impact analysis:

```bash
/mnt/f/experiments/Loom/loom impact "$ARGUMENTS"
```

The output shows:
- Direct callers of the entity
- Transitive dependents (callers of callers)
- Test files that would be affected
- Risk assessment

**CRITICAL**: Always run this before refactoring or changing function signatures to avoid breaking dependent code.
