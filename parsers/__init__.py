"""Parser abstraction layer for multi-language code analysis."""

from pathlib import Path
from typing import List, Optional

from .base import BaseParser, ParseResult
from .python_parser import PythonParser
from .js_ts_parser import JavaScriptParser, TypeScriptParser
from .cpp_parser import CppParser
from .actionscript3_parser import ActionScript3Parser
from .html_parser import HTMLParser
from .registry import ParserRegistry

__all__ = ['BaseParser', 'ParseResult', 'PythonParser', 'JavaScriptParser', 'TypeScriptParser', 'CppParser', 'ActionScript3Parser', 'HTMLParser', 'ParserRegistry']
