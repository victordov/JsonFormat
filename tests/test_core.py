"""Tests for the formatter core. Run from the package folder:

    python3 -m unittest discover -s tests
"""

import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import JsonError, containers, format_text, minify_text, parse  # noqa: E402


def fmt(text, **options):
    options.setdefault('indent', '  ')
    return format_text(text, options)[0]


def strict(text, **options):
    return fmt(text, strict_json=True, **options)


class ValuesAreNotCorrupted(unittest.TestCase):
    """Regressions from the old formatter, which treated string contents as syntax."""

    def test_strings_that_look_like_punctuation(self):
        for s in ['', '{', '}', '[', ']', ',', ':', '//', '/*', '"', "'"]:
            src = json.dumps({'a': s, 'b': [s, 1]})
            self.assertEqual(json.loads(strict(src)), {'a': s, 'b': [s, 1]}, s)

    def test_non_ascii_kept_as_written(self):
        self.assertEqual(fmt('{"name": "café ✓"}'), '{\n  "name": "café ✓"\n}')

    def test_ensure_ascii(self):
        self.assertEqual(fmt('["é😀"]', ensure_ascii=True), '[\n  "\\u00e9\\ud83d\\ude00"\n]')

    def test_escapes_kept_as_written(self):
        self.assertEqual(fmt('["\\u00e9\\/x"]'), '[\n  "\\u00e9\\/x"\n]')

    def test_numbers_kept_as_written(self):
        self.assertEqual(fmt('[1.50, -0, 1E+3]'), '[\n  1.50,\n  -0,\n  1E+3\n]')

    def test_surrogate_pair_escapes_are_joined(self):
        doc = parse('"\\ud83d\\ude00"')
        self.assertEqual(doc.value.value, '😀')


class Errors(unittest.TestCase):

    def assertError(self, text, pos, fragment):
        with self.assertRaises(JsonError) as ctx:
            format_text(text)
        self.assertEqual(ctx.exception.pos, pos, ctx.exception.message)
        self.assertIn(fragment, ctx.exception.message)

    def test_garbage_is_rejected_not_dropped(self):
        self.assertError('{"a": 1 @#! }', 8, "'@'")

    def test_unterminated_string(self):
        self.assertError('{"a": "oops}', 6, 'Unterminated string')

    def test_newline_in_string(self):
        self.assertError('["a\nb"]', 1, 'line break')

    def test_unclosed(self):
        self.assertError('{"a": [1, 2', 11, 'never closed')

    def test_missing_comma(self):
        self.assertError('[1 2]', 3, "Expected ',' or ']'")

    def test_missing_colon(self):
        self.assertError('{"a" 1}', 5, "Expected ':'")

    def test_bad_escape(self):
        self.assertError('["\\uZZZZ"]', 2, '\\u escape')
        self.assertError('["\\1"]', 2, 'escape')

    def test_bad_numbers(self):
        for text in ['01', '1.2.3', '0x', '-', '1e', '--1', '1abc']:
            with self.assertRaises(JsonError, msg=text):
                parse(text)

    def test_unquoted_value(self):
        self.assertError('{"a": yes}', 6, 'must be quoted')

    def test_empty_and_extra(self):
        self.assertError('  // nothing\n', 13, 'Empty document')
        self.assertError('{} {}', 3, 'after the end')

    def test_empty_slots(self):
        for text in ['[1,,2]', '[,]', '{,}', '{"a":1,,}']:
            with self.assertRaises(JsonError, msg=text):
                parse(text)

    def test_unterminated_block_comment(self):
        self.assertError('{} /* x', 3, 'block comment')

    def test_deep_nesting_is_an_error_not_a_crash(self):
        with self.assertRaises(JsonError):
            parse('[' * 5000 + ']' * 5000)

    def test_strict_rejects_infinity(self):
        with self.assertRaises(JsonError):
            strict('[NaN]')


