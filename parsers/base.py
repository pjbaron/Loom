"""Abstract base interface for language-specific parsers."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple, Union
from pathlib import Path


# Relationship can be 3-tuple (from, to, type) or 4-tuple (from, to, type, metadata)
Relationship = Union[Tuple[str, str, str], Tuple[str, str, str, Dict[str, Any]]]


class ParseResult:
    """Result of parsing a single file."""

    def __init__(self):
        self.entities: List[Dict[str, Any]] = []  # {name, kind, file, start_line, end_line, metadata, intent}
        self.relationships: List[Relationship] = []  # (from_name, to_name, relation_type[, metadata])
        self.errors: List[str] = []


class BaseParser(ABC):
    """Abstract base for language-specific parsers."""

    @property
    @abstractmethod
    def language(self) -> str:
        """Return language identifier, e.g. 'python', 'javascript', 'cpp'"""
        pass

    @property
    @abstractmethod
    def file_extensions(self) -> List[str]:
        """Return list of extensions this parser handles, e.g. ['.py', '.pyw']"""
        pass

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """Return True if this parser can handle the given file."""
        pass

    @abstractmethod
    def parse_file(self, file_path: Path, source: str = None) -> ParseResult:
        """Parse a file and return entities and relationships.

        Args:
            file_path: Path to the file
            source: Optional source code (if already read)

        Returns:
            ParseResult with entities, relationships, and any errors
        """
        pass

    def parse_files(self, file_paths: List[Path]) -> List[ParseResult]:
        """Parse multiple files. Default implementation calls parse_file for each."""
        results = []
        for path in file_paths:
            if self.can_parse(path):
                results.append(self.parse_file(path))
        return results
