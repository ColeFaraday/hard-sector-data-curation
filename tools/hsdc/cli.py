"""The hsdc command line: build, validate, tables.

To add a record, download its YAML archive from hepdata.net, unpack it under data/, list
its tables with `hsdc tables <id> <version>`, write recipes/ins<id>.yaml and run
`hsdc build`. inspire.yaml holds the records' INSPIRE keys, typed in by hand.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import build as builder
from . import check, raw, reader, vocab, yamlio
from .recipe import RecipeError


def _root(args: argparse.Namespace) -> Path:
    if not args.root:
        return reader.find_root()
    root = Path(args.root).resolve()
    if not (root / "aliases.yaml").exists():
        raise FileNotFoundError(f"{root} has no aliases.yaml: it is not a data repository")
    return root


def _recipe_paths(root: Path, given: list[str] | None) -> list[Path]:
    if given:
        return [Path(p) for p in given]
    return sorted((root / "recipes").glob("*.yaml"))


def _curated_files(root: Path) -> dict[Path, str]:
    folder = root / "curated"
    return {p: p.read_text(encoding="utf-8") for p in sorted(folder.rglob("*.yaml"))}


def cmd_build(args: argparse.Namespace) -> int:
    root = _root(args)
    paths = _recipe_paths(root, args.recipe)
    result = builder.build_recipes(root, paths)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    wanted = {builder.target(root, item): builder.render(item) for item in result.built}

    if args.check:
        problems = []
        for path, text in wanted.items():
            if not path.exists():
                problems.append(f"missing: {path.relative_to(root)}")
            elif path.read_text(encoding="utf-8") != text:
                problems.append(f"differs: {path.relative_to(root)}")
        if not args.recipe:
            for path in _curated_files(root):
                if path not in wanted:
                    problems.append(f"stale: {path.relative_to(root)}")
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{len(wanted)} datasets, {len(problems)} differences")
        return 1 if problems else 0

    written = 0
    for path, text in wanted.items():
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written += 1
    removed = 0
    if not args.recipe:
        for path in _curated_files(root):
            if path not in wanted:
                path.unlink()
                removed += 1
        for folder in sorted((root / "curated").rglob("*"), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
    print(f"{len(wanted)} datasets from {len(paths)} recipes: {written} written, {removed} removed")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = _root(args)
    files = [Path(p) for p in args.paths] or reader.dataset_files(root)
    problems: list[str] = []
    keys: dict[str, Path] = {}
    for path in files:
        label = path.relative_to(root) if path.is_absolute() and root in path.parents else path
        data = yamlio.load(path)
        found = check.problems(data, root)
        if not found and (root / "curated") in path.resolve().parents:
            expected = vocab.dataset_path(root, data)
            if expected.resolve() != path.resolve():
                found = [f"a generated dataset belongs at {expected.relative_to(root)}"]
        if not found and data["key"] in keys:
            found = [f"key {data['key']} is also in {keys[data['key']]}"]
        keys.setdefault(data.get("key", str(path)), label)
        problems.extend(f"{label}: {p}" for p in found)
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{len(files)} datasets, {len(problems)} problems")
    return 1 if problems else 0


def _short(text: str, width: int = 100) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 3] + "..."


def cmd_tables(args: argparse.Namespace) -> int:
    root = _root(args)
    record = raw.open_record(root, args.inspire_id, args.version)
    print(f"ins{record.inspire_id} v{record.version}  {record.doi}")
    if record.comment:
        print(f"  {_short(record.comment, 300)}")
    for name, table in record.tables.items():
        if args.table and name not in args.table:
            continue
        data = table.data
        print(f"\n{name}  [{table.data_file}]  {table.location}")
        print(f"  {_short(table.description, 400 if args.table else 140)}")
        for variable in data.independent:
            print(f"  x: {variable.name!r} [{variable.units}]  {len(variable.values)} points")
        for column, variable in enumerate(data.dependent):
            qualifiers = ", ".join(f"{q.name}={q.value}" for q in variable.qualifiers)
            labels = sorted(
                {str(e.get("label", "")) for cell in variable.values for e in cell.get("errors", [])}
            )
            print(f"  c{column}: {variable.name!r} [{variable.units}]  {qualifiers}")
            print(f"      errors: {labels}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hsdc", description=__doc__)
    parser.add_argument("--root", help="the data repository (default: this checkout)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="apply the recipes and write curated/")
    p.add_argument("--recipe", action="append", help="build only this recipe (repeatable)")
    p.add_argument("--check", action="store_true", help="build in memory and compare with curated/")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("validate", help="check the format of datasets")
    p.add_argument("paths", nargs="*", help="default: every file in curated/ and manual/")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("tables", help="list the tables of a raw record, for writing a recipe")
    p.add_argument("inspire_id", type=int)
    p.add_argument("version", type=int)
    p.add_argument("table", nargs="*", help="only these tables, with their full description")
    p.set_defaults(func=cmd_tables)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        # `hsdc tables | head`: the reader went away. Silence the flush at exit too.
        sys.stdout = open(os.devnull, "w")
        return 0
    except (
        builder.BuildError,
        raw.RawError,
        vocab.VocabularyError,
        RecipeError,
        FileNotFoundError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
