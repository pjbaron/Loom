"""Test fixture for call analysis with cycles."""


def foo():
    """Calls bar, creating a chain."""
    bar()


def bar():
    """Calls baz, continuing the chain."""
    baz()


def baz():
    """Calls foo, completing the cycle."""
    foo()


def standalone():
    """Does not call anyone."""
    pass
