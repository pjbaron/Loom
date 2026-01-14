"""
Database schema mixin for CodeStore.

Provides database initialization and migration logic:
- Core schema tables (entities, relationships, notes)
- Schema versioning
- Migrations for adding trace and file tracking tables

Extracted from codestore.py to reduce its size.
"""

import logging
import sqlite3


class SchemaMixin:
    """Mixin providing database schema initialization and migrations."""

    # Current schema version for migrations
    SCHEMA_VERSION = 8

    def _init_schema(self):
        """Initialize database schema."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,  -- 'module', 'class', 'function', 'method', 'variable'
                code TEXT,
                intent TEXT,         -- what this entity is meant to do
                metadata TEXT,       -- JSON blob for extra attributes
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                relation TEXT NOT NULL,  -- 'contains', 'calls', 'imports', 'inherits', 'uses', 'member_of'
                metadata TEXT,
                FOREIGN KEY (source_id) REFERENCES entities(id),
                FOREIGN KEY (target_id) REFERENCES entities(id)
            );

            CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
            CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
            CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id);

            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,  -- 'analysis', 'intent', 'hypothesis', 'todo', 'decision', 'bug'
                title TEXT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                source TEXT,  -- file path, session id, or 'manual'
                status TEXT DEFAULT 'active'  -- for hypotheses: 'active', 'confirmed', 'refuted'
            );

            CREATE TABLE IF NOT EXISTS note_links (
                note_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                link_type TEXT NOT NULL,  -- 'about', 'affects', 'explains', 'tests'
                PRIMARY KEY (note_id, entity_id, link_type),
                FOREIGN KEY (note_id) REFERENCES notes(id),
                FOREIGN KEY (entity_id) REFERENCES entities(id)
            );

            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );
        """)
        self.conn.commit()
        self._run_migrations()

    def _get_schema_version(self) -> int:
        """Get current schema version from database."""
        try:
            row = self.conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    def _set_schema_version(self, version: int):
        """Set schema version in database."""
        self.conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (version,))
        self.conn.commit()

    def _run_migrations(self):
        """Run any pending schema migrations."""
        current_version = self._get_schema_version()

        if current_version < 2:
            self._migrate_to_v2()
            self._set_schema_version(2)

        if current_version < 3:
            self._migrate_to_v3()
            self._set_schema_version(3)

        if current_version < 4:
            self._migrate_to_v4()
            self._set_schema_version(4)

        if current_version < 5:
            self._migrate_to_v5()
            self._set_schema_version(5)

        if current_version < 6:
            self._migrate_to_v6()
            self._set_schema_version(6)

        if current_version < 7:
            self._migrate_to_v7()
            self._set_schema_version(7)

        if current_version < 8:
            self._migrate_to_v8()
            self._set_schema_version(8)

    def _migrate_to_v2(self):
        """Migration v2: Add runtime tracing tables."""
        self.conn.executescript("""
            -- Each execution run (e.g., a test run, a script execution)
            CREATE TABLE IF NOT EXISTS trace_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                command TEXT,  -- what was executed
                exit_code INTEGER,
                status TEXT  -- running, completed, failed, crashed
            );

            -- Individual function calls within a run
            CREATE TABLE IF NOT EXISTS trace_calls (
                call_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                function_name TEXT NOT NULL,  -- fully qualified: module.class.method
                file_path TEXT,
                line_number INTEGER,
                called_at TEXT NOT NULL,
                returned_at TEXT,
                duration_ms REAL,
                args_json TEXT,  -- serialized arguments
                kwargs_json TEXT,
                return_value_json TEXT,
                exception_type TEXT,
                exception_message TEXT,
                exception_traceback TEXT,
                parent_call_id TEXT,  -- for nested calls
                depth INTEGER DEFAULT 0,
                FOREIGN KEY (run_id) REFERENCES trace_runs(run_id),
                FOREIGN KEY (parent_call_id) REFERENCES trace_calls(call_id)
            );

            CREATE INDEX IF NOT EXISTS idx_trace_calls_run ON trace_calls(run_id);
            CREATE INDEX IF NOT EXISTS idx_trace_calls_function ON trace_calls(function_name);
            CREATE INDEX IF NOT EXISTS idx_trace_calls_exception ON trace_calls(exception_type) WHERE exception_type IS NOT NULL;
        """)
        self.conn.commit()

    def _migrate_to_v3(self):
        """Migration v3: Add file tracking for change detection."""
        self.conn.executescript("""
            -- Track file modification times for change detection
            CREATE TABLE IF NOT EXISTS file_tracking (
                file_path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,           -- os.path.getmtime() value
                size INTEGER,                  -- file size in bytes
                last_ingest_run TEXT,          -- links to ingest_runs.run_id
                ingested_at TEXT NOT NULL      -- ISO timestamp
            );

            -- Track ingest operations (similar to trace_runs but for ingestion)
            CREATE TABLE IF NOT EXISTS ingest_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                paths TEXT,                    -- JSON array of paths ingested
                stats TEXT,                    -- JSON blob with module/function/class counts
                status TEXT                    -- running, completed, failed
            );

            -- Map entities to their source files (for efficient lookups)
            CREATE TABLE IF NOT EXISTS entity_files (
                entity_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                PRIMARY KEY (entity_id, file_path),
                FOREIGN KEY (entity_id) REFERENCES entities(id)
            );

            CREATE INDEX IF NOT EXISTS idx_file_tracking_mtime ON file_tracking(mtime);
            CREATE INDEX IF NOT EXISTS idx_entity_files_path ON entity_files(file_path);
        """)
        self.conn.commit()

    def _migrate_to_v4(self):
        """Migration v4: Add failure tracking for attempted fixes."""
        self.conn.executescript("""
            -- Track failed fix attempts to avoid repeating them
            CREATE TABLE IF NOT EXISTS failure_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                entity_id INTEGER,              -- optional, links to entities table
                entity_name TEXT,               -- optional, name of function/class being fixed
                file_path TEXT,                 -- optional, which file was being worked on
                context TEXT,                   -- what was being attempted (function name, error message, etc.)
                attempted_fix TEXT NOT NULL,   -- description of what was tried
                failure_reason TEXT,            -- why it didn't work (optional)
                related_error TEXT,             -- error message if available
                tags TEXT,                      -- comma-separated tags for categorization
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_failure_logs_entity ON failure_logs(entity_id);
            CREATE INDEX IF NOT EXISTS idx_failure_logs_entity_name ON failure_logs(entity_name);
            CREATE INDEX IF NOT EXISTS idx_failure_logs_file ON failure_logs(file_path);
            CREATE INDEX IF NOT EXISTS idx_failure_logs_timestamp ON failure_logs(timestamp);
        """)
        self.conn.commit()

    def _migrate_to_v5(self):
        """Migration v5: Add entity_name column to failure_logs."""
        # Check if column already exists (for fresh databases)
        cursor = self.conn.execute("PRAGMA table_info(failure_logs)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'entity_name' not in columns:
            self.conn.execute(
                "ALTER TABLE failure_logs ADD COLUMN entity_name TEXT"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_failure_logs_entity_name ON failure_logs(entity_name)"
            )
            self.conn.commit()

    def _migrate_to_v6(self):
        """Migration v6: Add TODO/work item tracking table."""
        self.conn.executescript("""
            -- Track work items (TODOs) for LLM to manage
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,                     -- Short name for display
                prompt TEXT NOT NULL,           -- Detailed instructions (like task prompts)
                context TEXT,                   -- Additional context for the task
                status TEXT DEFAULT 'pending',  -- pending, in_progress, completed, combined
                priority INTEGER DEFAULT 0,     -- Higher = more urgent
                position INTEGER,               -- FIFO order position
                created_at TEXT NOT NULL,
                updated_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                estimated_minutes INTEGER,      -- Optional time estimate
                critical BOOLEAN DEFAULT 0,     -- If true, blocks subsequent work on failure
                tags TEXT,                      -- Comma-separated tags
                combined_into INTEGER,          -- If combined, points to the surviving TODO id
                completion_notes TEXT,          -- Notes added when completing
                entity_name TEXT,               -- Related entity (function/class)
                file_path TEXT,                 -- Related file path
                metadata TEXT,                  -- JSON blob for extra data (result, etc.)
                FOREIGN KEY (combined_into) REFERENCES todos(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
            CREATE INDEX IF NOT EXISTS idx_todos_priority ON todos(priority);
            CREATE INDEX IF NOT EXISTS idx_todos_position ON todos(position);
            CREATE INDEX IF NOT EXISTS idx_todos_created ON todos(created_at);
            CREATE INDEX IF NOT EXISTS idx_todos_entity ON todos(entity_name);
            CREATE INDEX IF NOT EXISTS idx_todos_file ON todos(file_path);
        """)
        self.conn.commit()

    def _migrate_to_v7(self):
        """Migration v7: Add additional TODO columns for enhanced tracking."""
        # Check which columns already exist
        cursor = self.conn.execute("PRAGMA table_info(todos)")
        columns = [row[1] for row in cursor.fetchall()]

        # Add title column (short name for display)
        if 'title' not in columns:
            self.conn.execute("ALTER TABLE todos ADD COLUMN title TEXT")

        # Add position column (FIFO order, allows manual reordering)
        if 'position' not in columns:
            self.conn.execute("ALTER TABLE todos ADD COLUMN position INTEGER")
            # Initialize positions based on id order
            self.conn.execute("""
                UPDATE todos SET position = (
                    SELECT COUNT(*) FROM todos t2 WHERE t2.id <= todos.id
                )
            """)

        # Add estimated_minutes column (optional time estimate)
        if 'estimated_minutes' not in columns:
            self.conn.execute("ALTER TABLE todos ADD COLUMN estimated_minutes INTEGER")

        # Add critical column (blocks subsequent work on failure)
        if 'critical' not in columns:
            self.conn.execute("ALTER TABLE todos ADD COLUMN critical BOOLEAN DEFAULT 0")

        # Add combined_into column (points to surviving TODO if combined)
        if 'combined_into' not in columns:
            self.conn.execute("ALTER TABLE todos ADD COLUMN combined_into INTEGER REFERENCES todos(id) ON DELETE SET NULL")

        # Add completion_notes column (notes added when completing)
        if 'completion_notes' not in columns:
            self.conn.execute("ALTER TABLE todos ADD COLUMN completion_notes TEXT")

        # Create position index if it doesn't exist
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_todos_position ON todos(position)")

        self.conn.commit()

    def _migrate_to_v8(self):
        """Migration v8: Add cross-file references table for DOM validation."""
        self.conn.executescript("""
            -- Track cross-file references (e.g., JS -> HTML DOM elements)
            -- These are relationships where the target may not exist as an entity
            CREATE TABLE IF NOT EXISTS cross_file_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity_id INTEGER NOT NULL,      -- The entity making the reference
                target_name TEXT NOT NULL,              -- The name being referenced (e.g., element ID)
                ref_type TEXT NOT NULL,                 -- 'dom_reference', 'import', etc.
                source_file TEXT,                       -- File containing the reference
                line_number INTEGER,                    -- Line number in source file
                verifiable BOOLEAN DEFAULT 1,           -- Can this be statically verified?
                verification_reason TEXT,               -- If not verifiable, why?
                metadata TEXT,                          -- JSON blob with extra info
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_entity_id) REFERENCES entities(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_cross_file_refs_type ON cross_file_refs(ref_type);
            CREATE INDEX IF NOT EXISTS idx_cross_file_refs_target ON cross_file_refs(target_name);
            CREATE INDEX IF NOT EXISTS idx_cross_file_refs_source ON cross_file_refs(source_entity_id);
        """)
        self.conn.commit()

    def _init_vec_table(self):
        """Initialize sqlite-vec virtual table for embeddings if available."""
        try:
            import sqlite_vec
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)

            self.conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_entities
                USING vec0(embedding float[384])
            """)
            self.conn.commit()
            self._vec_available = True
        except ImportError:
            logging.warning("sqlite-vec not installed; vector search disabled")
        except Exception as e:
            logging.warning(f"Failed to initialize sqlite-vec: {e}")
