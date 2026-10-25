"""The /flash.do showId routing table.

The table replaced a 100-line if-chain so that two lanes can add commands without
colliding. These tests keep the table honest:
  * every mapped showId answers HTTP 200 with a protocol body — never a 500;
  * a successful body echoes the requested showId (the client routes on it);
  * a business error body is the `-1\\t-1:<id>` form the client can display;
  * an unknown showId still falls back to the empty envelope.
"""
from __future__ import annotations

import re
from pathlib import Path

from pet_hunter_server import app as A
from pet_hunter_server import create_app
from support import create_local_player, envelope

_ERROR_BODY = re.compile(r"^-1\t-1:\d+$")


def _client(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    return create_app({"TESTING": True, "DATABASE": database}).test_client()


def test_every_routed_show_id_answers_with_a_protocol_body(tmp_path: Path):
    client = _client(tmp_path)
    uid = create_local_player(client, "RouteA")

    broken: list[tuple[str, int, str]] = []
    for show_id in sorted(A._SHOW_HANDLERS, key=int):
        response = client.post(
            "/flash.do", data={"m": "show", "showId": show_id, "uid": uid}
        )
        body = response.get_data(as_text=True)
        # 5xx / HTML error pages are the real failure: they mean the handler raised.
        if response.status_code >= 500:
            broken.append((show_id, response.status_code, body[:80]))
            continue
        if _ERROR_BODY.match(body):
            # 12 号等命令用 -1:100 + HTTP 400 表达"参数不对"，形状仍是客户端能读的。
            continue
        first, _, rest = body.partition("\t")
        if not first.isdigit() or not rest:
            broken.append((show_id, response.status_code, body[:80]))

    assert broken == []


def test_successful_response_echoes_the_requested_show_id(tmp_path: Path):
    client = _client(tmp_path)
    uid = create_local_player(client, "RouteB")

    mismatched: list[tuple[str, str]] = []
    for show_id in sorted(A._SHOW_HANDLERS, key=int):
        response = client.post(
            "/flash.do", data={"m": "show", "showId": show_id, "uid": uid}
        )
        body = response.get_data(as_text=True)
        if _ERROR_BODY.match(body):
            continue
        command, _payload = envelope(response)
        if command != int(show_id):
            mismatched.append((show_id, str(command)))

    assert mismatched == []


def test_unknown_show_id_keeps_the_empty_envelope_fallback(tmp_path: Path):
    client = _client(tmp_path)
    uid = create_local_player(client, "RouteC")

    response = client.post(
        "/flash.do", data={"m": "show", "showId": "9999", "uid": uid}
    )

    assert response.status_code == 200
    command, payload = envelope(response)
    assert command == 9999
    assert payload == {"value": "ok"}


def test_business_errors_are_displayable_protocol_errors(tmp_path: Path):
    """`-1:100` without a tab is the bug fixed on 2026-10-25: the client splits on
    tab first, so a bare `-1:100` becomes payload "null" and the message is lost."""
    client = _client(tmp_path)
    uid = create_local_player(client, "RouteD")

    response = client.post(
        "/flash.do", data={"m": "show", "showId": "12", "uid": uid, "index": "999999"}
    )

    body = response.get_data(as_text=True)
    assert _ERROR_BODY.match(body), body
