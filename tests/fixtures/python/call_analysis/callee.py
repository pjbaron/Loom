"""Module with helper functions that are called by others."""


def helper():
    """A simple helper function."""
    return "helped"


def process_data(data):
    """Process input data and return result."""
    return f"processed: {data}"


def unused_function():
    """A function that is never called by other code in this package."""
    return "unused"
