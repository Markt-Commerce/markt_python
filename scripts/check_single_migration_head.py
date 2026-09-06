#!/usr/bin/env python
"""Fail if the migration chain has more than one head.

Two feature branches cut from the same revision and merged independently fork
the chain. Alembic then refuses to run at all:

    Error: Multiple head revisions are present for given argument 'head';
    please specify a specific target revision, '<branchname>@head' to narrow
    to a specific head, or 'heads' for all heads

The deploy job upgrades to `head`, so the first deploy after such a merge dies
before it touches the database -- and it dies on develop, after review, rather
than on the branch that caused it. That is exactly the wrong place to find out.

This reads the migration files directly rather than booting the app: it needs
no database, no settings and no Redis, so it can run in the lint job alongside
flake8 and black instead of needing the integration environment.

    python scripts/check_single_migration_head.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

VERSIONS = pathlib.Path(__file__).resolve().parent.parent / "migrations" / "versions"


def _literal(module: ast.Module, name: str):
    """Value of a module-level assignment, or None if absent/not a literal."""
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                try:
                    return ast.literal_eval(node.value)
                except ValueError:
                    return None
    return None


def main() -> int:
    revisions: dict[str, pathlib.Path] = {}
    parents: set[str] = set()

    for path in sorted(VERSIONS.glob("*.py")):
        module = ast.parse(path.read_text())
        revision = _literal(module, "revision")
        if not revision:
            continue
        revisions[revision] = path

        down = _literal(module, "down_revision")
        if down is None:
            continue
        # A merge revision has a tuple/list of parents; everything else a string.
        if isinstance(down, (tuple, list)):
            parents.update(d for d in down if d)
        else:
            parents.add(down)

    heads = sorted(set(revisions) - parents)

    if len(heads) == 1:
        print(f"Single migration head: {heads[0]}")
        return 0

    if not heads:
        print("No migration head found — the chain is circular or empty.")
        return 1

    print(f"{len(heads)} migration heads, expected 1:\n")
    for head in heads:
        print(f"  {head}  {revisions[head].name}")
    print(
        "\nTwo branches were cut from the same revision and merged separately."
        "\nJoin them with a merge revision, which is structural and changes no"
        "\nschema:"
        f"\n\n    flask db merge -m \"join the branches\" {' '.join(heads)}\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
