# JsonFormat

A Sublime Text 4 package that formats, minifies, converts, validates and folds **JSON**, **JSONC** (JSON with comments) and **JSON5**. It keeps your comments.

- **Self-contained.** Runs inside Sublime's own Python 3.8 using only the standard library. It needs no external Python, no `pip install`, no third-party code and no network access.
- **Never corrupts data.** Invalid input is reported with its line and column and the buffer is left untouched. Nothing is guessed or silently dropped.
- **Keeps what you wrote.** By default string escapes, number spelling (`1.50`, `0x1F`), quote style, key quoting and trailing commas stay as they are. Only the layout changes.
- **Structural folding.** Collapse and expand objects and arrays by nesting level, based on the JSON structure rather than indentation.

**Requirements:** Sublime Text 4 (build 4050 or later), any platform.

## Contents

- [Installation](#installation)
- [Commands](#commands)
- [Folding](#folding)
- [Settings](#settings)
- [How comments are placed](#how-comments-are-placed)
- [Development](#development)
- [Limitations](#limitations)
- [License](#license)

## Installation

### Package Control

Open the Command Palette, run **Package Control: Install Package** and choose **JsonFormat**.

Until the package is listed in the default channel, first run **Package Control: Add Repository** with `https://github.com/victordov/JsonFormat`.

### Manually

Clone the repository into Sublime's Packages directory (`Preferences → Browse Packages…`). The folder **must be named `JsonFormat`** because the settings menu refers to that path.

```sh
# macOS
cd "$HOME/Library/Application Support/Sublime Text/Packages"
git clone https://github.com/victordov/JsonFormat.git JsonFormat
```

| Platform | Packages directory |
|---|---|
| macOS | `~/Library/Application Support/Sublime Text/Packages` |
| Windows | `%APPDATA%\Sublime Text\Packages` |
| Linux | `~/.config/sublime-text/Packages` |

If you upgraded from Sublime Text 3 and kept its data directory, the path ends in `Sublime Text 3/Packages` instead. Alternatively, clone anywhere and symlink the folder into `Packages/JsonFormat`.

Sublime loads the package immediately; no restart is needed. To update, run `git pull` in the package folder.

## Commands

Open the Command Palette (`Ctrl/Cmd+Shift+P`) and type `JsonFormat:`.

| Command | What it does |
|---|---|
| **JsonFormat: Format** | Re-indent, keeping comments and (at most one) blank line between members |
| **JsonFormat: Format and Sort Keys** | Format and sort object keys recursively; comments move with their member |
| **JsonFormat: Minify** | Write everything on one line (removes comments) |
| **JsonFormat: Convert to Standard JSON** | Strict RFC 8259 output: quoted keys, double quotes, no comments or trailing commas; `0x1F` → `31`, `+1` → `1`, `.5` → `0.5`. `Infinity`/`NaN` are reported as errors. |
| **JsonFormat: Minify to Standard JSON** | Same, on one line |
| **JsonFormat: Convert to JSON5** | Unquote keys that are valid identifiers and add trailing commas |
| **JsonFormat: Validate** | Report errors, duplicate keys, and which JSON5 features the file uses |

With text selected, each selection is formatted on its own and keeps the indentation of its line. Without a selection, the whole file is formatted. If any selection has an error, nothing is changed.

On an error, the status bar shows the message, the location is underlined with an inline annotation, and the caret jumps there. The marks clear when you edit.

## Folding

No key bindings are installed by default. Run **Preferences: JsonFormat Key Bindings** from the Command Palette, which opens the suggested bindings next to your own key bindings, and copy the ones you want. For example, on macOS:

```json
{ "keys": ["super+shift+minus"], "command": "json_format_fold", "args": { "level": 1 },
  "context": [{ "key": "selector", "operator": "equal", "operand": "source.json" }] },
{ "keys": ["super+shift+equals"], "command": "json_format_unfold_all",
  "context": [{ "key": "selector", "operator": "equal", "operand": "source.json" }] },
```

On Windows and Linux use `ctrl` instead of `super`. The `selector` context limits the keys to JSON files.

The Command Palette has **Collapse to Level 1/2/3**, **Collapse All**, **Collapse/Expand at Caret** and **Expand All** (each caption also contains the word "Fold"/"Unfold", so searching for either works).

To open a block, click the arrow in the gutter or the `…` in the text. Inner blocks are folded first, so opening a block should show its children still folded, one level at a time. **Collapse/Expand at Caret** guarantees this: it opens the block on the caret's line and re-folds that block's children.

Folding follows the JSON structure, not indentation, so it also works on badly indented or minified files. Brackets inside strings or comments are never mistaken for structure. Arrays that fit on one line aren't folded. Sublime's built-in `Cmd+K, Cmd+1…9` still works too, but it is based on indentation.

With `always_show_fold_buttons` on (the default), the gutter arrows in JSON files are always visible instead of only when the mouse is over the gutter.

You can bind the toggle command or other levels yourself:

```json
{ "keys": ["super+alt+minus"], "command": "json_format_toggle_fold",
  "context": [{ "key": "selector", "operator": "equal", "operand": "source.json" }] },
{ "keys": ["super+shift+2"], "command": "json_format_fold", "args": { "level": 2 },
  "context": [{ "key": "selector", "operator": "equal", "operand": "source.json" }] }
```

## Settings

`Preferences → Package Settings → JsonFormat → Settings`

| Setting | Default | Values |
|---|---|---|
| `indent` | `"auto"` | `"auto"` (follows the view's `tab_size` / `translate_tabs_to_spaces`), `"tab"`, or 0–16 spaces |
| `sort_keys` | `false` | `false`, `true`, `"ignore-case"` |
| `ensure_ascii` | `false` | `true` escapes all non-ASCII characters as `\uXXXX` |
| `quote_keys` | `"preserve"` | `"preserve"`, `"always"`, `"as-needed"` (JSON5) |
| `quote_style` | `"preserve"` | `"preserve"`, `"double"`, `"single"` (JSON5) |
| `trailing_commas` | `"preserve"` | `"preserve"`, `"never"`, `"always"` (JSON5/JSONC) |
| `keep_comments` | `true` | Minify and standard JSON always remove them |
| `keep_blank_lines` | `true` | Keep single blank lines between members |
| `inline_width` | `0` | When > 0, arrays that fit within this many columns stay on one line: `[1, 2, 3]` |
| `inline_objects` | `false` | Also apply `inline_width` to objects |
| `strict_json` | `false` | Always output standard JSON |
| `final_newline` | `true` | End a fully formatted file with a newline |
| `format_on_save` | `false` | Format before saving… |
| `format_on_save_extensions` | `[".json", ".jsonc", ".json5"]` | …files with these extensions |
| `max_size_kb` | `5120` | Skip files larger than this (`0` = no limit). Formatting runs on the UI thread at about 3 MB/s. |
| `show_annotations` | `true` | Inline error and warning annotations |
| `jump_to_error` | `true` | Move the caret to a syntax error |
| `always_show_fold_buttons` | `true` | Keep the gutter fold arrows visible in JSON files (sets `fade_fold_buttons` to `false` for those views) |

### Per-project settings

Any setting can be overridden for a project or a single view by adding the `json_format.` prefix, for example in a `.sublime-project` file:

```json
{
    "settings": {
        "json_format.format_on_save": true,
        "json_format.indent": 2
    }
}
```

### Custom commands and key bindings

`json_format_format` accepts `options` (any setting above), `minify`, and `whole_file`, so you can bind any variation:

```json
{ "keys": ["ctrl+alt+j"], "command": "json_format_format",
  "args": { "options": { "indent": 2, "sort_keys": true, "inline_width": 100 } },
  "context": [{ "key": "selector", "operator": "equal", "operand": "source.json" }] }
```

## How comments are placed

| Where the comment was | Where it ends up |
|---|---|
| On its own line above a member | Above that member |
| After a value or comma, on the same line | Same line, after the comma |
| Right after `{` / `[` on the same line | Stays there |
| After the last member | Before the closing bracket |
| Between a key and `:`, or between `:` and the value | Moved above the member (the only case where a comment moves) |

When keys are sorted, each comment moves with its member.

## Development

The formatter lives in `core/` and doesn't import `sublime`, so it can be tested with any Python 3.8 or later:

```sh
python3 -m unittest discover -s tests
```

The tests cover error positions, comment placement, every option, and randomized round-trips. Randomly generated documents are formatted in each mode and must parse back with Python's `json` module to the same value, and formatting twice must give the same output.

| File | Role |
|---|---|
| `core/parser.py` | Lexer and parser that builds a tree keeping comments and blank-line hints |
| `core/printer.py` | Writes the tree back as formatted, minified or strict output |
| `json_format.py` | Sublime commands, settings, error annotations, folding, format on save |
| `.python-version` | Makes Sublime run the plugin on Python 3.8 instead of 3.3 |

## Limitations

- Large files (several MB) block the editor briefly while formatting.
- JSON5 identifiers that contain `\uXXXX` escapes (very rare) are reported as errors.
- JsonFormat doesn't provide syntax highlighting for `.json5` files. Use a JSON5 syntax package, or set the syntax to JSON.

## License

[MIT](LICENSE) © 2026 Victor Dovgaliuc
