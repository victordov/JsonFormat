# AGENTS.md

Notes for anyone (human or AI agent) working on this repository. User-facing documentation lives in [README.md](README.md); this file covers how the project is built, released and constrained.

## Project

JsonFormat is a Sublime Text 4 package that formats, minifies, converts, validates and folds JSON, JSONC and JSON5 while keeping comments.

- Author and maintainer: Victor Dovgaliuc ([@victordov](https://github.com/victordov))
- Repository: https://github.com/victordov/JsonFormat (public, MIT license)
- Package Control submission: https://github.com/sublimehq/package_control_channel/pull/9590 (opened 2026-10-02; entry in `repository/j.json`, `"sublime_text": ">=4050"`, `"tags": true`)

## Layout

| Path | Role |
|---|---|
| `core/parser.py` | Lexer and parser. Builds a tree that keeps comments, blank-line hints, raw spelling of strings/numbers, and records non-standard JSON features and duplicate-key warnings |
| `core/printer.py` | Writes the tree back: formatted, minified, or strict JSON. Option defaults and validation (`DEFAULTS`, `resolve_options`) |
| `core/__init__.py` | Public API: `parse`, `format_text`, `minify_text`, `containers`, `JsonError` |
| `json_format.py` | Sublime integration: commands, settings lookup, error annotations, folding, format on save |
| `Default.sublime-commands` | Command Palette entries |
| `Default.sublime-keymap` | Commented-out key binding suggestions only (see Constraints) |
| `Main.sublime-menu` | Preferences > Package Settings > JsonFormat |
| `JsonFormat.sublime-settings` | Default settings, with comments explaining each one |
| `messages.json`, `messages/` | Messages Package Control shows on install/upgrade |
| `.python-version` | Contains `3.8`; makes Sublime run the plugin on Python 3.8 instead of 3.3. Must ship with the package |
| `tests/test_core.py` | Unit tests for `core/` |

## Naming

The package was renamed from `JsonFmt` to `JsonFormat`. Everything uses the new name; keep it consistent:

- Folder name in `Packages/` must be exactly `JsonFormat` (menu and palette entries reference `${packages}/JsonFormat/...`).
- Commands: `json_format_<action>` (class `JsonFormat<Action>Command`): `json_format_format`, `json_format_validate`, `json_format_fold`, `json_format_unfold_all`, `json_format_toggle_fold`.
- Palette captions start with `JsonFormat:`. Folding captions contain both "Collapse/Expand" and "Fold/Unfold" so either search word finds them.
- Per-project/view setting overrides use the `json_format.` prefix.

## Constraints

- **No dependencies.** Standard library only, Python 3.8 syntax. No network access, no external processes.
- **`core/` must not import `sublime`**, so it stays testable with plain Python.
- **Never corrupt data.** On any parse error, report it (status bar + inline annotation) and leave the buffer unchanged. Never guess or drop content.
- **Preserve by default.** Formatting changes layout only; string escapes, number spelling, quotes, key quoting and trailing commas stay as written unless an option says otherwise.
- **No default key bindings.** Package Control reviewers reject packages that install key bindings. Add suggestions as comments in `Default.sublime-keymap` and document them in the README.
- **No context menu entries.** Every command must be reachable from the Command Palette.
- Settings and key bindings are opened with `edit_settings` (split view), from both the menu and the palette.
- Keep the source ASCII: write Unicode characters as `\uXXXX` escapes, never as raw invisible characters.
- Files that should not ship in the installed package get `export-ignore` in `.gitattributes` (currently `tests/`, `.gitattributes`, `.gitignore`, `AGENTS.md`, `CLAUDE.md`).
- Requires Sublime Text build 4050+ (region annotations, Python 3.8 plugin host).

## Testing

```sh
python3 -m unittest discover -s tests
```

Add a regression test with every bug fix. The randomized round-trip test checks that output parses back with Python's `json` module to the same value and that formatting is idempotent.

The Sublime layer (`json_format.py`) has no automated tests; check changes manually in Sublime (View > Show Console shows plugin load errors).

## Releasing

Package Control installs from semver git tags on `main`; there is no need to touch the channel repository after the first submission.

1. Make sure tests pass and `README.md` matches the behavior.
2. For user-visible changes, optionally add `messages/<version>.txt` and register it in `messages.json`.
3. Commit, then tag and push:

   ```sh
   git tag -a 1.2.0 -m 1.2.0
   git push origin main --tags
   ```

Version history: `1.0.0` initial release; `1.1.0` removed default key bindings, added "Preferences: JsonFormat Key Bindings".

## Commit conventions

- Author: `Victor Dovgaliuc <victordov@gmail.com>`.
- Imperative subject line; body explains why.