class Comments(unittest.TestCase):

    def test_comments_kept_in_place(self):
        src = (
            '// header\n'
            '{\n'
            '  // about a\n'
            '  "a": 1, // trailing a\n'
            '  /* about b */ "b": [ // open\n'
            '    2\n'
            '    // dangling\n'
            '  ]\n'
            '} // end\n'
        )
        self.assertEqual(fmt(src), (
            '// header\n'
            '{\n'
            '  // about a\n'
            '  "a": 1, // trailing a\n'
            '  /* about b */\n'
            '  "b": [ // open\n'
            '    2\n'
            '    // dangling\n'
            '  ]\n'
            '} // end'
        ))

    def test_comment_between_key_and_value_moves_above(self):
        self.assertEqual(fmt('{"a" /*x*/ : /*y*/ 1}'), '{\n  /*x*/\n  /*y*/\n  "a": 1\n}')

    def test_block_comment_reindented(self):
        src = '{\n        /* one\n         * two\n         */\n        "a": 1\n}'
        self.assertEqual(fmt(src), '{\n  /* one\n   * two\n   */\n  "a": 1\n}')

    def test_comments_follow_sorted_members(self):
        src = '{\n  "b": 1, // bee\n  // about a\n  "a": 2\n}'
        self.assertEqual(fmt(src, sort_keys=True), '{\n  // about a\n  "a": 2,\n  "b": 1 // bee\n}')

    def test_empty_container_with_comment(self):
        self.assertEqual(fmt('{\n  // nothing yet\n}'), '{\n  // nothing yet\n}')

    def test_formatting_with_comments_is_stable(self):
        src = (
            '// a\n/* b\n   c */\n\n{ // open\n  "x": 1, /* t */ // t2\n  // lead\n\n'
            '  y: [ /* o */\n     1, // one\n     /* lead2 */ 2,\n     // dangle\n  ],\n'
            "  'z' /* k */ : {}, // after\n  \"w\": { // only comment\n  },\n} // end\n// tail\n"
        )
        for opts in [{}, {'sort_keys': True}, {'inline_width': 80}, {'trailing_commas': 'never'},
                     {'quote_keys': 'as-needed', 'quote_style': 'single'}]:
            once = fmt(src, **opts)
            self.assertEqual(fmt(once, **opts), once, opts)
            for marker in ['// a', 'c */', '// open', '/* t */', '// t2', '// lead', '/* o */',
                           '// one', '/* lead2 */', '// dangle', '/* k */', '// after',
                           '// only comment', '// end', '// tail']:
                self.assertIn(marker, once, opts)

    def test_drop_comments(self):
        self.assertEqual(fmt('{"a": 1 // x\n}', keep_comments=False), '{\n  "a": 1\n}')

    def test_strict_and_minify_drop_comments(self):
        src = '/* c */ {"a": 1, // x\n "b": [2 /* y */]}'
        self.assertEqual(minify_text(src)[0], '{"a":1,"b":[2]}')
        self.assertEqual(json.loads(strict(src)), {'a': 1, 'b': [2]})

    def test_comments_after_the_root_value_are_dropped(self):
        src = '{"a": 1} // same line\n/* next line */\n'
        self.assertEqual(fmt(src, keep_comments=False), '{\n  "a": 1\n}')
        self.assertEqual(json.loads(strict(src)), {'a': 1})


