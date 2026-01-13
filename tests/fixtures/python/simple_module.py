"""A simple module for testing code ingestion."""


def greet(name: str) -> str:
    """Return a greeting message for the given name."""
    return f"Hello, {name}!"


def add_numbers(a: int, b: int) -> int:
    """Add two numbers and return the result."""
    return a + b


class Calculator:
    """A simple calculator class for basic arithmetic."""

    def __init__(self, initial_value: float = 0):
        """Initialize the calculator with an optional starting value."""
        self.value = initial_value

    def add(self, x: float) -> float:
        """Add x to the current value."""
        self.value += x
        return self.value

    def multiply(self, x: float) -> float:
        """Multiply current value by x."""
        self.value *= x
        return self.value


async def fetch_data(url: str) -> dict:
    """Asynchronously fetch data from a URL."""
    return {"url": url, "data": "mock"}
