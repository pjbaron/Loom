# Loom Validation Feature - Implementation Status

## Completed
1. **HTML Parser** (`parsers/html_parser.py`) - Extracts DOM element IDs as entities
2. **JS Parser Extension** (`parsers/js_ts_parser.py`) - Tracks `getElementById`/`querySelector` calls as `dom_reference` relationships
3. **Cross-file refs table** (`schema.py` v8 migration) - Stores references where target may be in different file
4. **Ingestion update** (`ingestion.py`) - Stores DOM references in `cross_file_refs` table
5. **Validation module** (`validation.py`) - `CodeValidator` class with `validate_dom_references()` and `validate_imports()`
6. **CLI command** (`cli.py`) - Added `validate` subparser
7. **Slash command** (`.claude/commands/loom-validate.md`) - Created skill file

## To Verify
1. Run `./loom validate --help` - may fail due to missing `refactor.py` import in cli.py
2. Test full validation on diamonddig_js project to confirm it catches the gameContainer bug

## Known Issue
`cli.py` imports `from refactor import cmd_clusters` but `refactor.py` may not exist. This blocks the validate command from running. Options:
- Find where refactor.py is located
- Make the import conditional
- Remove the import if unused

## Test Command
Once working, test with:
```bash
cd /mnt/f/experiments/ClaudeOnClaude
./loom ingest diamonddig_js/tasks_002_core_systems
./loom validate --level warn -v
```

Should report ERROR: `gameContainer` not found (HTML has `gameCanvas` instead).