class Layout(unittest.TestCase):

    def test_blank_lines_collapsed_to_one(self):
        self.assertEqual(fmt('{"a": 1,\n\n\n\n"b": 2}'), '{\n  "a": 1,\n\n  "b": 2\n}')
        self.assertEqual(fmt('{"a": 1,\n\n"b": 2}', keep_blank_lines=False), '{\n  "a": 1,\n  "b": 2\n}')

    def test_no_blank_line_after_open_bracket(self):
        self.assertEqual(fmt('{\n\n\n"a": 1\n\n}'), '{\n  "a": 1\n}')

    def test_empty_containers(self):
        self.assertEqual(fmt('{"a": { }, "b": [\n]}'), '{\n  "a": {},\n  "b": []\n}')

    def test_tabs(self):
        self.assertEqual(fmt('{"a": [1]}', indent='\t'), '{\n\t"a": [\n\t\t1\n\t]\n}')

    def test_inline_width(self):
        src = '{"short": [1, 2, 3], "long": [1111111111, 2222222222, 3333333333], "o": {"x": 1}}'
        self.assertEqual(fmt(src, inline_width=30), (
            '{\n'
            '  "short": [1, 2, 3],\n'
            '  "long": [\n'
            '    1111111111,\n'
            '    2222222222,\n'
            '    3333333333\n'
            '  ],\n'
            '  "o": {\n'
            '    "x": 1\n'
            '  }\n'
            '}'
        ))
        self.assertIn('"o": {"x": 1}', fmt(src, inline_width=30, inline_objects=True))

    def test_inline_skips_containers_with_comments(self):
        self.assertEqual(fmt('[1, // one\n2]', inline_width=80), '[\n  1, // one\n  2\n]')

    def test_base_indent_for_selections(self):
        out = format_text('{"a": [1]}', {'indent': '  '}, base_indent='    ')[0]
        self.assertEqual(out, '{\n      "a": [\n        1\n      ]\n    }')

    def test_sort_ignore_case(self):
        self.assertEqual(minify_text('{"b":1,"B":2,"a":3}', {'sort_keys': 'ignore-case'})[0],
                         '{"a":3,"B":2,"b":1}')

    def test_sort_is_recursive(self):
        self.assertEqual(minify_text('{"b":{"d":1,"c":2},"a":[{"z":1,"y":2}]}', {'sort_keys': True})[0],
                         '{"a":[{"y":2,"z":1}],"b":{"c":2,"d":1}}')


class Json5(unittest.TestCase):
    SRC = "{unquoted: 'single', \"q\": 0x1F, n: +.5, m: 5., i: -Infinity, list: [1, 2,],}"

    def test_preserve_by_default(self):
        self.assertEqual(fmt(self.SRC), (
            '{\n'
            "  unquoted: 'single',\n"
            '  "q": 0x1F,\n'
            '  n: +.5,\n'
            '  m: 5.,\n'
            '  i: -Infinity,\n'
            '  list: [\n'
            '    1,\n'
            '    2,\n'
            '  ],\n'
            '}'
        ))

    def test_strict_conversion(self):
        out = strict(self.SRC.replace('i: -Infinity, ', ''))
        self.assertEqual(json.loads(out), {'unquoted': 'single', 'q': 31, 'n': 0.5, 'm': 5.0, 'list': [1, 2]})
        self.assertIn('"n": 0.5', out)
        self.assertIn('"m": 5.0', out)

    def test_to_json5(self):
        out = fmt('{"a-b": 1, "ok_1": "x"}', quote_keys='as-needed', trailing_commas='always', quote_style='single')
        self.assertEqual(out, "{\n  'a-b': 1,\n  ok_1: 'x',\n}")

    def test_quote_conversion_reescapes(self):
        self.assertEqual(fmt("['it\\'s \"q\"']", quote_style='double'), '[\n  "it\'s \\"q\\""\n]')
        self.assertEqual(fmt('["it\'s"]', quote_style='single'), "[\n  'it\\'s'\n]")

    def test_json5_escapes(self):
        doc = parse("'\\x41\\v\\0\\q\\\nB'")
        self.assertEqual(doc.value.value, 'A\v\0qB')
        self.assertEqual(json.loads(strict("'\\x41\\\nB'")), 'AB')

    def test_features_reported(self):
        self.assertEqual(parse('{"a": [1]}').features, set())
        self.assertEqual(parse(self.SRC).features, {
            'unquoted keys', 'single-quoted strings', 'hexadecimal numbers', 'leading + sign',
            'leading/trailing decimal point', 'Infinity/NaN', 'trailing commas'})

    def test_non_json_characters_reported(self):
        self.assertEqual(parse('["a\tb"]').features, {'unescaped control characters in strings'})
        self.assertEqual(strict('["a\tb"]'), '[\n  "a\\tb"\n]')
        self.assertEqual(parse('[1,\u00a02]').features, {'non-standard whitespace'})
        self.assertEqual(parse('[1,\u20282]').features, {'non-standard whitespace'})
        self.assertEqual(parse('\ufeff[1]').features, set())

    def test_duplicate_keys_warned(self):
        doc = parse('{"a": 1,\n"a": 2}')
        self.assertEqual(len(doc.warnings), 1)
        self.assertEqual(doc.warnings[0][0], 9)
        self.assertIn('line 1', doc.warnings[0][1])


