# Contributing to Loom

Thank you for your interest in contributing to Loom! This document provides guidelines and information for contributors.

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/loom.git
   cd loom
   ```
3. Install development dependencies:
   ```bash
   pip install -e ".[all]"
   ```
4. Run tests to ensure everything works:
   ```bash
   pytest tests/
   ```

## Development Setup

### Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_analysis.py

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

### Code Style

We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

## Adding a New Language Parser

Loom uses tree-sitter for multi-language support. To add a new language:

### 1. Create the Parser

Create a new file in `parsers/`, e.g., `go_parser.py`:

```python
"""Go parser using tree-sitter."""

from pathlib import Path
from typing import List

try:
    import tree_sitter_go as tsgo
    from tree_sitter import Language, Parser
    TREE_SITTER_GO_AVAILABLE = True
except ImportError:
    TREE_SITTER_GO_AVAILABLE = False

from parsers.base import BaseParser, ParseResult


class GoParser(BaseParser):
    """Parser for Go source files."""

    def __init__(self):
        if not TREE_SITTER_GO_AVAILABLE:
            raise ImportError(
                "tree-sitter-go is required. "
                "Install with: pip install tree-sitter tree-sitter-go"
            )
        self._language = Language(tsgo.language())
        self._parser = Parser(self._language)

    @property
    def language(self) -> str:
        return "go"

    @property
    def file_extensions(self) -> List[str]:
        return [".go"]

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.file_extensions

    def parse_file(self, file_path: Path, source: str = None) -> ParseResult:
        # Implementation here
        pass
```

### 2. Register the Parser

Update `parsers/__init__.py`:

```python
from .go_parser import GoParser

__all__ = [..., 'GoParser']
```

### 3. Add to pyproject.toml

```toml
[project.optional-dependencies]
go = ["tree-sitter", "tree-sitter-go"]
```

### 4. Write Tests

Create `tests/parsers/test_go_parser.py` using existing parser tests as templates.

### 5. Add Test Fixtures

Create `tests/fixtures/go/` with sample Go files covering:
- Package declarations
- Functions and methods
- Structs and interfaces
- Import statements
- Nested structures

## Pull Request Process

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** with clear, focused commits

3. **Ensure tests pass**:
   ```bash
   pytest tests/
   ```

4. **Update documentation** if needed

5. **Submit a pull request** with:
   - Clear description of changes
   - Any related issue numbers
   - Screenshots/examples if applicable

## Code Guidelines

### General

- Keep functions focused and single-purpose
- Add docstrings to public functions and classes
- Handle errors gracefully with informative messages
- Avoid breaking backwards compatibility

### Parser Guidelines

- Inherit from `BaseParser`
- Implement all abstract methods
- Handle encoding issues gracefully
- Return meaningful error messages in `ParseResult.errors`
- Extract relationships (calls, imports, contains) accurately

### Testing Guidelines

- Write tests for new functionality
- Include edge cases (empty files, syntax errors, etc.)
- Use fixtures for test data
- Keep tests focused and independent

## Reporting Issues

When reporting issues, please include:

1. **Description**: Clear description of the problem
2. **Steps to reproduce**: Minimal steps to reproduce the issue
3. **Expected behavior**: What you expected to happen
4. **Actual behavior**: What actually happened
5. **Environment**: Python version, OS, Loom version
6. **Logs/errors**: Any error messages or stack traces

## Feature Requests

We welcome feature requests! Please include:

1. **Use case**: Why is this feature needed?
2. **Proposed solution**: How should it work?
3. **Alternatives considered**: Other approaches you've thought about
4. **Additional context**: Examples, mockups, etc.

## Areas for Contribution

### High Impact

- **New language parsers**: Go, Rust, Java, Ruby, C#, PHP
- **Incremental indexing**: Only re-parse changed files
- **Better call resolution**: Handle dynamic dispatch, decorators

### Medium Impact

- **IDE integrations**: VS Code extension, Neovim plugin
- **Export formats**: Mermaid diagrams, DOT graphs
- **Coverage integration**: Import coverage.py data

### Documentation

- **Tutorials**: Step-by-step guides
- **Examples**: Real-world usage examples
- **API documentation**: Detailed API reference

## Questions?

- Open an issue for questions about contributing
- Check existing issues and discussions first

Thank you for contributing to Loom!
