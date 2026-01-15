# /loom-note - Add Analysis Note

Record an analysis finding or observation for future reference. Use this to document insights discovered during debugging or code review.

## Usage
```
/loom-note <content>
```

## Examples
- `/loom-note "The validate_user function silently returns None on database errors"`
- `/loom-note "This module uses the singleton pattern for connection pooling"`

## Instructions

Run the Loom note command:

```bash
/mnt/f/experiments/Loom/loom note "$ARGUMENTS"
```

Notes are stored in the Loom knowledge base and can be:
- Searched with `/loom-search-notes`
- Retrieved by entity with `/loom-about`
- Used to inform future debugging sessions
