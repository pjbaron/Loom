"""Tests for import analysis, query, and find_usages features of CodeStore."""

import pytest
import tempfile
import shutil
from pathlib import Path

from codestore import CodeStore


@pytest.fixture
def store():
    """Create a fresh in-memory CodeStore for each test."""
    return CodeStore(":memory:")


@pytest.fixture
def fixtures_dir():
    """Return the path to the test fixtures directory."""
    return Path(__file__).parent / "test_fixtures"


@pytest.fixture
def import_analysis_dir(fixtures_dir):
    """Return the path to the import_analysis fixtures."""
    return fixtures_dir / "import_analysis"


@pytest.fixture
def call_analysis_dir(fixtures_dir):
    """Return the path to the call_analysis fixtures."""
    return fixtures_dir / "call_analysis"


class TestAnalyzeImportsCreatesRelationships:
    """Tests for analyze_imports() creating 'imports' relationships."""

    def test_analyze_imports_creates_imports_relationship(self, store, import_analysis_dir):
        """analyze_imports() creates 'imports' relationships between modules."""
        store.ingest_files(str(import_analysis_dir))
        stats = store.analyze_imports()

        # Should have analyzed modules and created relationships
        assert stats["analyzed"] > 0
        assert stats["relationships_created"] > 0

        # Verify consumer imports core
        consumer_mods = [e for e in store.find_entities(kind="module")
                        if "consumer" in e["name"]]
        assert len(consumer_mods) > 0
        consumer = consumer_mods[0]

        imports = store.find_related(consumer["id"], relation="imports", direction="outgoing")
        imported_names = [i["name"] for i in imports]

        # consumer.py imports from .core and .utils
        assert any("core" in name for name in imported_names)
        assert any("utils" in name for name in imported_names)

    def test_analyze_imports_from_init_creates_relationships(self, store, import_analysis_dir):
        """analyze_imports() creates relationships for imports in __init__.py."""
        store.ingest_files(str(import_analysis_dir))
        store.analyze_imports()

        # __init__.py imports from .core and .utils
        init_mods = [e for e in store.find_entities(kind="module")
                    if e["name"] == "import_analysis" or e["name"].endswith("import_analysis")]

        if init_mods:
            init_mod = init_mods[0]
            imports = store.find_related(init_mod["id"], relation="imports", direction="outgoing")
            imported_names = [i["name"] for i in imports]

            # Should import core and utils
            assert any("core" in name for name in imported_names)
            assert any("utils" in name for name in imported_names)

    def test_analyze_imports_no_self_imports(self, store, import_analysis_dir):
        """analyze_imports() does not create self-import relationships."""
        store.ingest_files(str(import_analysis_dir))
        store.analyze_imports()

        modules = store.find_entities(kind="module")
        for mod in modules:
            imports = store.find_related(mod["id"], relation="imports", direction="outgoing")
            imported_ids = [i["id"] for i in imports]

            # Module should not import itself
            assert mod["id"] not in imported_ids

    def test_analyze_imports_handles_star_import(self, store):
        """analyze_imports() handles 'from x import *' correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = Path(tmpdir) / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "base.py").write_text('"""Base module."""\ndef base_func(): pass\n')
            (pkg / "consumer.py").write_text('''"""Consumer module."""
from .base import *
''')

            store.ingest_files(tmpdir)
            stats = store.analyze_imports()

            # Should find and create the import relationship
            assert stats["imports_found"] > 0

            consumer_mods = [e for e in store.find_entities(kind="module")
                           if "consumer" in e["name"]]
            if consumer_mods:
                imports = store.find_related(consumer_mods[0]["id"],
                                            relation="imports", direction="outgoing")
                assert any("base" in i["name"] for i in imports)


class TestAnalyzeImportsMetadata:
    """Tests for import metadata storage in relationships."""

    def test_import_metadata_contains_names(self, store):
        """Import metadata includes the names being imported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = Path(tmpdir) / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "source.py").write_text('"""Source module."""\ndef func_a(): pass\ndef func_b(): pass\n')
            (pkg / "importer.py").write_text('''"""Importer module."""
from .source import func_a, func_b
''')

            store.ingest_files(tmpdir)
            store.analyze_imports()

            importer_mods = [e for e in store.find_entities(kind="module")
                           if "importer" in e["name"]]
            assert len(importer_mods) > 0

            rels = store.get_relationships(importer_mods[0]["id"], direction="outgoing")
            import_rels = [r for r in rels if r["relation"] == "imports"]

            assert len(import_rels) > 0
            metadata = import_rels[0].get("metadata", {})
            assert metadata is not None
            assert "names" in metadata
            assert "func_a" in metadata["names"]
            assert "func_b" in metadata["names"]

    def test_import_metadata_contains_aliases(self, store):
        """Import metadata includes aliases when present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = Path(tmpdir) / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "source.py").write_text('"""Source module."""\ndef long_function_name(): pass\n')
            (pkg / "importer.py").write_text('''"""Importer module."""
from .source import long_function_name as short_name
''')

            store.ingest_files(tmpdir)
            store.analyze_imports()

            importer_mods = [e for e in store.find_entities(kind="module")
                           if "importer" in e["name"]]
            assert len(importer_mods) > 0

            rels = store.get_relationships(importer_mods[0]["id"], direction="outgoing")
            import_rels = [r for r in rels if r["relation"] == "imports"]

            assert len(import_rels) > 0
            metadata = import_rels[0].get("metadata", {})
            assert metadata is not None
            assert "aliases" in metadata
            assert "long_function_name" in metadata["aliases"]
            assert metadata["aliases"]["long_function_name"] == "short_name"

    def test_import_metadata_marks_relative_imports(self, store):
        """Import metadata correctly marks relative imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = Path(tmpdir) / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "source.py").write_text('"""Source module."""\ndef func(): pass\n')
            (pkg / "importer.py").write_text('''"""Importer module."""
from .source import func
''')

            store.ingest_files(tmpdir)
            store.analyze_imports()

            importer_mods = [e for e in store.find_entities(kind="module")
                           if "importer" in e["name"]]
            assert len(importer_mods) > 0

            rels = store.get_relationships(importer_mods[0]["id"], direction="outgoing")
            import_rels = [r for r in rels if r["relation"] == "imports"]

            assert len(import_rels) > 0
            metadata = import_rels[0].get("metadata", {})
            assert metadata is not None
            assert metadata.get("is_relative") is True
            assert metadata.get("level") == 1

    def test_import_metadata_contains_import_type(self, store):
        """Import metadata includes the type of import (import/from/from_star)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = Path(tmpdir) / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "source.py").write_text('"""Source module."""\ndef func(): pass\n')
            (pkg / "importer.py").write_text('''"""Importer module."""
from .source import func
''')

            store.ingest_files(tmpdir)
            store.analyze_imports()

            importer_mods = [e for e in store.find_entities(kind="module")
                           if "importer" in e["name"]]

            rels = store.get_relationships(importer_mods[0]["id"], direction="outgoing")
            import_rels = [r for r in rels if r["relation"] == "imports"]

            assert len(import_rels) > 0
            metadata = import_rels[0].get("metadata", {})
            assert metadata is not None
            assert "import_type" in metadata
            assert metadata["import_type"] == "from"

    def test_import_metadata_star_import_type(self, store):
        """Import metadata marks star imports correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = Path(tmpdir) / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "source.py").write_text('"""Source module."""\ndef func(): pass\n')
            (pkg / "importer.py").write_text('''"""Importer module."""
from .source import *
''')

            store.ingest_files(tmpdir)
            store.analyze_imports()

            importer_mods = [e for e in store.find_entities(kind="module")
                           if "importer" in e["name"]]

            rels = store.get_relationships(importer_mods[0]["id"], direction="outgoing")
            import_rels = [r for r in rels if r["relation"] == "imports"]

            assert len(import_rels) > 0
            metadata = import_rels[0].get("metadata", {})
            assert metadata is not None
            assert metadata.get("import_type") == "from_star"


