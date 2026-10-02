"""Parser for JSON, JSON with comments (JSONC) and JSON5.

Builds a small tree that keeps comments and blank-line hints so the printer
can reformat a document without losing anything. Standard library only and
no Sublime imports, so it can be tested with a plain Python interpreter.
"""

import re
import unicodedata

# value -> container -> value is two Python frames per level; keep well under
# the default recursion limit of 1000 (the printer recurses the same way).
MAX_DEPTH = 200

_WHITESPACE = ' \t\v\f\u00a0\ufeff'
_LINE_TERMINATORS = '\n\r\u2028\u2029'

_NUMBER_RE = re.compile(r'''
    [+-]?
    (?:
        Infinity
      | NaN
      | 0[xX][0-9A-Fa-f]+
      | (?:0|[1-9][0-9]*)(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?
      | \.[0-9]+(?:[eE][+-]?[0-9]+)?
    )
''', re.VERBOSE)

_CONTROL_RE = re.compile(r'[\x00-\x1f]')
_HEX4_RE = re.compile(r'[0-9A-Fa-f]{4}')
_HEX2_RE = re.compile(r'[0-9A-Fa-f]{2}')

_STRING_STOP = {
    '"': re.compile(r'["\\\n\r]'),
    "'": re.compile(r"['\\\n\r]"),
}

_JSON_ESCAPES = {
    '"': '"', '\\': '\\', '/': '/',
    'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t',
}
_JSON5_ESCAPES = {"'": "'", 'v': '\v'}


class JsonError(Exception):
    """A syntax error, or a value that can't be written in the chosen output.

    ``pos`` is an offset into the text that was parsed.
    """

    def __init__(self, message, pos):
        super().__init__(message)
        self.message = message
        self.pos = pos


def line_col(text, pos):
    """1-based line and column of offset ``pos`` in ``text``."""
    line = text.count('\n', 0, pos) + 1
    col = pos - (text.rfind('\n', 0, pos) + 1) + 1
    return line, col


# --------------------------------------------------------------------------
# Tree
# --------------------------------------------------------------------------

class Comment:
    __slots__ = ('text', 'block', 'pos', 'col', 'nl_before')

    def __init__(self, text, block, pos, col, nl_before):
        self.text = text
        self.block = block
        self.pos = pos
        self.col = col              # source column, used to re-indent block comments
        self.nl_before = nl_before  # newlines between the previous token and this one


class Scalar:
    """A string, number, literal (true/false/null) or object key."""

    __slots__ = ('kind', 'value', 'raw', 'quote', 'pos')

    def __init__(self, kind, value, raw, quote, pos):
        self.kind = kind    # 'string' | 'number' | 'literal' | 'key'
        self.value = value  # decoded text for strings and keys
        self.raw = raw      # exact source text
        self.quote = quote  # '"', "'" or None (number, literal, unquoted key)
        self.pos = pos


class Member:
    """An object member or array element, with the comments around it."""

    __slots__ = ('key', 'value', 'leading', 'trailing', 'nl_before')

    def __init__(self):
        self.key = None       # Scalar for object members, None for array elements
        self.value = None
        self.leading = []     # comments on the lines above
        self.trailing = []    # comments on the same line, after the value/comma
        self.nl_before = 0    # newlines before the key (or value)


class Container:
    __slots__ = ('kind', 'items', 'open_comments', 'dangling',
                 'trailing_comma', 'pos', 'end')

    def __init__(self, kind, pos):
        self.kind = kind          # 'object' | 'array'
        self.items = []
        self.open_comments = []   # comments on the same line as the opening bracket
        self.dangling = []        # comments after the last item
        self.trailing_comma = False
        self.pos = pos            # offset of the opening bracket
        self.end = None           # offset of the closing bracket


class Document:
    __slots__ = ('value', 'leading', 'value_nl', 'trailing', 'warnings',
                 'features')

    def __init__(self):
        self.value = None
        self.leading = []
        self.value_nl = 0
        self.trailing = []
        self.warnings = []       # [(pos, message)]
        self.features = set()    # non-standard JSON features used by the input


