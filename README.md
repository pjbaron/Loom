# Loom

**Code understanding toolkit for AI agents and developers**

Loom builds a semantic graph of your codebase, enabling intelligent code navigation, impact analysis, and debugging assistance. Designed to work seamlessly with Claude Code as an agent skill.

## Features

- **Semantic Code Search** - Find code by meaning, not just text matching
- **Impact Analysis** - See what breaks before you change it
- **Call Graph Navigation** - Trace callers and callees across your codebase
- **Debug Context** - Get comprehensive context for errors including traces and related code
- **Knowledge Base** - Record findings, hypotheses, and notes linked to code entities
- **TODO Tracking** - Persistent work queue with detailed task prompts
- **Test Intelligence** - Smart test selection based on code changes
- **Multi-Language Support** - Python, JavaScript, TypeScript, C++ (extensible via tree-sitter)

## Installation

### From Source

```bash
git clone https://github.com/anthropics/loom.git
cd loom
pip install -e .
```

### With Language Support

```bash
# Python only (no extra dependencies)
pip install -e .

# With JavaScript/TypeScript support
pip install -e ".[javascript]"

# With C++ support
pip install -e ".[cpp]"

# All languages
pip install -e ".[all-languages]"

# Everything including dev tools
pip install -e ".[all]"
```

## Quick Start

```bash
# Index your codebase
./loom ingest .

# Search for code semantically
./loom understand "authentication logic"

# Check impact before changing a function
./loom impact process_user_data

# Find all callers of a function
./loom callers validate_input

# Get debug context for an error
./loom debug "AttributeError: 'NoneType' has no attribute 'id'"

# Run tests with smart selection
./loom test
```

## Claude Code Integration

Loom is designed to work as a Claude Code skill. Copy the skill definition to your project:

```bash
# Project-level (recommended)
cp -r .claude/skills/loom /path/to/your/project/.claude/skills/

# Or user-level (available in all projects)
cp -r .claude/skills/loom ~/.config/claude/skills/
```

Then Claude will automatically use Loom when you ask things like:
- "Study this project" / "Analyse this codebase" - indexes and provides architecture overview
- "What calls this function?" - finds all callers
- "What breaks if I change this?" - impact analysis
- "Help me debug this error" - comprehensive debug context
- "Find code related to authentication" - semantic search
- "How does the payment system work?" - explains modules/classes

### Slash Commands

Loom provides slash commands for direct invocation:

| Command | Description |
|---------|-------------|
| `/loom-understand <query>` | Semantic code search |
| `/loom-impact <name>` | Impact analysis |
| `/loom-callers <name>` | Find all callers |
| `/loom-class <name>` | Explain a class |
| `/loom-module <name>` | Explain a module |
| `/loom-debug <error>` | Get debugging context |
| `/loom-tests <name>` | Find relevant tests |
| `/loom-architecture` | Codebase overview |

## Command Reference

### Code Understanding

```bash
# Semantic search
./loom understand "database connection pooling"

# Explain a class with all its methods
./loom class UserAuthentication

# Explain a module
./loom module auth_handlers

# Find what calls a function
./loom callers process_payment

# Analyze change impact
./loom impact update_user_profile
```

### Architecture Analysis

```bash
# High-level architecture overview
./loom architecture

# Find most connected code (potential refactoring targets)
./loom central 10

# Find dead code (no callers)
./loom orphans

# Find path between two entities
./loom path UserModel validate_credentials

# Analyze file cohesion
./loom clusters src/auth.py
```

### Debugging

```bash
# Get comprehensive debug context
./loom debug "KeyError: 'user_id'" auth.py

# View last test failure trace
./loom last-failure

# Run tests with smart tracing
./loom test

# Run specific tests
./loom test tests/test_auth.py
```

### Knowledge Management

```bash
# Add a note
./loom note "The cache invalidation happens in two places"

# Document why code exists
./loom intent process_legacy_data "Handles v1 API format for backwards compatibility"

# Record a debugging hypothesis
./loom hypothesis "The race condition is in the connection pool" --about ConnectionPool

# Resolve a hypothesis
./loom resolve 42 yes  # or 'no'

# Get all knowledge about an entity
./loom about UserAuthentication

# Search notes
./loom search-notes "race condition"
```

