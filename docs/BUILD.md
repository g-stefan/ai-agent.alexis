# Building & Packaging

AI-Agent.Alexis is a standard `src/`-layout package (`src/alexis/`). All bundled
data — the MCP server scripts (`alexis/mcp/`), the web UI HTML (`alexis/ui/`), and
the version file (`alexis/data/version.json`) — ships *inside* the package and is
located at runtime via `importlib.resources`, so a built wheel works exactly like
a source checkout.

A small cross-platform task runner, [`tools/make.py`](../tools/make.py), wraps the
common commands. It is pure standard library and always operates on the repository
root, so you can run it from anywhere with any interpreter.

## Prerequisites

```bash
python -m pip install build      # PEP 517 build frontend (only needed for `build`)
```

## Commands

| Command | What it does |
|---------|--------------|
| `python tools/make.py clean` | Remove all build artifacts and caches |
| `python tools/make.py build` | Build only the wheel into `dist/` |
| `python tools/make.py build-dev` | Build only the source distribution (sdist) into `dist/` |
| `python tools/make.py build --clean` | Clean first, then build |
| `python tools/make.py install` | `pip install .` (core MCP deps) |
| `python tools/make.py install -x all` | Install with all extras (`api`, `tui`) |
| `python tools/make.py install -e -x all` | Editable install with all extras (development) |
| `python tools/make.py uninstall` | `pip uninstall alexis` from the current environment |
| `python tools/make.py rebuild` | `clean` then `build` |

### clean

Removes, anywhere under the repo (VCS directories like `.git` are never touched):

- `build/` and `dist/` (at the repo root)
- `*.egg-info/` (e.g. `src/alexis.egg-info` left by editable installs)
- `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
- `*.pyc` / `*.pyo` compiled files

Everything it deletes is already in `.gitignore`, so tracked files are never affected.

### build / build-dev

Each builds a single artifact into `dist/` via `python -m build`:

- `build` → `alexis-<version>-py3-none-any.whl` — the wheel (what `pip`/`pipx` installs)
- `build-dev` → `alexis-<version>.tar.gz` — the source distribution (sdist)

Add `--clean` to either to wipe artifacts first. To produce both, run `build`
then `build-dev` (or `rebuild` for a clean wheel build). The version comes from
`src/alexis/data/version.json` (see *Versioning* below).

### install

Thin wrapper over `pip install`:

```bash
python tools/make.py install                # pip install .
python tools/make.py install -x api         # pip install ".[api]"
python tools/make.py install -e -x all      # pip install -e ".[all]"
```

### uninstall

Removes the package from the current environment:

```bash
python tools/make.py uninstall              # pip uninstall -y alexis
python tools/make.py uninstall --no-confirm # prompt before removing
```

## Installing a built artifact

```bash
pip install dist/alexis-*.whl               # into the current environment
pipx install dist/alexis-*.whl              # isolated, recommended for a CLI tool
```

After installing, the `alexis` command is on your PATH, and `python -m alexis`
works as well (the agent uses `python -m alexis` internally when it re-spawns
itself as a subagent MCP server).

## Versioning

The version is read from `src/alexis/data/version.json` at build time via the
dynamic-version hook in `pyproject.toml`
(`version = { attr = "alexis.version.__version__" }`) and at runtime for the
startup banner / `--version` / TUI title. Bump it there and every surface updates.

> If you use the `fabricare` release tool, point it at
> `src/alexis/data/version.json` (it previously managed a repo-root `version.json`).

## Clean-room verification

To confirm a wheel is self-contained (carries the MCP servers, web UI, and version
file), install it into a throwaway virtual environment:

```bash
python -m venv .venv-check
.venv-check/Scripts/python -m pip install dist/alexis-*.whl   # Windows
# .venv-check/bin/python -m pip install dist/alexis-*.whl     # POSIX
.venv-check/Scripts/alexis --version
```
