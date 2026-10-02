import html

import sublime
import sublime_plugin

from .core import DEFAULTS, JsonError, containers, format_text, minify_text, parse

SETTINGS_FILE = 'JsonFormat.sublime-settings'
MARKS_KEY = 'json_format_marks'


def _setting(view, key, default=None):
    """Per-view/project value ("json_format.<key>") overrides the package setting."""
    value = view.settings().get('json_format.' + key)
    if value is None:
        value = sublime.load_settings(SETTINGS_FILE).get(key, default)
    return value


def _indent_unit(view, value):
    if value == 'auto':
        if view.settings().get('translate_tabs_to_spaces', False):
            return ' ' * int(view.settings().get('tab_size', 4))
        return '\t'
    if value in ('tab', '\t'):
        return '\t'
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 16:
        return ' ' * value
    raise ValueError('Invalid "indent" setting: {!r} (use "auto", "tab" or 0-16)'.format(value))


def _options(view, overrides):
    opts = {}
    for key in DEFAULTS:
        value = _setting(view, key)
        if value is not None:
            opts[key] = value
    opts.update(overrides or {})
    opts['indent'] = _indent_unit(view, opts.get('indent', 'auto'))
    return opts


def _strip_span(text):
    """(start, end) of ``text`` without surrounding whitespace, or None if blank."""
    start = len(text) - len(text.lstrip())
    end = len(text.rstrip())
    return (start, end) if end > start else None


def _line_indent(view, pt):
    line = view.substr(view.line(pt))
    return line[:len(line) - len(line.lstrip(' \t'))]


def _show_marks(view, marks):
    """Underline points and annotate them with messages: [(point, message)]."""
    if not marks:
        view.erase_regions(MARKS_KEY)
        return
    if not _setting(view, 'show_annotations', True):
        return
    view.add_regions(
        MARKS_KEY,
        [sublime.Region(pt, min(pt + 1, view.size())) for pt, _ in marks],
        scope='region.redish',
        icon='circle',
        flags=(sublime.DRAW_SQUIGGLY_UNDERLINE | sublime.DRAW_NO_FILL
               | sublime.DRAW_NO_OUTLINE | sublime.DRAW_EMPTY_AS_OVERWRITE),
        annotations=[html.escape(msg) for _, msg in marks],
        annotation_color='#e06c75',
    )


def _report_error(view, pt, message, jump):
    row, col = view.rowcol(pt)
    text = '{} (line {}, column {})'.format(message, row + 1, col + 1)
    sublime.status_message('JsonFormat: ' + text)
    _show_marks(view, [(pt, message)])
    if jump and _setting(view, 'jump_to_error', True):
        view.sel().clear()
        view.sel().add(pt)
        view.show_at_center(pt)


def _too_large(view):
    limit = _setting(view, 'max_size_kb', 5120)
    if limit and view.size() > limit * 1024:
        sublime.status_message('JsonFormat: file is larger than max_size_kb ({} KB), skipped'
                               .format(limit))
        return True
    return False


class JsonFormatFormatCommand(sublime_plugin.TextCommand):
    """Format (or minify) the selections, or the whole file if nothing is selected.

    Args:
        options: overrides for the formatting settings, e.g. {"sort_keys": true}
        minify:  write everything on one line (comments are removed)
        whole_file: ignore selections (used by format on save)
    """

    def run(self, edit, options=None, minify=False, whole_file=False):
        view = self.view
        view.erase_regions(MARKS_KEY)
        if _too_large(view):
            return
        try:
            opts = _options(view, options)
        except ValueError as e:
            sublime.status_message('JsonFormat: ' + str(e))
            if not whole_file:
                sublime.error_message('JsonFormat settings error:\n\n' + str(e))
            return

        regions = [] if whole_file else [r for r in view.sel() if not r.empty()]
        whole = not regions
        if whole:
            regions = [sublime.Region(0, view.size())]

        # Format everything first so an error anywhere leaves the buffer untouched.
        edits = []
        warnings = 0
        for region in regions:
            text = view.substr(region)
            span = _strip_span(text)
            if span is None:
                continue
            begin = region.begin() + span[0]
            source = text[span[0]:span[1]]
            try:
                if minify:
                    out, doc = minify_text(source, opts)
                else:
                    base = '' if whole else _line_indent(view, begin)
                    out, doc = format_text(source, opts, base)
            except JsonError as e:
                _report_error(view, begin + e.pos, e.message, jump=not whole_file)
                return
            except ValueError as e:
                sublime.status_message('JsonFormat: ' + str(e))
                return
            warnings += len(doc.warnings)
            if whole:
                target = sublime.Region(0, view.size())
                if _setting(view, 'final_newline', True):
                    out += '\n'
            else:
                target = sublime.Region(begin, region.begin() + span[1])
            if view.substr(target) != out:
                edits.append((target, out))

        if not edits:
            msg = 'already formatted'
        else:
            self._apply(edit, edits, whole)
            msg = 'minified' if minify else 'formatted'
        if warnings:
            msg += ', {} duplicate key(s) - run "JsonFormat: Validate" to see them'.format(warnings)
        sublime.status_message('JsonFormat: ' + msg)

    def _apply(self, edit, edits, whole):
        view = self.view
        if whole:
            # Keep the caret on the same line/column and the viewport in place.
            row, col = view.rowcol(view.sel()[0].begin()) if len(view.sel()) else (0, 0)
            viewport = view.viewport_position()
            view.replace(edit, edits[0][0], edits[0][1])
            last_row = view.rowcol(view.size())[0]
            line = view.line(view.text_point(min(row, last_row), 0))
            pt = min(line.begin() + col, line.end())
            view.sel().clear()
            view.sel().add(pt)
            view.set_viewport_position(viewport, False)
            return
        # Bottom-up so earlier edits don't shift the regions of later ones.
        for target, text in sorted(edits, key=lambda e: e[0].begin(), reverse=True):
            view.replace(edit, target, text)


