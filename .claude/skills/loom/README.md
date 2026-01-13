# Loom Skill

This directory contains the Claude Code skill definition for Loom.

**The actual Loom code lives at: `/mnt/f/experiments/ClaudeOnClaude/Loom/`**

## Contents

- `SKILL.md` - Skill definition with triggers, commands, and usage instructions

## Key Files in Main Directory

| File | Purpose |
|------|---------|
| `loom` | CLI entry point |
| `codestore.py` | Core CodeStore class (graph database, embeddings) |
| `loom_tools.py` | High-level API (understand, impact, callers, etc.) |
| `cli.py` | CLI implementation |

Do not duplicate code files here - this skill directory should only contain metadata.
