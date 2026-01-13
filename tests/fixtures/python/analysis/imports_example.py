"""Test fixture for import analysis."""

from . import importable_module
from .importable_module import helper, Widget

import os
from pathlib import Path


def use_imports():
    """Uses the imported items."""
    helper()
    w = Widget()
    return w.activate()
