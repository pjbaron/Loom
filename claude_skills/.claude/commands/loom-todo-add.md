# /loom-todo-add - Add a TODO Item

Add a new TODO to the Loom work queue. TODOs persist across sessions and can have detailed prompts.

## Usage
```
/loom-todo-add <title> [options]
```

## Options
- `--prompt "Detailed instructions..."` - Full task description
- `--tag <tag>` - Add a tag (can repeat)
- `--critical` - Mark as critical/blocking

## Examples
- `/loom-todo-add "Fix null pointer in validate_user"`
- `/loom-todo-add "Refactor auth module" --prompt "Extract token validation to separate file" --tag refactor`
- `/loom-todo-add "Security: sanitize inputs" --critical --tag security`

## Instructions

Run the Loom todo add command:

```bash
/mnt/f/experiments/Loom/loom todo add "$ARGUMENTS"
```

View todos with `/loom-todo-list`, get next item with `/loom-todo-next`.