class Folding(unittest.TestCase):

    def test_containers_report_depth_and_bracket_offsets(self):
        text = '{"a": {"b": [1, {"c": "]}"}]}, "d": []}'
        found = [(depth, node.kind, text[node.pos], text[node.end])
                 for depth, node in containers(parse(text))]
        self.assertEqual(found, [
            (0, 'object', '{', '}'),
            (1, 'object', '{', '}'),
            (2, 'array', '[', ']'),
            (3, 'object', '{', '}'),
            (1, 'array', '[', ']'),
        ])

    def test_offsets_skip_brackets_in_comments(self):
        text = '[ /* ] */ 1 // ]\n]'
        (_, node), = containers(parse(text))
        self.assertEqual(node.end, len(text) - 1)


class Options(unittest.TestCase):

    def test_invalid_options(self):
        for bad in [{'quote_keys': 'nope'}, {'trailing_commas': True}, {'inline_width': -1},
                    {'indent': 'xx'}, {'sort_keys': 'yes'}]:
            with self.assertRaises(ValueError, msg=bad):
                format_text('{}', bad)


def _random_value(rnd, depth=0):
    choice = rnd.randrange(9 if depth < 4 else 6)
    if choice == 0:
        return rnd.choice([True, False, None])
    if choice == 1:
        return rnd.randint(-10 ** 12, 10 ** 12)
    if choice == 2:
        return rnd.uniform(-1e6, 1e6)
    if choice in (3, 4, 5):
        alphabet = 'ab {}[],:"\'\\/\n\t\x00é😀 '
        return ''.join(rnd.choice(alphabet) for _ in range(rnd.randrange(8)))
    if choice in (6, 7):
        return [_random_value(rnd, depth + 1) for _ in range(rnd.randrange(5))]
    return {rnd.choice(['k', 'a-b', 'é', '', '"', '_$x', str(rnd.random())]): _random_value(rnd, depth + 1)
            for _ in range(rnd.randrange(5))}


class RoundTrip(unittest.TestCase):
    """Random documents survive every mode unchanged in meaning, and formatting is stable."""

    def test_random_documents(self):
        rnd = random.Random(1234)
        modes = [
            {'strict_json': True},
            {'strict_json': True, 'ensure_ascii': True, 'inline_width': 60, 'inline_objects': True},
            {'quote_style': 'single', 'quote_keys': 'as-needed', 'trailing_commas': 'always'},
            {'sort_keys': True},
        ]
        for _ in range(300):
            value = _random_value(rnd)
            src = json.dumps(value, ensure_ascii=rnd.random() < .5, indent=rnd.choice([None, 1, '\t']))
            for opts in modes:
                once = format_text(src, dict(opts, indent='  '))[0]
                self.assertEqual(format_text(once, dict(opts, indent='  '))[0], once, (src, opts))
                as_json = format_text(once, {'strict_json': True})[0]
                self.assertEqual(json.loads(as_json), value, (src, opts))
                self.assertEqual(json.loads(minify_text(once, {'strict_json': True})[0]), value)


if __name__ == '__main__':
    unittest.main()
