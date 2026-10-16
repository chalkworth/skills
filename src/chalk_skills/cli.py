"""The `chalk-skills` command line."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from chalk_skills import __version__
from chalk_skills.errors import ChalkError


def home_dir() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chalk-skills", description=__doc__)
    parser.add_argument("--version", action="version", version=f"chalk-skills {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_root(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument(
            "--root", type=Path, default=Path.cwd(), help="repository root (default: cwd)"
        )
        return p

    with_root(
        sub.add_parser("vendor", help="copy the selected skills and hooks, write the lockfile")
    )
    with_root(sub.add_parser("check", help="fail when the tree differs from the lockfile"))
    with_root(sub.add_parser("lint", help="check a source repository's skills"))
    hooks = with_root(sub.add_parser("hooks", help="rewrite only the hook entries"))
    hooks.add_argument("--global", dest="is_global", action="store_true", help="user-level hooks")
    hooks.add_argument(
        "--adopt",
        action="append",
        default=[],
        metavar="COMMAND",
        help="with --global: remove this foreign Codex entry first (repeatable)",
    )
    install = sub.add_parser("install", help="symlink packs into the user-level skill folders")
    install.add_argument("--global", dest="is_global", action="store_true", required=True)
    install.add_argument("packs", nargs="*", help="pack names")
    install.add_argument(
        "--source", type=Path, required=True, help="a checkout of a skills repository"
    )
    install.add_argument("--replace", action="store_true", help="move existing folders aside")
    install.add_argument(
        "--uninstall", action="store_true", help="remove the links into the source"
    )
    return parser


def run(args: argparse.Namespace) -> int:
    root = args.root.resolve() if hasattr(args, "root") else None
    if args.command == "vendor":
        from chalk_skills.vendor import vendor

        print("\n".join(vendor(root)))
    elif args.command == "check":
        from chalk_skills.check import check

        problems = check(root)
        if problems:
            print("\n".join(problems))
            print(f"{len(problems)} problem(s)")
            return 1
        print("chalk-skills: OK, vendored files match the lockfile")
    elif args.command == "lint":
        from chalk_skills.lint import format_problem, lint

        problems = lint(root)
        for problem in problems:
            print(format_problem(problem))
        return 1 if problems else 0
    elif args.command == "hooks":
        return run_hooks(args, root)
    elif args.command == "install":
        from chalk_skills.install import install_global, uninstall_global

        source = args.source.resolve()
        if args.uninstall:
            lines = uninstall_global(home_dir(), source, args.packs)
        else:
            if not args.packs:
                raise ChalkError("name at least one pack to install")
            lines = install_global(home_dir(), source, args.packs, args.replace)
        print("\n".join(lines))
    return 0


def run_hooks(args: argparse.Namespace, root: Path) -> int:
    if args.is_global:
        from chalk_skills.global_hooks import run_global

        print("\n".join(run_global(home_dir(), args.adopt)))
        return 0
    if args.adopt:
        raise ChalkError("--adopt only works with --global")
    from chalk_skills.vendor import vendor

    print("\n".join(vendor(root, only_hooks=True)))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except ChalkError as error:
        print(f"chalk-skills: {error}", file=sys.stderr)
        return 1