class JsonFormatValidateCommand(sublime_plugin.TextCommand):
    """Check the whole file and report errors, duplicate keys and JSON5 features."""

    def run(self, edit):
        view = self.view
        view.erase_regions(MARKS_KEY)
        if _too_large(view):
            return
        text = view.substr(sublime.Region(0, view.size()))
        try:
            doc = parse(text)
        except JsonError as e:
            _report_error(view, e.pos, e.message, jump=True)
            return
        if doc.features:
            msg = 'valid JSON5 (not standard JSON: {})'.format(', '.join(sorted(doc.features)))
        else:
            msg = 'valid JSON'
        if doc.warnings:
            msg += ', {} duplicate key(s)'.format(len(doc.warnings))
            _show_marks(view, doc.warnings)
        sublime.status_message('JsonFormat: ' + msg)


def _foldable(view):
    """[(depth, Region inside the brackets)] for every non-empty container.

    Containers on a single line are skipped unless the whole file is one line
    (minified), so short inline arrays don't turn into a row of ellipses.
    Returns None (after reporting it) if the file can't be parsed.
    """
    view.erase_regions(MARKS_KEY)
    if _too_large(view):
        return None
    text = view.substr(sublime.Region(0, view.size()))
    try:
        doc = parse(text)
    except JsonError as e:
        _report_error(view, e.pos, e.message, jump=True)
        return None
    one_line = '\n' not in text.strip()
    return [(depth, sublime.Region(node.pos + 1, node.end))
            for depth, node in containers(doc)
            if node.end > node.pos + 1 and (one_line or '\n' in text[node.pos:node.end])]


def _fold_deepest_first(view, targets):
    # Folding inner blocks before outer ones lets Sublime keep them folded
    # when the outer block is opened, so each click reveals one more level.
    for depth in sorted({d for d, _ in targets}, reverse=True):
        view.fold([r for d, r in targets if d == depth])


class JsonFormatFoldCommand(sublime_plugin.TextCommand):
    """Fold every object/array nested ``level`` or more levels deep.

    level=1 shows the root's members with each of their values collapsed.
    """

    def run(self, edit, level=1):
        view = self.view
        targets = _foldable(view)
        if targets is None:
            return
        view.unfold(sublime.Region(0, view.size()))
        targets = [(d, r) for d, r in targets if d >= level]
        _fold_deepest_first(view, targets)
        sublime.status_message('JsonFormat: folded to level {} ({} blocks)'.format(
            level, sum(1 for d, _ in targets if d == level)))


class JsonFormatUnfoldAllCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        self.view.unfold(sublime.Region(0, self.view.size()))


class JsonFormatToggleFoldCommand(sublime_plugin.TextCommand):
    """Fold the block at the caret, or unfold it one level (children stay folded).

    The block is the first object/array that opens on the caret's line, or
    otherwise the innermost one containing the caret.
    """

    def run(self, edit):
        view = self.view
        targets = _foldable(view)
        if targets is None:
            return
        for sel in list(view.sel()):
            target = self._target(view, targets, sel.b)
            if target is None:
                continue
            depth, inner = target
            if any(f.contains(inner) for f in view.folded_regions()):
                view.unfold(inner)
                _fold_deepest_first(view, [(d, r) for d, r in targets
                                           if d > depth and inner.contains(r)])
            else:
                view.fold(inner)

    @staticmethod
    def _target(view, targets, pt):
        line = view.line(pt)
        on_line = [t for t in targets if line.contains(t[1].begin() - 1)]
        if on_line:
            return min(on_line, key=lambda t: t[0])
        around = [t for t in targets if t[1].begin() <= pt <= t[1].end()]
        return max(around, key=lambda t: t[0]) if around else None


class JsonFormatFoldButtons(sublime_plugin.ViewEventListener):
    """Keep the gutter fold arrows visible in JSON views instead of only on hover."""

    @classmethod
    def is_applicable(cls, settings):
        return 'JSON' in (settings.get('syntax') or '')

    def on_activated_async(self):
        if _setting(self.view, 'always_show_fold_buttons', True):
            self.view.settings().set('fade_fold_buttons', False)


class JsonFormatListener(sublime_plugin.EventListener):

    def on_pre_save(self, view):
        if not _setting(view, 'format_on_save', False):
            return
        name = (view.file_name() or '').lower()
        extensions = _setting(view, 'format_on_save_extensions', ['.json', '.jsonc', '.json5'])
        if any(name.endswith(ext.lower()) for ext in extensions):
            view.run_command('json_format_format', {'whole_file': True})

    def on_modified_async(self, view):
        if view.get_regions(MARKS_KEY):
            view.erase_regions(MARKS_KEY)
