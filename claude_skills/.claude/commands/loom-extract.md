# /loom-extract - Preview Code Extraction

Preview extracting entities to a new module. Use this to plan refactoring.

## Usage
```
/loom-extract <entity1> [entity2...] --preview [--to <module_name>]
```

## Examples
- `/loom-extract start_trace_run end_trace_run record_call --preview`
- `/loom-extract validate_token refresh_token --to token_utils --preview`

## Instructions

Run the Loom extract command:

```bash
/mnt/f/experiments/Loom/loom extract $ARGUMENTS
```

Shows:
- What would be extracted
- Required imports for new module
- Changes needed in original module
- Potential circular dependency issues

**Always use --preview first** to verify the extraction makes sense.