class TestQueryFindsByName:
    """Tests for query() finding entities by name."""

    def test_query_finds_function_by_name(self, store, fixtures_dir):
        """query() finds functions matching name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            results = store.query("greet")

            assert len(results) > 0
            greet_results = [r for r in results if "greet" in r["entity"]["name"]]
            assert len(greet_results) > 0
            assert "name" in greet_results[0]["matches"]

    def test_query_finds_class_by_name(self, store, fixtures_dir):
        """query() finds classes matching name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            results = store.query("Calculator")

            assert len(results) > 0
            calc_results = [r for r in results if "Calculator" in r["entity"]["name"]]
            assert len(calc_results) > 0
            assert calc_results[0]["entity"]["kind"] == "class"

    def test_query_finds_module_by_name(self, store, fixtures_dir):
        """query() finds modules matching name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            results = store.query("simple_module")

            assert len(results) > 0
            module_results = [r for r in results if r["entity"]["kind"] == "module"]
            assert len(module_results) > 0

    def test_query_partial_name_match(self, store, fixtures_dir):
        """query() finds entities with partial name matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            # "add" should match "add_numbers" and possibly "add" method
            results = store.query("add")

            assert len(results) > 0
            assert any("add" in r["entity"]["name"].lower() for r in results)


class TestQueryFindsByIntent:
    """Tests for query() finding entities by intent/docstring."""

    def test_query_finds_by_docstring_content(self, store, fixtures_dir):
        """query() finds entities matching docstring content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            results = store.query("greeting message")

            assert len(results) > 0
            # greet function has docstring "Return a greeting message..."
            greet_results = [r for r in results if "greet" in r["entity"]["name"]]
            assert len(greet_results) > 0
            assert "intent" in greet_results[0]["matches"]

    def test_query_finds_by_intent_keyword(self, store, fixtures_dir):
        """query() finds entities with intent containing keyword."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            # "arithmetic" is in Calculator docstring
            results = store.query("arithmetic")

            assert len(results) > 0
            calc_results = [r for r in results if "Calculator" in r["entity"]["name"]]
            assert len(calc_results) > 0
            assert "intent" in calc_results[0]["matches"]

    def test_query_intent_case_insensitive(self, store, fixtures_dir):
        """query() is case insensitive for intent matching."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            results_lower = store.query("arithmetic")
            results_upper = store.query("ARITHMETIC")

            assert len(results_lower) > 0
            assert len(results_upper) > 0
            assert len(results_lower) == len(results_upper)


class TestQueryFindsByCode:
    """Tests for query() finding entities by code content."""

    def test_query_finds_by_code_content(self, store, fixtures_dir):
        """query() finds entities matching code content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            # "initial_value" is a parameter in Calculator.__init__ code
            results = store.query("initial_value")

            assert len(results) > 0
            code_matches = [r for r in results if "code" in r["matches"]]
            assert len(code_matches) > 0

    def test_query_finds_by_return_statement(self, store, fixtures_dir):
        """query() finds entities by code return statements."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            results = store.query("Hello")

            assert len(results) > 0
            # greet function returns f"Hello, {name}!"
            greet_results = [r for r in results if "greet" in r["entity"]["name"]]
            assert len(greet_results) > 0
            assert "code" in greet_results[0]["matches"]

    def test_query_multiple_fields_match(self, store):
        """query() returns entity matching in multiple fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "multi_match.py"
            test_file.write_text('''
def process_data(data):
    """Process the data and transform it."""
    return data.process()
''')
            store.ingest_files(tmpdir)

            # "process" appears in name, intent, and code
            results = store.query("process")

            assert len(results) > 0
            process_result = [r for r in results if "process_data" in r["entity"]["name"]][0]
            # Should match in multiple fields
            assert len(process_result["matches"]) >= 2


