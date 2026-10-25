"""Shared helpers for the test suite.

`app.py` is one large module and so is `test_app.py`; when two lanes add tests at
the same time they used to collide at the end of that single file. New per-topic
test modules import these helpers instead of re-defining them, so each lane can
add its own file (`test_character_growth.py`, ...) and merge without conflicts.

pytest inserts this directory into sys.path (rootdir insertion, no __init__.py),
so `from support import envelope` works from any module in `server/tests`.
"""
from __future__ import annotations

import json


def create_local_player(client, nick: str) -> str:
    """Create a character through the legacy quick-create path and return its uid."""
    created = client.post("/flash.do", data={"m": "autoReg", "nick": nick, "sex": "1"})
    return json.loads(created.get_data(as_text=True).split("\t", 1)[1])["value"]


def envelope(response) -> tuple[int, object]:
    """Split a `command\\tjson` protocol body into (command, payload)."""
    command, payload = response.get_data(as_text=True).split("\t", 1)
    return int(command), json.loads(payload)


# The historical names used inside test_app.py.
_create_local_player = create_local_player
_envelope = envelope
