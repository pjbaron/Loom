# /loom-intent - Document Why Code Exists

Document the intent/purpose of an entity - WHY it exists, not just what it does. Critical for understanding legacy code.

## Usage
```
/loom-intent <entity_name> <why_it_exists>
```

## Examples
- `/loom-intent validate_user "Centralizes all auth checks to ensure consistent security policy"`
- `/loom-intent _legacy_handler "Backwards compatibility for v1 API clients, remove after 2024"`

## Instructions

Run the Loom intent command:

```bash
/mnt/f/experiments/Loom/loom intent $ARGUMENTS
```

Intent notes are linked to the entity and shown when using `/loom-about <entity>`.