# --------------------------------------------------------------------------
# Lexer
# --------------------------------------------------------------------------

class _Token:
    __slots__ = ('type', 'value', 'raw', 'pos', 'nl_before', 'quote')

    def __init__(self, type_, value, raw, pos, nl_before, quote=None):
        self.type = type_
        self.value = value
        self.raw = raw
        self.pos = pos
        self.nl_before = nl_before
        self.quote = quote


def _is_ident_start(c):
    return c.isalpha() or c in '$_'


def _is_ident_part(c):
    return (c.isalnum() or c in '$_\u200c\u200d'
            or unicodedata.category(c) in ('Mn', 'Mc', 'Pc'))


def _join_surrogates(s):
    """Turn escaped surrogate pairs (\\ud83d\\ude00) into the real character."""
    if not any('\ud800' <= c <= '\udfff' for c in s):
        return s
    try:
        return s.encode('utf-16-le', 'surrogatepass').decode('utf-16-le')
    except UnicodeDecodeError:
        return s  # lone surrogates; the printer escapes them again


def _read_string(text, i, features):
    quote = text[i]
    start = i
    if quote == "'":
        features.add('single-quoted strings')
    stop = _STRING_STOP[quote]
    n = len(text)
    out = []
    i += 1
    while True:
        m = stop.search(text, i)
        if m is None:
            raise JsonError('Unterminated string', start)
        chunk = text[i:m.start()]
        if _CONTROL_RE.search(chunk):
            features.add('unescaped control characters in strings')
        out.append(chunk)
        i = m.start()
        c = text[i]
        if c == quote:
            i += 1
            break
        if c in '\n\r':
            raise JsonError('Unterminated string (line break inside a string)', start)
        # backslash escape
        i += 1
        if i >= n:
            raise JsonError('Unterminated string', start)
        e = text[i]
        if e in _JSON_ESCAPES:
            out.append(_JSON_ESCAPES[e])
            i += 1
        elif e == 'u':
            if not _HEX4_RE.match(text, i + 1):
                raise JsonError('Invalid \\u escape (expected 4 hex digits)', i - 1)
            out.append(chr(int(text[i + 1:i + 5], 16)))
            i += 5
        elif e in '123456789' or (e == '0' and text[i + 1:i + 2].isdigit()):
            raise JsonError('Invalid escape sequence \\' + e, i - 1)
        else:
            features.add('JSON5 string escapes')
            if e in _JSON5_ESCAPES:
                out.append(_JSON5_ESCAPES[e])
                i += 1
            elif e == '0':
                out.append('\0')
                i += 1
            elif e == 'x':
                if not _HEX2_RE.match(text, i + 1):
                    raise JsonError('Invalid \\x escape (expected 2 hex digits)', i - 1)
                out.append(chr(int(text[i + 1:i + 3], 16)))
                i += 3
            elif e in _LINE_TERMINATORS:
                # line continuation: backslash + newline contributes nothing
                i += 2 if text[i:i + 2] == '\r\n' else 1
            else:
                out.append(e)  # JSON5 allows any other character to be escaped
                i += 1
    return _join_surrogates(''.join(out)), i


def _read_number(text, i, features):
    m = _NUMBER_RE.match(text, i)
    end = m.end() if m else i
    if not m or (end < len(text) and (_is_ident_part(text[end]) or text[end] == '.')):
        j = end
        while j < len(text) and (_is_ident_part(text[j]) or text[j] in '.+-'):
            j += 1
        raise JsonError('Invalid number {!r}'.format(text[i:max(j, i + 1)]), i)
    raw = m.group()
    body = raw.lstrip('+-')
    if raw[0] == '+':
        features.add('leading + sign')
    if body in ('Infinity', 'NaN'):
        features.add('Infinity/NaN')
    elif body[:2] in ('0x', '0X'):
        features.add('hexadecimal numbers')
    elif body.startswith('.') or re.search(r'\.(?![0-9])', body):
        features.add('leading/trailing decimal point')
    return end