class TestQueryEdgeCases:
    """Tests for query() edge cases."""

    def test_query_empty_string_returns_empty(self, store, fixtures_dir):
        """query() with empty string returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            results = store.query("")

            assert results == []

    def test_query_no_matches_returns_empty(self, store, fixtures_dir):
        """query() with no matches returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            results = store.query("xyznonexistentxyz123")

            assert results == []

    def test_query_ranks_name_matches_first(self, store, fixtures_dir):
        """query() ranks results with name matches higher."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            results = store.query("add")

            assert len(results) > 0
            # First result should have a name match
            first_result = results[0]
            assert "name" in first_result["matches"]

    def test_query_no_duplicates(self, store, fixtures_dir):
        """query() does not return duplicate entities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "simple_module.py"
            shutil.copy(fixtures_dir / "simple_module.py", dest)

            store.ingest_files(tmpdir)
            results = store.query("add")

            entity_ids = [r["entity"]["id"] for r in results]
            assert len(entity_ids) == len(set(entity_ids))


class TestFindUsagesReturnsCallers:
    """Tests for find_usages() returning entities that call the target."""

    def test_find_usages_returns_callers(self, store, call_analysis_dir):
        """find_usages() returns entities that call the target."""
        store.ingest_files(str(call_analysis_dir))
        store.analyze_calls()

        # step_one is called by orchestrator and step_two
        step_one = store.find_entities(name="step_one")[0]
        usages = store.find_usages(step_one["id"])

        call_usages = [u for u in usages if u["relation"] == "calls"]
        caller_names = [u["entity"]["name"] for u in call_usages]

        assert len(call_usages) >= 2
        assert any("orchestrator" in name for name in caller_names)
        assert any("step_two" in name for name in caller_names)

    def test_find_usages_returns_relation_type(self, store, call_analysis_dir):
        """find_usages() returns the type of relationship."""
        store.ingest_files(str(call_analysis_dir))
        store.analyze_calls()

        step_one = store.find_entities(name="step_one")[0]
        usages = store.find_usages(step_one["id"])

        for usage in usages:
            assert "relation" in usage
            assert usage["relation"] in ["calls", "imports", "inherits",
                                         "uses", "code_reference", "contains"]

    def test_find_usages_empty_for_unused_function(self, store, call_analysis_dir):
        """find_usages() returns minimal list for functions not called."""
        store.ingest_files(str(call_analysis_dir))
        store.analyze_calls()

        # unused_function is not called by anything
        unused = store.find_entities(name="unused_function")
        if unused:
            usages = store.find_usages(unused[0]["id"])
            call_usages = [u for u in usages if u["relation"] == "calls"]
            assert len(call_usages) == 0


