"""The Redis wrapper has to expose every command its callers use.

`external.redis.RedisClient` is a hand-written delegating wrapper, so a
command nobody added is an AttributeError at runtime rather than a name error
at import — and every one of the call sites below wraps its work in a
try/except that logs and moves on. That combination means a missing method is
invisible: the feature simply never happens.

That is exactly what did happen. The wrapper had no list commands at all,
while the offline message queue and the realtime throttler both used them, so
every socket event addressed to a user who was not connected at that instant
was dropped instead of queued, and nothing was ever replayed on reconnect.

This is deliberately a *contract* test rather than a behaviour one: it asserts
the wrapper still covers what the codebase asks of it, which is the thing that
silently drifted.
"""

import ast
import pathlib
import re

from external.redis import RedisClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEARCHED = ("app", "main", "external")

# Calls made on the shared instance, e.g. `redis_client.lpush(...)`.
CALL = re.compile(r"\bredis_client\.(\w+)\s*\(")

# Attributes that are not Redis commands.
NOT_COMMANDS = {"client"}


def _methods():
    return {
        name
        for name in dir(RedisClient)
        if not name.startswith("_") and callable(getattr(RedisClient, name))
    }


def _call_sites():
    used = {}
    for folder in SEARCHED:
        for path in (ROOT / folder).rglob("*.py"):
            for i, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for name in CALL.findall(line):
                    if name not in NOT_COMMANDS:
                        used.setdefault(name, []).append(
                            f"{path.relative_to(ROOT)}:{i}"
                        )
    return used


def test_every_command_the_codebase_calls_exists_on_the_wrapper():
    available = _methods()
    missing = {
        name: sites for name, sites in _call_sites().items() if name not in available
    }
    assert (
        not missing
    ), "RedisClient is missing commands its callers use:\n" + "\n".join(
        f"  {name}() called at {', '.join(sites)}" for name, sites in missing.items()
    )


def test_the_list_commands_the_offline_queue_needs_are_present():
    """Named explicitly, so deleting one fails here rather than in production
    behind a caught exception."""
    for command in ("lpush", "rpush", "lrange", "lpop", "rpop", "llen", "ltrim"):
        assert hasattr(RedisClient, command), f"RedisClient.{command} is missing"


def test_the_wrapper_delegates_rather_than_reimplements():
    """A list command that quietly did something else would be worse than a
    missing one. Each is a one-line pass-through to redis-py."""
    source = (ROOT / "external" / "redis.py").read_text()
    tree = ast.parse(source)
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RedisClient"
    )
    by_name = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}

    for command in ("lpush", "lrange", "llen", "ltrim"):
        fn = by_name[command]
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
        assert len(returns) == 1
        call = returns[0].value
        assert isinstance(call, ast.Call)
        assert call.func.attr == command, (
            f"{command}() should delegate to self.client.{command}, "
            f"not self.client.{call.func.attr}"
        )
