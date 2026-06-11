# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

"""Developer task runner for AI-Agent.Alexis.

Cross-platform, pure standard library — run it from anywhere with the current
interpreter; it always operates on the repository root (the parent of tools/).

    python tools/make.py clean              # remove all build artifacts + caches
    python tools/make.py build              # build only the wheel into dist/
    python tools/make.py build-dev          # build only the sdist into dist/
    python tools/make.py install            # pip install . (core deps)
    python tools/make.py install -e -x all  # editable install with all extras
    python tools/make.py uninstall          # pip uninstall alexis
    python tools/make.py rebuild            # clean, then build

See docs/BUILD.md for details.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Distribution name (matches [project].name in pyproject.toml) — the name pip
# installs and uninstalls under.
DIST_NAME = "alexis"

# Directories removed wherever they appear in the tree.
_DIR_NAMES = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
# Directory name globs removed wherever they appear (e.g. editable-install metadata).
_DIR_GLOBS = ("*.egg-info",)
# Build-output directories cleaned at the repository root only.
_TOP_DIRS = ("build", "dist")
# Compiled-file globs removed wherever they appear.
_FILE_GLOBS = ("*.pyc", "*.pyo")
# Never descend into these while scanning.
_PRUNE = {".git", ".hg", ".svn"}


def _rm(path: Path) -> None:
    """Delete a file or directory tree, reporting the repo-relative path."""
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = path
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            return
    print(f"  removed {rel}")


def _collect_clean_targets() -> list:
    """Walk the tree once (pruning VCS dirs) and gather everything to delete."""
    targets = []
    for name in _TOP_DIRS:
        p = ROOT / name
        if p.exists():
            targets.append(p)
    for dirpath, dirnames, filenames in os.walk(ROOT, topdown=True):
        base = Path(dirpath)
        # Prune VCS dirs so we never scan (or delete) inside them.
        dirnames[:] = [d for d in dirnames if d not in _PRUNE]
        for d in list(dirnames):
            full = base / d
            if d in _DIR_NAMES or any(full.match(g) for g in _DIR_GLOBS):
                targets.append(full)
                # Don't descend into a directory we're about to remove.
                dirnames.remove(d)
        for f in filenames:
            full = base / f
            if any(full.match(g) for g in _FILE_GLOBS):
                targets.append(full)
    return targets


def clean(_args) -> int:
    """Remove build artifacts, packaging metadata, and Python caches."""
    targets = _collect_clean_targets()
    if not targets:
        print("clean: nothing to remove")
        return 0
    # Deepest paths first so children are gone before their parents.
    for path in sorted(set(targets), key=lambda p: len(p.parts), reverse=True):
        _rm(path)
    print(f"clean: removed {len(set(targets))} item(s)")
    return 0


def _run(cmd: list) -> int:
    """Echo and run a subprocess in the repo root, returning its exit code."""
    print("+ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


def _build(flag: str, args) -> int:
    """Run the PEP 517 build frontend for a single artifact (--wheel/--sdist)."""
    if getattr(args, "clean", False):
        clean(args)
    code = _run([sys.executable, "-m", "build", flag])
    if code != 0:
        print(
            "\nbuild failed. If the 'build' frontend is missing, install it with:\n"
            f"    {sys.executable} -m pip install build",
            file=sys.stderr,
        )
    return code


def build(args) -> int:
    """Build only the wheel into dist/."""
    return _build("--wheel", args)


def build_dev(args) -> int:
    """Build only the source distribution (sdist) into dist/."""
    return _build("--sdist", args)


def install(args) -> int:
    """pip install the project, optionally editable and/or with extras."""
    spec = f".[{args.extras}]" if args.extras else "."
    cmd = [sys.executable, "-m", "pip", "install"]
    if args.editable:
        cmd.append("-e")
    cmd.append(spec)
    return _run(cmd)


def uninstall(args) -> int:
    """pip uninstall the project from the current environment."""
    cmd = [sys.executable, "-m", "pip", "uninstall"]
    if args.yes:
        cmd.append("-y")
    cmd.append(DIST_NAME)
    return _run(cmd)


def rebuild(args) -> int:
    """clean, then build."""
    clean(args)
    return build(args)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="make.py", description="Developer task runner for AI-Agent.Alexis."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_clean = sub.add_parser("clean", help="remove build artifacts and caches")
    p_clean.set_defaults(func=clean)

    p_build = sub.add_parser("build", help="build only the wheel into dist/")
    p_build.add_argument("--clean", action="store_true", help="clean before building")
    p_build.set_defaults(func=build)

    p_build_dev = sub.add_parser(
        "build-dev", help="build only the source distribution (sdist) into dist/"
    )
    p_build_dev.add_argument("--clean", action="store_true", help="clean before building")
    p_build_dev.set_defaults(func=build_dev)

    p_install = sub.add_parser("install", help="pip install the project")
    p_install.add_argument("-e", "--editable", action="store_true", help="editable install")
    p_install.add_argument(
        "-x", "--extras", default=None,
        help="extras to install, e.g. 'all', 'api', 'tui' (comma-separated)",
    )
    p_install.set_defaults(func=install)

    p_uninstall = sub.add_parser("uninstall", help="pip uninstall the project")
    p_uninstall.add_argument(
        "--no-confirm", dest="yes", action="store_false",
        help="prompt before removing (default: uninstall without prompting)",
    )
    p_uninstall.set_defaults(func=uninstall, yes=True)

    p_rebuild = sub.add_parser("rebuild", help="clean, then build")
    p_rebuild.set_defaults(func=rebuild, clean=True)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