def tokenize(text, features):
    tokens = []
    i = 0
    n = len(text)
    nl = 0
    while True:
        while i < n:
            c = text[i]
            if c == '\n':
                nl += 1
                i += 1
            elif c == '\u2028' or c == '\u2029':
                features.add('non-standard whitespace')
                nl += 1
                i += 1
            elif c == '\r':
                nl += 1
                i += 1
                if i < n and text[i] == '\n':
                    i += 1
            elif c in ' \t':
                i += 1
            elif c in _WHITESPACE or c.isspace():
                if c != '\ufeff' or i:  # a leading byte order mark is fine
                    features.add('non-standard whitespace')
                i += 1
            else:
                break
        if i >= n:
            tokens.append(_Token('eof', None, '', n, nl))
            return tokens

        start = i
        c = text[i]
        if c in '{}[]:,':
            i += 1
            tok = _Token(c, c, c, start, nl)
        elif c == '/':
            nxt = text[i + 1:i + 2]
            if nxt == '/':
                end = i + 2
                while end < n and text[end] not in _LINE_TERMINATORS:
                    end += 1
                i = end
                tok = _Token('comment', text[start:end].rstrip(), None, start, nl, False)
            elif nxt == '*':
                end = text.find('*/', i + 2)
                if end == -1:
                    raise JsonError('Unterminated block comment', start)
                i = end + 2
                tok = _Token('comment', text[start:i], None, start, nl, True)
            else:
                raise JsonError("Unexpected character '/'", start)
            features.add('comments')
        elif c == '"' or c == "'":
            value, i = _read_string(text, i, features)
            tok = _Token('string', value, text[start:i], start, nl, c)
        elif c in '+-.0123456789':
            i = _read_number(text, i, features)
            tok = _Token('number', None, text[start:i], start, nl)
        elif _is_ident_start(c):
            i += 1
            while i < n and _is_ident_part(text[i]):
                i += 1
            name = text[start:i]
            tok = _Token('ident', name, name, start, nl)
        else:
            raise JsonError('Unexpected character {!r}'.format(c), start)
        tokens.append(tok)
        nl = 0


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

def _describe(tok):
    if tok.type == 'eof':
        return 'end of input'
    if tok.type == 'string':
        return 'a string'
    if tok.type == 'number':
        return 'number ' + tok.raw
    if tok.type == 'comment':
        return 'a comment'
    raw = tok.raw if len(tok.raw) <= 20 else tok.raw[:20] + '...'
    return "'{}'".format(raw)


def _split_same_line(comments):
    """Split off the comments that sit on the same line as the previous token."""
    k = 0
    while k < len(comments) and comments[k].nl_before == 0:
        k += 1
        if not comments[k - 1].block:
            break  # a line comment ends the line
    return comments[:k], comments[k:]