### Failure Tracking

```bash
# Log a failed fix attempt
./loom failure-log "Tried adding mutex lock" --context "Still getting race condition" --file pool.py

# Query past failures
./loom attempted-fixes --entity ConnectionPool
./loom attempted-fixes --file pool.py

# See recent failures
./loom attempted-fixes --days 7
```

### TODO Management

```bash
# Add a task
./loom todo add "Refactor authentication module" --prompt "Split into separate OAuth and JWT handlers" --tag refactor

# View queue
./loom todo list
./loom todo list --all  # Include completed

# Get next task
./loom todo next

# Mark complete
./loom todo done 42

# Prioritize
./loom todo move 42 top
```

### Codebase Management

```bash
# Initial indexing
./loom ingest .

# Re-index after changes
./loom ingest .

# View statistics
./loom stats

# List supported languages
./loom languages
```

## Supported Languages

| Language | Parser | File Extensions |
|----------|--------|-----------------|
| Python | Built-in `ast` | `.py`, `.pyw` |
| JavaScript | tree-sitter | `.js`, `.mjs`, `.cjs`, `.jsx` |
| TypeScript | tree-sitter | `.ts`, `.tsx` |
| C++ | tree-sitter | `.h`, `.hpp`, `.cpp`, `.cc`, `.cxx` |

### Adding New Languages

Loom is extensible via [tree-sitter](https://tree-sitter.github.io/), which supports 165+ languages. See `docs/adding-languages.md` for a guide on adding new language support.

## How It Works

1. **Ingestion**: Loom parses your source files using language-specific parsers (Python's `ast` module or tree-sitter grammars)

2. **Graph Building**: Entities (modules, classes, functions, methods) and relationships (calls, imports, contains) are stored in a SQLite database

3. **Semantic Search**: Optional sentence-transformer embeddings enable semantic code search

4. **Runtime Tracing**: The pytest plugin captures call traces during test execution for debugging

5. **Knowledge Base**: Notes, hypotheses, and findings are linked to code entities and persist across sessions

## Database Location

Loom stores its database at `.loom/store.db` in your project root. This file should be added to `.gitignore` (already included in the default `.gitignore`).

## Python API

```python
from loom_tools import (
    understand,
    what_calls,
    what_breaks_if_i_change,
    explain_class,
    debug_context,
    add_todo,
    get_todos,
    log_failed_attempt,
)

# Semantic search
results = understand("handle user authentication")

# Impact analysis
impact = what_breaks_if_i_change("validate_token")

# Debug context
context = debug_context("AttributeError in process_request")

# Track work
add_todo("Fix token validation", "The JWT expiry check is off by one hour")
```

## Project Structure

```
loom/
├── loom                    # CLI entry point
├── cli.py                  # CLI implementation
├── codestore.py            # Core graph database
├── loom_tools.py           # High-level Python API
├── ingestion.py            # Code parsing and indexing
├── schema.py               # Database schema
├── parsers/                # Language-specific parsers
│   ├── python_parser.py    # Python (ast)
│   ├── js_ts_parser.py     # JavaScript/TypeScript (tree-sitter)
│   └── cpp_parser.py       # C++ (tree-sitter)
├── *_storage.py            # Storage mixins (notes, todos, traces, etc.)
├── *_tools.py              # Tool implementations
└── tests/                  # Test suite
```

## Contributing

Contributions are welcome! Areas of interest:

- **New language parsers** - Add support for Go, Rust, Java, Ruby, etc.
- **Analysis improvements** - Better call graph resolution, type inference
- **IDE integrations** - VS Code extension, Neovim plugin
- **Performance** - Incremental indexing, faster semantic search

See `CONTRIBUTING.md` for guidelines.

## License

MIT License - see `LICENSE` for details.

## Acknowledgments

- [tree-sitter](https://tree-sitter.github.io/) for multi-language parsing
- [sentence-transformers](https://www.sbert.net/) for semantic embeddings
- [Claude Code](https://claude.ai/code) for the agent skill framework
