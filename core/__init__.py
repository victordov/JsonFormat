"""Comment-preserving JSON / JSONC / JSON5 formatter (no Sublime dependency)."""

from .parser import JsonError, containers, line_col, parse
from .printer import DEFAULTS, format_document, minify_document, resolve_options

__all__ = ['DEFAULTS', 'JsonError', 'containers', 'format_text', 'line_col', 'minify_text',
           'parse', 'resolve_options']


def format_text(text, options=None, base_indent=''):
    """Return ``(formatted_text, document)``. Raises JsonError or ValueError."""
    doc = parse(text)
    return format_document(doc, options, base_indent), doc


def minify_text(text, options=None):
    """Return ``(minified_text, document)``. Comments are always removed."""
    doc = parse(text)
    return minify_document(doc, options), doc
