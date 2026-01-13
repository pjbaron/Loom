"""Parser registry for managing language-specific parsers."""

from pathlib import Path
from typing import List, Optional

from .base import BaseParser


class ParserRegistry:
    """Registry for language-specific parsers."""

    def __init__(self):
        self._parsers: List[BaseParser] = []

    def register(self, parser: BaseParser) -> None:
        """Register a parser instance."""
        self._parsers.append(parser)

    def get_parser(self, file_path: Path) -> Optional[BaseParser]:
        """Get a parser that can handle the given file."""
        for parser in self._parsers:
            if parser.can_parse(file_path):
                return parser
        return None

    def supported_extensions(self) -> List[str]:
        """Return all file extensions supported by registered parsers."""
        exts = []
        for p in self._parsers:
            exts.extend(p.file_extensions)
        return exts
