"""Module that imports from other modules in the package."""

from .core import CoreClass
from .utils import utility_func, format_output
from . import utils


def use_core():
    """Use the CoreClass."""
    obj = CoreClass()
    return obj.do_work()


def use_utility(x):
    """Use the utility function."""
    result = utility_func(x)
    return format_output(result)


def use_module_import(x):
    """Use the module-level import."""
    return utils.utility_func(x)