class _Parser:

    def __init__(self, text):
        self.text = text
        self.doc = Document()
        self.toks = tokenize(text, self.doc.features)
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def next(self):
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def comments(self):
        out = []
        while self.toks[self.i].type == 'comment':
            tok = self.next()
            col = tok.pos - (self.text.rfind('\n', 0, tok.pos) + 1)
            out.append(Comment(tok.value, tok.quote, tok.pos, col, tok.nl_before))
        return out

    def document(self):
        doc = self.doc
        doc.leading = self.comments()
        tok = self.peek()
        if tok.type == 'eof':
            raise JsonError('Empty document: no JSON value found', tok.pos)
        doc.value_nl = tok.nl_before
        doc.value = self.value(0)
        doc.trailing = self.comments()
        tok = self.peek()
        if tok.type != 'eof':
            raise JsonError('Unexpected {} after the end of the JSON value'
                            .format(_describe(tok)), tok.pos)
        return doc

    def value(self, depth):
        tok = self.next()
        t = tok.type
        if t == '{' or t == '[':
            return self.container(tok, depth)
        if t == 'string':
            return Scalar('string', tok.value, tok.raw, tok.quote, tok.pos)
        if t == 'number':
            return Scalar('number', None, tok.raw, None, tok.pos)
        if t == 'ident':
            if tok.value in ('true', 'false', 'null'):
                return Scalar('literal', None, tok.raw, None, tok.pos)
            if tok.value in ('Infinity', 'NaN'):
                self.doc.features.add('Infinity/NaN')
                return Scalar('number', None, tok.raw, None, tok.pos)
            raise JsonError("Unexpected word '{}' (string values must be quoted)"
                            .format(tok.value), tok.pos)
        raise JsonError('Expected a value but found ' + _describe(tok), tok.pos)

    def key(self):
        tok = self.next()
        if tok.type == 'string':
            return Scalar('key', tok.value, tok.raw, tok.quote, tok.pos)
        if tok.type == 'ident':
            self.doc.features.add('unquoted keys')
            return Scalar('key', tok.value, tok.raw, None, tok.pos)
        raise JsonError('Expected a property name but found ' + _describe(tok), tok.pos)

    def container(self, open_tok, depth):
        if depth >= MAX_DEPTH:
            raise JsonError('Nesting is too deep (more than {} levels)'
                            .format(MAX_DEPTH), open_tok.pos)
        is_object = open_tok.type == '{'
        close = '}' if is_object else ']'
        node = Container('object' if is_object else 'array', open_tok.pos)
        seen = {} if is_object else None

        node.open_comments, pending = _split_same_line(self.comments())
        while True:
            pending += self.comments()
            tok = self.peek()
            if tok.type == close:
                self.next()
                node.end = tok.pos
                node.dangling = pending
                return node
            if tok.type == 'eof':
                self.unclosed(open_tok, tok)

            item = Member()
            item.leading = pending
            item.nl_before = tok.nl_before
            if is_object:
                item.key = self.key()
                if item.key.value in seen:
                    line, _ = line_col(self.text, seen[item.key.value])
                    self.doc.warnings.append((item.key.pos, 'Duplicate key {!r} (first defined on line {})'
                                              .format(item.key.value, line)))
                else:
                    seen[item.key.value] = item.key.pos
                item.leading += self.inner_comments()
                tok = self.next()
                if tok.type != ':':
                    raise JsonError("Expected ':' after the property name but found "
                                    + _describe(tok), tok.pos)
                item.leading += self.inner_comments()
            item.value = self.value(depth + 1)
            node.items.append(item)

            item.trailing, pending = _split_same_line(self.comments())
            tok = self.peek()
            if tok.type == ',':
                self.next()
                after = self.comments()
                if pending:
                    pending += after
                else:
                    more, pending = _split_same_line(after)
                    item.trailing += more
                if self.peek().type == close:
                    node.trailing_comma = True
                    self.doc.features.add('trailing commas')
            elif tok.type == 'eof':
                self.unclosed(open_tok, tok)
            elif tok.type != close:
                raise JsonError("Expected ',' or '{}' but found {}"
                                .format(close, _describe(tok)), tok.pos)

    def inner_comments(self):
        # Comments between a key and its value are moved above the member.
        out = self.comments()
        for c in out:
            c.nl_before = 1
        return out

    def unclosed(self, open_tok, tok):
        line, col = line_col(self.text, open_tok.pos)
        raise JsonError("Unexpected end of input: '{}' opened at line {}, column {} is never closed"
                        .format(open_tok.type, line, col), tok.pos)


def containers(doc):
    """Yield ``(depth, container)`` for every object/array; the root is depth 0."""
    stack = [(0, doc.value)]
    while stack:
        depth, node = stack.pop()
        if isinstance(node, Container):
            yield depth, node
            stack.extend((depth + 1, m.value) for m in reversed(node.items))


def parse(text):
    """Parse JSON / JSONC / JSON5 text into a :class:`Document`.

    Raises :class:`JsonError` on invalid input; nothing is guessed or dropped.
    """
    return _Parser(text).document()
