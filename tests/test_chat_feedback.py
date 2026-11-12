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
