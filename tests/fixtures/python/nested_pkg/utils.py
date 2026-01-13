"""Utility functions for the nested package."""


def helper_function(x: int) -> int:
    """Double the input value."""
    return x * 2


def format_string(template: str, **kwargs) -> str:
    """Format a string with the given keyword arguments."""
    return template.format(**kwargs)
