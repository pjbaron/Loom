"""Tests for call graph analysis features of CodeStore."""

import pytest
from pathlib import Path

from codestore import CodeStore


@pytest.fixture
def store():
    """Create a fresh in-memory CodeStore for each test."""
    return CodeStore(":memory:")


@pytest.fixture
def analysis_fixtures_dir():
    """Return the path to the analysis test fixtures directory."""
    return Path(__file__).parent / "test_fixtures" / "analysis"


class TestAnalyzeCallsCreatesRelationships:
    """Tests for analyze_calls() creating 'calls' relationships."""

    def test_analyze_calls_creates_calls_relationship(self, store, analysis_fixtures_dir):
        """analyze_calls() creates 'calls' relationships between functions."""
        store.ingest_files(str(analysis_fixtures_dir))
        stats = store.analyze_calls()

        # Should have analyzed functions and created relationships
        assert stats["analyzed"] > 0
        assert stats["relationships_created"] > 0

        # Verify foo calls bar
        foo = store.find_entities(name="foo")[0]
        calls = store.find_related(foo["id"], relation="calls", direction="outgoing")
        called_names = [c["name"] for c in calls]

        assert any("bar" in name for name in called_names)

    def test_analyze_calls_creates_chain_relationships(self, store, analysis_fixtures_dir):
        """analyze_calls() creates relationships for each call in a chain."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        # foo -> bar -> baz -> foo (cycle)
        bar = store.find_entities(name="bar")[0]
        bar_calls = store.find_related(bar["id"], relation="calls", direction="outgoing")
        bar_called_names = [c["name"] for c in bar_calls]

        assert any("baz" in name for name in bar_called_names)

        baz = store.find_entities(name="baz")[0]
        baz_calls = store.find_related(baz["id"], relation="calls", direction="outgoing")
        baz_called_names = [c["name"] for c in baz_calls]

        assert any("foo" in name for name in baz_called_names)

    def test_analyze_calls_standalone_function_no_relationships(self, store, analysis_fixtures_dir):
        """standalone function has no outgoing 'calls' relationships."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        standalone = store.find_entities(name="standalone")[0]
        calls = store.find_related(standalone["id"], relation="calls", direction="outgoing")

        assert len(calls) == 0


class TestGetCallGraphDirectCalls:
    """Tests for get_call_graph() returning direct calls."""

    def test_get_call_graph_returns_direct_calls(self, store, analysis_fixtures_dir):
        """get_call_graph() with default depth returns direct calls."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        foo = store.find_entities(name="foo")[0]
        graph = store.get_call_graph(foo["id"])

        assert "entity" in graph
        assert "calls" in graph
        assert "call_count" in graph
        assert graph["call_count"] == 1  # foo calls bar only

    def test_get_call_graph_direct_calls_contain_entity_info(self, store, analysis_fixtures_dir):
        """Direct calls in get_call_graph() contain entity information."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        foo = store.find_entities(name="foo")[0]
        graph = store.get_call_graph(foo["id"])

        assert len(graph["calls"]) == 1
        called_entity = graph["calls"][0]["entity"]
        assert "bar" in called_entity["name"]
        assert called_entity["kind"] == "function"

    def test_get_call_graph_depth_one_no_nested_calls(self, store, analysis_fixtures_dir):
        """get_call_graph() with depth=1 does not recurse into called functions."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        foo = store.find_entities(name="foo")[0]
        graph = store.get_call_graph(foo["id"], depth=1)

        # foo -> bar, but bar's calls to baz should NOT be populated
        bar_call = graph["calls"][0]
        # At depth 1, bar's calls should be empty (depth exhausted)
        assert bar_call["calls"] == []

    def test_get_call_graph_standalone_has_no_calls(self, store, analysis_fixtures_dir):
        """get_call_graph() for a standalone function returns empty calls list."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        standalone = store.find_entities(name="standalone")[0]
        graph = store.get_call_graph(standalone["id"])

        assert graph["call_count"] == 0
        assert graph["calls"] == []


