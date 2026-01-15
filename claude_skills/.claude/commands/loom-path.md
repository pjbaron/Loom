# /loom-path - Find Connection Between Entities

Find the call path between two entities to understand how they relate.

## Usage
```
/loom-path <from_entity> <to_entity>
```

## Examples
- `/loom-path main process_request`
- `/loom-path User.save Database.commit`
- `/loom-path test_auth validate_token`

## Instructions

Run the Loom path command:

```bash
/mnt/f/experiments/Loom/loom path $ARGUMENTS
```

The output shows:
- Shortest call path between entities
- Intermediate functions
- Alternative paths if multiple exist
