""""This reply was wrong" (POST /api/chats/{id}/feedback): the chat is saved
only with consent, only by its customer, only for a bot reply; the chat
eval replays the saved customer turns (backend/evals/cases.feedback_cases)."""

from __future__ import annotations

from backend import db
from backend.evals import cases
from tests.test_chat_sessions import _ANSWER, _customer, _start, client  # noqa: F401  (fixture)


def test_a_reported_reply_is_saved_with_consent_and_replayed_by_the_eval(client, tmp_path):  # noqa: F811
    headers = _customer(client)
    chat = _start(client, headers, _ANSWER, issue="how do I restart the agent")
    ai = next(m for m in chat["messages"] if m["role"] == "ai")
    url = f"/api/chats/{chat['session_id']}/feedback"

    assert client.post(url, json={"message_id": ai["message_id"], "consent": False}, headers=headers).status_code == 400
    assert client.post(url, json={"message_id": "MSG-nope", "consent": True}, headers=headers).status_code == 404
    assert client.post(url, json={"message_id": ai["message_id"], "consent": True},
                       headers=_customer(client)).status_code == 403
    res = client.post(url, json={"message_id": ai["message_id"], "consent": True, "note": "wrong steps"},
                      headers=headers)
    assert res.status_code == 200

    conn = db.get_connection()
    try:
        [case] = cases.feedback_cases(conn)
    finally:
        conn.close()
    assert (case.opener, case.script, case.simulate, case.expected) == ("how do I restart the agent", [], False, "any")


def test_an_idle_chat_is_closed_as_abandoned_when_next_opened(client):  # noqa: F811
    from backend import chats

    headers = _customer(client)
    chat = _start(client, headers, _ANSWER, issue="how do I restart the agent")
    url = f"/api/chats/{chat['session_id']}"
    assert client.get(url, headers=headers).json()["status"] == "active"     # not idle yet
    conn = db.get_connection()
    try:
        conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                     ("2020-01-01T00:00:00+00:00", chat["session_id"]))
        conn.commit()
    finally:
        conn.close()
    view = client.get(url, headers=headers).json()
    assert view["status"] == "abandoned" and view["ticket_id"] is None
    assert view["messages"][-1]["content"] == chats.IDLE_CLOSED_MESSAGE.format(minutes=chats.idle_minutes())
    assert client.post(f"{url}/messages", json={"message": "hello?"}, headers=headers).status_code == 400


def test_the_eval_leaves_out_provider_outages_but_not_our_own_bugs(client):  # noqa: F811
    from backend.ai_service import AIError, provider
    from backend.evals import harness

    headers = _customer(client)
    throttled = AIError("down", provider.AIFailure(kind="throttling", operation="answer", code="ThrottlingException"))
    outage = _start(client, headers, throttled, issue="how do I restart the agent")
    bug = _start(client, headers, RuntimeError("our bug"), issue="how do I restart the agent")
    assert outage["ai_error"] and bug["ai_error"]
    assert harness.infra_error(outage["session_id"]) is True
    assert harness.infra_error(bug["session_id"]) is False
