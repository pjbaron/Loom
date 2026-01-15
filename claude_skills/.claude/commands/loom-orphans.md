# /loom-orphans - Find Dead Code & Wiring Issues

Find entities with no connections and uncalled methods - detect incomplete wiring.

## Usage
```
/loom-orphans
```

## Instructions

Run the Loom orphans command:

```bash
/mnt/f/experiments/Loom/loom orphans
```

## Output Sections

### 1. LIKELY WIRING ISSUES (Most Important!)

Shows `set*`, `init*`, `configure*` methods that are **defined but never called**.

Example:
```
🚨 LIKELY WIRING ISSUES - Uncalled Setup Methods:

These set*/init*/configure* methods are never called - probable bugs!

  ⚠️  Map.Map.setTileImages() [line 853]
  ⚠️  PlayerController.setMap() [line 148]
```

**Action**: These are often bugs! Check if they should be called during initialization.

### 2. Uncalled Methods/Functions

All methods that exist but are never called. Includes:
- Constructors (usually fine - called via `new`)
- Getters/setters (accessed as properties)
- Future-use methods (will be used in later tasks)

### 3. Orphan Entities

Entities with NO relationships at all - completely disconnected code.

## When to Use

**ALWAYS run after verification tasks** to catch wiring bugs before they become runtime errors.

Example bug caught: `Map.setTileImages()` was defined but never called, so tiles never rendered.
