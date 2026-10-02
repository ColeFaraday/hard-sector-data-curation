"""The hsdc command line: build, validate, schema, tables, check-updates, fetch, fill-inspire."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from . import build as builder
from . import raw, reader, registry as reg, schema, updates, yamlio
from .recipe import RecipeError, load_recipe


def _root(args: argparse.Namespace) -> Path:
    if not args.root:
        return reader.find_root()
    root = Path(args.root).resolve()
    if not (root / "observables.yaml").exists():
        raise FileNotFoundError(f"{root} has no observables.yaml: it is not a data repository")
    return root


def _recipe_paths(root: Path, given: list[str] | None) -> list[Path]:
    if given:
        return [Path(p) for p in given]
    return sorted((root / "recipes").glob("*.yaml"))


def _curated_files(root: Path) -> dict[Path, str]:
    folder = root / "curated"
    return {p: p.read_text(encoding="utf-8") for p in sorted(folder.rglob("*.yaml"))}


def cmd_schema(args: argparse.Namespace) -> int:
    root = _root(args)
    path = schema.write_schema(reg.load(root))
    print(f"wrote {path.relative_to(root)}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    root = _root(args)
    registry = reg.load(root)
    paths = _recipe_paths(root, args.recipe)

    if args.update:
        status = _update_pins(root, paths, args.dry_run)
        if status:
            return status

    result = builder.build_recipes(root, registry, paths)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    wanted = {builder.target(root, item): builder.render(item) for item in result.built}
    schema_text = schema.schema_text(registry)
    schema_path = root / "schema" / "dataset.schema.json"

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
        if not schema_path.exists() or schema_path.read_text(encoding="utf-8") != schema_text:
            problems.append("differs: schema/dataset.schema.json")
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
    schema.write_schema(registry)
    print(f"{len(wanted)} datasets from {len(paths)} recipes: {written} written, {removed} removed")
    return 0


def _update_pins(root: Path, paths: list[Path], dry_run: bool) -> int:
    changed = 0
    for path in paths:
        recipe = load_recipe(path)
        newest = updates.latest_version(recipe.inspire_id)
        if newest <= recipe.version:
            continue
        print(f"ins{recipe.inspire_id}: v{recipe.version} -> v{newest}  ({path.name})")
        changed += 1
        if dry_run:
            continue
        current = raw.find_record_directory(root, recipe.inspire_id, recipe.version)
        updates.download_record(recipe.inspire_id, newest, current.parent)
        updates.repin(path, newest)
    if not changed:
        print("every pinned record is the newest version")
    return 0


def cmd_check_updates(args: argparse.Namespace) -> int:
    root = _root(args)
    newer = 0
    for path in _recipe_paths(root, None):
        recipe = load_recipe(path)
        newest = updates.latest_version(recipe.inspire_id)
        marker = "NEWER" if newest > recipe.version else "ok"
        newer += newest > recipe.version
        print(f"ins{recipe.inspire_id}  pinned v{recipe.version}  newest v{newest}  {marker}  {path.name}")
    return 1 if newer else 0


def cmd_fetch(args: argparse.Namespace) -> int:
    root = _root(args)
    dest = Path(args.dest)
    if not dest.is_absolute():
        dest = root / dest
    target = updates.download_record(args.inspire_id, args.version, dest)
    print(f"unpacked {target.relative_to(root)}")
    return 0


def cmd_fill_inspire(args: argparse.Namespace) -> int:
    root = _root(args)
    path = root / "inspire.yaml"
    known: dict[Any, Any] = (yamlio.load(path) if path.exists() else None) or {}
    for recipe_path in _recipe_paths(root, None):
        recipe = load_recipe(recipe_path)
        if recipe.inspire_id in known and not args.refresh:
            continue
        known[recipe.inspire_id] = updates.inspire_info(recipe.inspire_id)
        print(f"ins{recipe.inspire_id}: {known[recipe.inspire_id].get('texkey')}")
    lines = [
        "# INSPIRE keys of the pinned records, filled by `hsdc fill-inspire`; the build reads",
        "# this file and never the network.",
    ]
    for key in sorted(known):
        info = known[key]
        lines.append(f"{key}: {yamlio.flow(info)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = _root(args)
    registry = reg.load(root)
    document = schema.dataset_schema(registry)
    files = [Path(p) for p in args.paths] or reader.dataset_files(root)
    problems: list[str] = []
    keys: dict[str, Path] = {}
    for path in files:
        label = path.relative_to(root) if path.is_absolute() and root in path.parents else path
        data = yamlio.load(path)
        found = schema.schema_problems(data, document)
        if not found:
            found = schema.semantic_problems(data, registry)
        if not found and (root / "curated") in path.resolve().parents:
            expected = reg.dataset_path(root, data)
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
    p.add_argument("--update", action="store_true", help="first move the pins to the newest versions")
    p.add_argument("--dry-run", action="store_true", help="with --update, only report")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("validate", help="check datasets against the schema")
    p.add_argument("paths", nargs="*", help="default: every file in curated/ and manual/")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("schema", help="write schema/dataset.schema.json")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("tables", help="list the tables of a raw record, for writing a recipe")
    p.add_argument("inspire_id", type=int)
    p.add_argument("version", type=int)
    p.add_argument("table", nargs="*", help="only these tables, with their full description")
    p.set_defaults(func=cmd_tables)

    p = sub.add_parser("check-updates", help="report records with a newer HEPData version")
    p.set_defaults(func=cmd_check_updates)

    p = sub.add_parser("fetch", help="download and unpack one HEPData record")
    p.add_argument("inspire_id", type=int)
    p.add_argument("version", type=int)
    p.add_argument("dest", help="folder under data/, such as data/5020/hadron/pt_ch_atlas")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("fill-inspire", help="fetch the INSPIRE keys of the pinned records")
    p.add_argument("--refresh", action="store_true", help="fetch the ones already known again")
    p.set_defaults(func=cmd_fill_inspire)

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
        reg.RegistryError,
        RecipeError,
        updates.UpdateError,
        FileNotFoundError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
