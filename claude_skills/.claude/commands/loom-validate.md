# /loom-validate - Cross-Language Code Validation

Validate code for cross-reference issues that cannot be caught by syntax checking alone.

## Usage
```
/loom-validate [--check <type>] [--level <level>]
```

## Options
- `--check all|dom|imports|exports|syntax|methods` - What to validate (default: all)
- `--level error|warn|all` - Minimum issue level to show (default: error)
- `--verbose` - Show detailed issue information
- `--json` - Output as JSON (for CI integration)

## Instructions

Run the Loom validate command:

```bash
/mnt/f/experiments/Loom/loom validate
```

For specific checks:
```bash
/mnt/f/experiments/Loom/loom validate --check dom --level warn -v
/mnt/f/experiments/Loom/loom validate --check exports  # Check named imports/exports
```

## What It Checks

**ERRORS (must fix):**
- DOM references: `getElementById('X')` where element `#X` doesn't exist in HTML
- Import resolution: `import './foo'` where file doesn't exist
- **Export validation**: `import { name } from './file'` where `name` is not exported (uses esbuild)
- Syntax errors: Invalid JavaScript syntax (uses esprima)

**WARNINGS (LLM should verify):**
- Dynamic DOM references: `getElementById(variable)` - cannot verify statically
- Template string selectors: `` getElementById(`${prefix}Id`) `` - dynamic value
- ES2020+ syntax that esprima doesn't support (optional chaining, nullish coalescing)

## Example Output

```
============================================================
LOOM VALIDATION REPORT
============================================================

ERRORS (2):
----------------------------------------
  src/main.js:29
    [dom_reference] DOM element 'gameContainer' not found - getElementById('gameContainer') references non-existent element

  src/utils.js:15
    [import] Import './missing.js' not found

WARNINGS (1):
----------------------------------------
  src/main.js:45
    [dom_reference] Cannot verify DOM reference: getElementById(elementId) - Dynamic value

SUMMARY:
  Errors:   2
  Warnings: 1
```

## When to Use

**ALWAYS run after:**
- Creating new HTML files with element IDs
- Adding new JavaScript DOM queries
- Refactoring element IDs or file structure

**Integrate with task_runner:**
Add as a post-task validation step to catch issues before they become runtime errors.