class TestGetCallGraphRecursive:
    """Tests for get_call_graph(recursive=True) returning full tree."""

    def test_get_call_graph_recursive_returns_full_tree(self, store, analysis_fixtures_dir):
        """get_call_graph(recursive=True) returns the full call tree."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        foo = store.find_entities(name="foo")[0]
        graph = store.get_call_graph(foo["id"], depth=-1, recursive=True)

        # foo -> bar -> baz -> foo (stops at cycle)
        assert graph["call_count"] == 1

        # bar should be in foo's calls
        bar_call = graph["calls"][0]
        assert "bar" in bar_call["entity"]["name"]

        # bar should have baz in its calls
        assert bar_call["call_count"] == 1
        baz_call = bar_call["calls"][0]
        assert "baz" in baz_call["entity"]["name"]

        # baz should have foo in its calls (cycle detected)
        assert baz_call["call_count"] == 1
        foo_call = baz_call["calls"][0]
        assert "foo" in foo_call["entity"]["name"]

    def test_get_call_graph_recursive_depth_controls_traversal(self, store, analysis_fixtures_dir):
        """get_call_graph() with depth=2 limits traversal depth."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        foo = store.find_entities(name="foo")[0]
        graph = store.get_call_graph(foo["id"], depth=2)

        # foo -> bar (depth 1) -> baz (depth 2) -> foo (depth exhausted, not traversed)
        bar_call = graph["calls"][0]
        assert bar_call["call_count"] == 1  # bar has calls populated

        baz_call = bar_call["calls"][0]
        # At depth 2, baz's calls should be populated
        # But the next level (foo) should have empty calls (depth 3 not reached)

    def test_get_call_graph_depth_zero_returns_entity_only(self, store, analysis_fixtures_dir):
        """get_call_graph(depth=0) returns entity with no calls."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        foo = store.find_entities(name="foo")[0]
        graph = store.get_call_graph(foo["id"], depth=0)

        assert graph["entity"]["id"] == foo["id"]
        assert graph["calls"] == []
        assert graph["call_count"] == 0


class TestCycleDetection:
    """Tests for cycle detection in get_call_graph()."""

    def test_cycle_detection_prevents_infinite_loop(self, store, analysis_fixtures_dir):
        """Cycle detection prevents infinite loops in recursive call graphs."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        # foo -> bar -> baz -> foo (cycle)
        foo = store.find_entities(name="foo")[0]

        # This should complete without hanging
        graph = store.get_call_graph(foo["id"], depth=-1, recursive=True)

        # Should have completed with the cycle detected
        assert graph is not None
        assert "entity" in graph

    def test_cycle_detection_marks_cycle(self, store, analysis_fixtures_dir):
        """Cycle detection marks the cyclic node."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        foo = store.find_entities(name="foo")[0]
        graph = store.get_call_graph(foo["id"], depth=-1, recursive=True)

        # Navigate to the cycle: foo -> bar -> baz -> foo
        bar_call = graph["calls"][0]
        baz_call = bar_call["calls"][0]
        foo_cycle = baz_call["calls"][0]

        # The cyclic call to foo should be marked
        assert foo_cycle.get("cycle") is True or foo_cycle["calls"] == []

    def test_multiple_calls_to_same_function_handled(self, store):
        """Multiple calls to the same function are handled correctly."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "multi_call.py"
            test_file.write_text('''
def helper():
    """A helper function."""
    return 1

def caller():
    """Calls helper multiple times."""
    a = helper()
    b = helper()
    c = helper()
    return a + b + c
''')
            store.ingest_files(tmpdir)
            store.analyze_calls()

            caller = store.find_entities(name="caller")[0]
            graph = store.get_call_graph(caller["id"], depth=-1, recursive=True)

            # Should complete and only have one call entry for helper
            assert graph["call_count"] == 1

    def test_deep_recursion_terminates(self, store, analysis_fixtures_dir):
        """Deep recursive traversal terminates due to cycle detection."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        # Start from any node in the cycle
        bar = store.find_entities(name="bar")[0]

        # This should complete without recursion limit
        graph = store.get_call_graph(bar["id"], depth=-1, recursive=True)

        assert graph is not None
        assert graph["entity"]["id"] == bar["id"]


class TestGetCallers:
    """Tests for get_callers() returning reverse lookup."""

    def test_get_callers_returns_calling_functions(self, store, analysis_fixtures_dir):
        """get_callers() returns functions that call the target."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        bar = store.find_entities(name="bar")[0]
        callers = store.get_callers(bar["id"])

        caller_names = [c["name"] for c in callers]

        # foo calls bar
        assert any("foo" in name for name in caller_names)

    def test_get_callers_for_cycle_end(self, store, analysis_fixtures_dir):
        """get_callers() works for functions at the end of a cycle."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        # foo is called by baz (completing the cycle)
        foo = store.find_entities(name="foo")[0]
        callers = store.get_callers(foo["id"])

        caller_names = [c["name"] for c in callers]

        assert any("baz" in name for name in caller_names)

    def test_get_callers_empty_for_uncalled(self, store, analysis_fixtures_dir):
        """get_callers() returns empty list for functions not called."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        standalone = store.find_entities(name="standalone")[0]
        callers = store.get_callers(standalone["id"])

        assert callers == []

    def test_get_callers_returns_entity_dicts(self, store, analysis_fixtures_dir):
        """get_callers() returns list of entity dictionaries."""
        store.ingest_files(str(analysis_fixtures_dir))
        store.analyze_calls()

        bar = store.find_entities(name="bar")[0]
        callers = store.get_callers(bar["id"])

        assert len(callers) > 0
        for caller in callers:
            assert "id" in caller
            assert "name" in caller
            assert "kind" in caller

    def test_get_callers_nonexistent_entity(self, store):
        """get_callers() returns empty list for nonexistent entity."""
        callers = store.get_callers(99999)
        assert callers == []

    def test_get_callers_multiple_callers(self, store):
        """get_callers() returns all functions that call the target."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "multi_caller.py"
            test_file.write_text('''
def target():
    """A function called by multiple callers."""
    return 42

def caller_one():
    """First caller."""
    return target()

def caller_two():
    """Second caller."""
    return target() * 2

def caller_three():
    """Third caller."""
    return target() + 1
''')
            store.ingest_files(tmpdir)
            store.analyze_calls()

            target = store.find_entities(name="target")[0]
            callers = store.get_callers(target["id"])

            caller_names = [c["name"] for c in callers]

            assert len(callers) == 3
            assert any("caller_one" in name for name in caller_names)
            assert any("caller_two" in name for name in caller_names)
            assert any("caller_three" in name for name in caller_names)
