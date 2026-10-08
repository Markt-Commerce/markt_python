"""@bp.arguments must be given a Schema, never a dict.

flask-smorest builds its parser from a marshmallow Schema. Hand it a plain
dict of JSON-Schema-looking rules and it does not complain -- it produces a
schema with no fields at all, so every field the client sends comes back as
"Unknown field." and the endpoint 422s on every well-formed request.

That is exactly what happened to the chat discount endpoints: creating an
offer, responding to one and pricing one were all unreachable, while the
service layer underneath them worked fine. Service-level tests could not see
it, and neither could a reader -- the dicts look like a validation spec.

This walks the source instead, because the failure is in how the decorator
was called, not in what it produced.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"


def _argument_decorator_calls():
    """Every `@bp.arguments(...)` in the app, with where it is."""
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "arguments"
                    and decorator.args
                ):
                    yield path, node.name, decorator.lineno, decorator.args[0]


def test_every_route_argument_is_a_schema_not_a_dict():
    offenders = [
        f"{path.relative_to(APP.parent)}:{lineno} ({name})"
        for path, name, lineno, first_arg in _argument_decorator_calls()
        if isinstance(first_arg, ast.Dict)
    ]
    assert not offenders, (
        "@bp.arguments was given a dict instead of a Schema. The endpoint will "
        "reject every field as 'Unknown field.':\n  " + "\n  ".join(offenders)
    )


def test_the_check_can_actually_see_a_dict():
    """A guard that cannot fail is not a guard. This proves the walker spots
    the shape it exists to catch."""
    source = (
        "class V:\n"
        "    @bp.arguments({'x': {'type': 'string'}})\n"
        "    def post(self, data):\n"
        "        pass\n"
    )
    tree = ast.parse(source)
    dicts = [
        d.args[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for d in node.decorator_list
        if isinstance(d, ast.Call)
        and isinstance(d.func, ast.Attribute)
        and d.func.attr == "arguments"
        and d.args
    ]
    assert dicts and isinstance(dicts[0], ast.Dict)


def test_there_are_arguments_decorators_to_check():
    """Guards against the walker silently finding nothing -- a rename or a
    move would otherwise turn this file into a test that always passes."""
    assert len(list(_argument_decorator_calls())) > 20
