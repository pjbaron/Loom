# /loom-todo-list - List TODO Items

List all TODOs in the Loom work queue.

## Usage
```
/loom-todo-list [options]
```

## Options
- `--all` - Include completed and combined items
- `--status <status>` - Filter by status (pending, in_progress, completed)
- `--tag <tag>` - Filter by tag

## Examples
- `/loom-todo-list`
- `/loom-todo-list --all`
- `/loom-todo-list --tag bug`
- `/loom-todo-list --status in_progress`

## Instructions

Run the Loom todo list command:

```bash
/mnt/f/experiments/Loom/loom todo list $ARGUMENTS
```

Output shows:
- TODO ID (for use with other commands)
- Title and status
- Tags and priority
- Creation date
