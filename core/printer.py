"""Turns a parsed :class:`~.parser.Document` back into text."""

import re

from .parser import Container, JsonError, Scalar

DEFAULTS = {
    'indent': '    ',               # the indent unit itself: spaces or '\t'
    'sort_keys': False,             # False | True | 'ignore-case'
    'ensure_ascii': False,          # escape every non-ASCII character
    'quote_keys': 'preserve',       # 'preserve' | 'always' | 'as-needed'
    'quote_style': 'preserve',      # 'preserve' | 'double' | 'single'
    'trailing_commas': 'preserve',  # 'preserve' | 'never' | 'always'
    'keep_comments': True,
    'keep_blank_lines': True,       # keep (at most one) blank line between items
    'inline_width': 0,              # > 0: put short containers on one line
    'inline_objects': False,        # inline_width applies to objects too
    'strict_json': False,           # output standard JSON (RFC 8259)
}

_CHOICES = {
    'sort_keys': (False, True, 'ignore-case'),
    'quote_keys': ('preserve', 'always', 'as-needed'),
    'quote_style': ('preserve', 'double', 'single'),
    'trailing_commas': ('preserve', 'never', 'always'),
}

_IDENTIFIER_RE = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*\Z')

_ESCAPES = {'\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


def resolve_options(options):
    """Merge ``options`` over the defaults and validate them."""
    opts = dict(DEFAULTS)
    for key, value in (options or {}).items():
        if key in DEFAULTS:
            opts[key] = value
    for key, allowed in _CHOICES.items():
        if opts[key] not in allowed or (key != 'sort_keys' and isinstance(opts[key], bool)):
            raise ValueError('Invalid value for "{}": {!r} (expected one of: {})'
                             .format(key, opts[key], ', '.join(repr(a) for a in allowed)))
    indent = opts['indent']
    if not isinstance(indent, str) or indent.strip(' \t'):
        raise ValueError('Invalid indent unit: {!r}'.format(indent))
    width = opts['inline_width']
    if not isinstance(width, int) or isinstance(width, bool) or width < 0:
        raise ValueError('Invalid value for "inline_width": {!r} (expected a number >= 0)'
                         .format(width))
    if opts['strict_json']:
        opts.update(quote_keys='always', quote_style='double',
                    trailing_commas='never', keep_comments=False)
    return opts


def encode_string(s, quote, ensure_ascii):
    out = [quote]
    for ch in s:
        o = ord(ch)
        if ch == quote:
            out.append('\\' + ch)
        elif ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif o < 0x20 or o == 0x7f or 0xd800 <= o <= 0xdfff or o in (0x2028, 0x2029):
            out.append('\\u{:04x}'.format(o))
        elif ensure_ascii and o > 0x7e:
            if o > 0xffff:
                o -= 0x10000
                out.append('\\u{:04x}\\u{:04x}'.format(0xd800 | (o >> 10), 0xdc00 | (o & 0x3ff)))
            else:
                out.append('\\u{:04x}'.format(o))
        else:
            out.append(ch)
    out.append(quote)
    return ''.join(out)


def strict_number(node):
    """Rewrite a JSON5 number literal as a standard JSON number."""
    raw = node.raw
    sign = '-' if raw[0] == '-' else ''
    body = raw.lstrip('+-')
    if body in ('Infinity', 'NaN'):
        raise JsonError('{} cannot be represented in standard JSON'.format(raw), node.pos)
    if body[:2] in ('0x', '0X'):
        return sign + str(int(body, 16))
    mantissa, e, exponent = body.partition('e') if 'e' in body else body.partition('E')
    if mantissa.startswith('.'):
        mantissa = '0' + mantissa
    if mantissa.endswith('.'):
        mantissa += '0'
    return sign + mantissa + e + exponent


class _TooWide(Exception):
    pass


class Printer:

    def __init__(self, options=None, base_indent=''):
        o = resolve_options(options)
        self.o = o
        self.unit = o['indent']
        self.base = base_indent
        self.keep_comments = o['keep_comments']
        self.keep_blank = o['keep_blank_lines']

    # ---- entry points ------------------------------------------------------

    def format(self, doc):
        lines = []
        if self.keep_comments:
            for c in doc.leading:
                self._blank(lines, c.nl_before, 0)
                lines.append(self.base + self._comment(c, 0))
            self._blank(lines, doc.value_nl, 0)
        line = self.base + self._value(doc.value, 0, len(self.base))
        trailing, rest = self._split(doc.trailing)
        if trailing:
            line += ' ' + ' '.join(self._comment(c, 0) for c in trailing)
        lines.append(line)
        for c in rest:
            self._blank(lines, c.nl_before, 0)
            lines.append(self.base + self._comment(c, 0))
        return '\n'.join(lines)[len(self.base):]

    def minify(self, doc):
        return self._flat(doc.value, compact=True, limit=None)

    # ---- values ------------------------------------------------------------

    def _value(self, node, level, col):
        if isinstance(node, Scalar):
            return self._scalar(node)
        if not node.items and not (self.keep_comments and (node.dangling or node.open_comments)):
            return '{}' if node.kind == 'object' else '[]'
        width = self.o['inline_width']
        if width and (node.kind == 'array' or self.o['inline_objects']):
            flat = self._flat(node, compact=False, limit=width - col)
            if flat is not None:
                return flat
        return self._expanded(node, level)

    def _expanded(self, node, level):
        is_object = node.kind == 'object'
        inner = self._indent(level + 1)
        first = '{' if is_object else '['
        if self.keep_comments and node.open_comments:
            first += ' ' + ' '.join(self._comment(c, level + 1) for c in node.open_comments)
        lines = [first]
        items = self._ordered(node)
        # blank lines mean nothing once members are reordered
        keep_blank = items is node.items
        last = len(items) - 1
        comma_after_last = self._trailing_comma(node)
        for idx, m in enumerate(items):
            if self.keep_comments:
                for c in m.leading:
                    self._blank(lines, c.nl_before, 1, keep_blank)
                    lines.append(inner + self._comment(c, level + 1))
            self._blank(lines, m.nl_before, 1, keep_blank)
            prefix = inner
            if is_object:
                prefix += self._key(m.key) + ': '
            text = prefix + self._value(m.value, level + 1, len(prefix))
            if idx < last or comma_after_last:
                text += ','
            if self.keep_comments and m.trailing:
                text += ' ' + ' '.join(self._comment(c, level + 1) for c in m.trailing)
            lines.append(text)
        if self.keep_comments:
            for c in node.dangling:
                self._blank(lines, c.nl_before, 1)
                lines.append(inner + self._comment(c, level + 1))
        lines.append(self._indent(level) + ('}' if is_object else ']'))
        return '\n'.join(lines)

    def _flat(self, node, compact, limit):
        """Single-line form of ``node``; None if it has comments or exceeds ``limit``."""
        out = []
        size = [0]
        item_sep = ',' if compact else ', '
        key_sep = ':' if compact else ': '

        def put(s):
            out.append(s)
            size[0] += len(s)
            if limit is not None and size[0] > limit:
                raise _TooWide

        def walk(n):
            if isinstance(n, Scalar):
                put(self._scalar(n))
                return
            if not compact and self.keep_comments and (
                    n.open_comments or n.dangling
                    or any(m.leading or m.trailing for m in n.items)):
                raise _TooWide
            is_object = n.kind == 'object'
            put('{' if is_object else '[')
            for idx, m in enumerate(self._ordered(n)):
                if idx:
                    put(item_sep)
                if is_object:
                    put(self._key(m.key))
                    put(key_sep)
                walk(m.value)
            put('}' if is_object else ']')

        try:
            walk(node)
        except _TooWide:
            return None
        return ''.join(out)

    def _scalar(self, node):
        if node.kind == 'string':
            return self._string(node)
        if node.kind == 'number' and self.o['strict_json']:
            return strict_number(node)
        return node.raw

    def _key(self, key):
        mode = self.o['quote_keys']
        if mode == 'as-needed' and _IDENTIFIER_RE.match(key.value):
            return key.value
        if mode == 'preserve' and key.quote is None:
            return key.raw
        return self._string(key)

    def _string(self, node):
        style = self.o['quote_style']
        if style == 'double':
            quote = '"'
        elif style == 'single':
            quote = "'"
        else:
            quote = node.quote or '"'
        if quote == node.quote and not self.o['ensure_ascii'] and not self.o['strict_json']:
            return node.raw  # keep the author's escapes exactly as written
        return encode_string(node.value, quote, self.o['ensure_ascii'])

    # ---- helpers -----------------------------------------------------------

    def _ordered(self, node):
        mode = self.o['sort_keys']
        if node.kind != 'object' or not mode:
            return node.items
        if mode == 'ignore-case':
            return sorted(node.items, key=lambda m: (m.key.value.lower(), m.key.value))
        return sorted(node.items, key=lambda m: m.key.value)

    def _trailing_comma(self, node):
        mode = self.o['trailing_commas']
        if mode == 'always':
            return bool(node.items)
        if mode == 'preserve':
            return node.trailing_comma
        return False

    def _indent(self, level):
        return self.base + self.unit * level

    def _blank(self, lines, nl_before, start, allowed=True):
        if allowed and self.keep_blank and nl_before >= 2 and len(lines) > start and lines[-1]:
            lines.append('')

    def _split(self, comments):
        k = 0
        while k < len(comments) and comments[k].nl_before == 0:
            k += 1
            if not comments[k - 1].block:
                break
        return comments[:k], comments[k:]

    def _comment(self, c, level):
        text = c.text
        if not c.block or '\n' not in text:
            return text
        # Re-indent continuation lines of a block comment relative to its start.
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        indent = self._indent(level)
        out = [lines[0]]
        for line in lines[1:]:
            stripped = line
            k = 0
            while k < c.col and stripped[:1] in (' ', '\t'):
                stripped = stripped[1:]
                k += 1
            out.append(indent + stripped if stripped.strip() else '')
        return '\n'.join(out)


def format_document(doc, options=None, base_indent=''):
    return Printer(options, base_indent).format(doc)


def minify_document(doc, options=None):
    return Printer(options).minify(doc)