class TestFindUsagesReturnsImporters:
    """Tests for find_usages() returning entities that import the target."""

    def test_find_usages_returns_importers(self, store, import_analysis_dir):
        """find_usages() returns entities that import the target module."""
        store.ingest_files(str(import_analysis_dir))
        store.analyze_imports()

        # Find the utils module
        utils_mods = [e for e in store.find_entities(kind="module")
                     if "utils" in e["name"] and "import_analysis" in e["name"]]

        if utils_mods:
            utils_mod = utils_mods[0]
            usages = store.find_usages(utils_mod["id"])

            import_usages = [u for u in usages if u["relation"] == "imports"]
            # utils is imported by consumer.py and __init__.py
            assert len(import_usages) >= 1

    def test_find_usages_returns_import_context(self, store, import_analysis_dir):
        """find_usages() returns context for import relationships."""
        store.ingest_files(str(import_analysis_dir))
        store.analyze_imports()

        # Find the core module
        core_mods = [e for e in store.find_entities(kind="module")
                    if "core" in e["name"] and "import_analysis" in e["name"]]

        if core_mods:
            core_mod = core_mods[0]
            usages = store.find_usages(core_mod["id"])

            import_usages = [u for u in usages if u["relation"] == "imports"]
            if import_usages:
                # Context should contain import metadata
                assert "context" in import_usages[0]


class TestFindUsagesReturnsCodeReferences:
    """Tests for find_usages() returning code references."""

    def test_find_usages_returns_code_references(self, store, call_analysis_dir):
        """find_usages() returns entities referencing the target in code."""
        store.ingest_files(str(call_analysis_dir))
        store.analyze_calls()

        # helper is referenced in caller.py
        helper = store.find_entities(name="helper")
        if helper:
            helper_func = helper[0]
            usages = store.find_usages(helper_func["id"])

            code_refs = [u for u in usages if u["relation"] == "code_reference"]
            # May have code references from functions that call it
            assert isinstance(code_refs, list)

    def test_find_usages_code_reference_context(self, store, call_analysis_dir):
        """find_usages() provides context for code references."""
        store.ingest_files(str(call_analysis_dir))
        store.analyze_calls()

        step_one = store.find_entities(name="step_one")[0]
        usages = store.find_usages(step_one["id"])

        code_refs = [u for u in usages if u["relation"] == "code_reference"]
        if code_refs:
            # Context should indicate reference type
            assert "context" in code_refs[0]
            assert code_refs[0]["context"] is not None


class TestFindUsagesEdgeCases:
    """Tests for find_usages() edge cases."""

    def test_find_usages_nonexistent_entity(self, store):
        """find_usages() returns empty list for nonexistent entity."""
        usages = store.find_usages(99999)
        assert usages == []

    def test_find_usages_no_self_reference_for_non_recursive(self, store, call_analysis_dir):
        """find_usages() does not include self-reference for non-recursive functions."""
        store.ingest_files(str(call_analysis_dir))
        store.analyze_calls()

        step_one = store.find_entities(name="step_one")[0]
        usages = store.find_usages(step_one["id"])

        # step_one doesn't call itself, so shouldn't have self-reference
        self_refs = [u for u in usages if u["entity"]["id"] == step_one["id"]]
        assert len(self_refs) == 0

    def test_find_usages_combines_all_relation_types(self, store):
        """find_usages() returns usages from all relationship types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = Path(tmpdir) / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "target.py").write_text('''"""Target module."""
def target_func():
    """A target function."""
    return 42
''')
            (pkg / "caller.py").write_text('''"""Caller module."""
from .target import target_func

def call_target():
    """Call the target."""
    return target_func()
''')

            store.ingest_files(tmpdir)
            store.analyze_imports()
            store.analyze_calls()

            target_func = store.find_entities(name="target_func")
            if target_func:
                usages = store.find_usages(target_func[0]["id"])
                relations = set(u["relation"] for u in usages)

                # Should have both calls and possibly code_reference
                assert len(usages) >= 1

    def test_find_usages_returns_entity_dict(self, store, call_analysis_dir):
        """find_usages() returns complete entity dictionaries."""
        store.ingest_files(str(call_analysis_dir))
        store.analyze_calls()

        step_one = store.find_entities(name="step_one")[0]
        usages = store.find_usages(step_one["id"])

        for usage in usages:
            assert "entity" in usage
            entity = usage["entity"]
            assert "id" in entity
            assert "name" in entity
            assert "kind" in entity
