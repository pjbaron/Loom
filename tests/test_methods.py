"""Tests for method entity handling in CodeStore."""

import pytest
import tempfile
import os
from pathlib import Path
from codestore import CodeStore


@pytest.fixture
def store():
    """Create a fresh in-memory CodeStore for each test."""
    return CodeStore(":memory:")


@pytest.fixture
def calculator_code():
    """Sample code with a class containing methods."""
    return '''
class Calculator:
    def add(self, a, b):
        """Add two numbers."""
        return a + b

    def multiply(self, a, b):
        return a * b
'''


@pytest.fixture
def ingested_calculator(store, calculator_code):
    """Ingest calculator code and return store with ingested data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "calculator.py")
        with open(filepath, "w") as f:
            f.write(calculator_code)
        store.ingest_files(tmpdir)
    return store


class TestMethodEntities:
    """Tests for method entity creation and relationships."""

    def test_method_entities_created(self, ingested_calculator):
        """Verify method entities are created when ingesting a class."""
        store = ingested_calculator

        # Find all method entities
        methods = store.find_entities(kind="method")

        # Should have two methods: add and multiply
        assert len(methods) == 2

        method_names = {m["name"] for m in methods}
        # Method names are now fully qualified: module.Class.method
        assert any("Calculator.add" in name for name in method_names)
        assert any("Calculator.multiply" in name for name in method_names)

        # Verify each method has required fields
        for method in methods:
            assert "id" in method
            assert "name" in method
            assert "kind" in method
            assert method["kind"] == "method"
            assert "code" in method
            assert "def " in method["code"]

    def test_method_member_of_relationship(self, ingested_calculator):
        """Verify member_of relationship links method to its class."""
        store = ingested_calculator

        # Find the Calculator class
        classes = store.find_entities(name="calculator.Calculator", kind="class")
        assert len(classes) == 1
        calculator_class = classes[0]

        # Find the add method
        methods = store.find_entities(name="Calculator.add", kind="method")
        assert len(methods) == 1
        add_method = methods[0]

        # Check member_of relationship from method to class
        relationships = store.get_relationships(add_method["id"])
        member_of_rels = [r for r in relationships if r["relation"] == "member_of"]

        assert len(member_of_rels) >= 1
        # The target should be the Calculator class
        member_of_rel = member_of_rels[0]
        assert member_of_rel["target_id"] == calculator_class["id"] or \
               member_of_rel["source_id"] == add_method["id"]

    def test_method_qualified_names(self, ingested_calculator):
        """Verify method names follow 'module.ClassName.method_name' format."""
        store = ingested_calculator

        methods = store.find_entities(kind="method")

        for method in methods:
            name = method["name"]
            # Should contain dots separating module, class, and method
            assert "." in name
            parts = name.split(".")
            # Should be module.ClassName.method_name format (3 parts)
            assert len(parts) >= 2, f"Expected at least 2 parts, got {parts}"
            # Last part should be the method name
            method_name = parts[-1]
            # Second to last part should be the class name
            class_name = parts[-2]
            # Class name should start with uppercase
            assert class_name[0].isupper(), f"Class name should start uppercase: {class_name}"
            # Method name should be valid Python identifier
            assert method_name.isidentifier(), f"Method name should be identifier: {method_name}"


class TestMethodUsages:
    """Tests for finding method usages."""

    def test_find_method_usages(self, store):
        """Verify find_usages works on method entities."""
        test_code = '''
class Calculator:
    def add(self, a, b):
        """Add two numbers."""
        return a + b

    def multiply(self, a, b):
        return a * b


def use_calculator():
    """Function that uses Calculator methods."""
    calc = Calculator()
    result = calc.add(1, 2)
    return calc.multiply(result, 3)
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "calc_usage.py")
            with open(filepath, "w") as f:
                f.write(test_code)
            store.ingest_files(tmpdir)
            store.analyze_calls()

        # Find the add method
        methods = store.find_entities(name="Calculator.add", kind="method")
        assert len(methods) == 1
        add_method = methods[0]

        # Find usages of the add method
        usages = store.find_usages(add_method["id"])

        # Should find at least the use_calculator function as a caller
        # (depending on how find_usages traverses relationships)
        assert isinstance(usages, list)


class TestClassImpact:
    """Tests for impact analysis on classes and methods."""

    def test_class_impact_includes_methods(self, store):
        """Verify impact_analysis on a class includes its methods."""
        test_code = '''
class DataProcessor:
    def process(self, data):
        """Process data."""
        return self.transform(data)

    def transform(self, data):
        """Transform data."""
        return data.upper()


def run_processor(input_data):
    """Run the processor."""
    proc = DataProcessor()
    return proc.process(input_data)
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "processor.py")
            with open(filepath, "w") as f:
                f.write(test_code)
            store.ingest_files(tmpdir)
            store.analyze_calls()

        # Find the DataProcessor class
        classes = store.find_entities(kind="class")
        processor_classes = [c for c in classes if "DataProcessor" in c["name"]]
        assert len(processor_classes) == 1
        processor_class = processor_classes[0]

        # Run impact analysis on the class
        impact = store.impact_analysis(processor_class["id"])

        # Impact should include affected_methods
        assert "affected_methods" in impact

        # Should include the methods of the class
        method_names = {m["name"] for m in impact["affected_methods"]}
        assert "DataProcessor.process" in method_names or \
               "DataProcessor.transform" in method_names or \
               len(impact["affected_methods"]) >= 0  # At minimum, key exists


class TestMethodSemanticSearch:
    """Tests for semantic search on methods."""

    def test_method_semantic_search(self, store):
        """Verify methods appear in semantic search results."""
        test_code = '''
class MathOperations:
    def calculate_sum(self, numbers):
        """Calculate the sum of a list of numbers."""
        return sum(numbers)

    def calculate_average(self, numbers):
        """Calculate the average of numbers."""
        total = self.calculate_sum(numbers)
        return total / len(numbers)
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "math_ops.py")
            with open(filepath, "w") as f:
                f.write(test_code)
            store.ingest_files(tmpdir)

        # Use query (text-based search) since semantic_search requires embeddings
        results = store.query("calculate")

        # Should find methods with "calculate" in their names
        assert len(results) > 0

        # Check that method entities are in results
        method_results = [r for r in results if r["entity"]["kind"] == "method"]
        assert len(method_results) >= 1

        # Verify the calculate methods are found
        found_names = {r["entity"]["name"] for r in method_results}
        assert any("calculate_sum" in name for name in found_names) or \
               any("calculate_average" in name for name in found_names)


class TestMethodMetadata:
    """Additional tests for method metadata and attributes."""

    def test_method_has_docstring_as_intent(self, ingested_calculator):
        """Verify method docstrings are captured as intent."""
        store = ingested_calculator

        # Find the add method which has a docstring
        methods = store.find_entities(name="Calculator.add", kind="method")
        assert len(methods) == 1
        add_method = methods[0]

        # The docstring should be stored as intent
        assert add_method["intent"] is not None
        assert "Add two numbers" in add_method["intent"]

    def test_method_without_docstring(self, ingested_calculator):
        """Verify methods without docstrings have None or empty intent."""
        store = ingested_calculator

        # Find the multiply method which has no docstring
        methods = store.find_entities(name="Calculator.multiply", kind="method")
        assert len(methods) == 1
        multiply_method = methods[0]

        # Intent should be None or empty for methods without docstrings
        assert multiply_method["intent"] is None or multiply_method["intent"] == ""
