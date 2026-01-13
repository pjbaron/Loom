"""Module with functions that call other functions."""

from .callee import helper, process_data


def main():
    """Main entry point that calls helper functions."""
    result = helper()
    data = process_data(result)
    return data


def orchestrator():
    """Orchestrates multiple operations."""
    a = step_one()
    b = step_two(a)
    c = step_three(b)
    return c


def step_one():
    """First step in pipeline."""
    return 1


def step_two(x):
    """Second step in pipeline - calls step_one again."""
    return x + step_one()


def step_three(x):
    """Third step in pipeline."""
    return x * 2


def recursive_func(n):
    """A recursive function that calls itself."""
    if n <= 0:
        return 0
    return n + recursive_func(n - 1)


def mutual_a(n):
    """First function in mutual recursion."""
    if n <= 0:
        return 0
    return mutual_b(n - 1)


def mutual_b(n):
    """Second function in mutual recursion."""
    if n <= 0:
        return 1
    return mutual_a(n - 1)
