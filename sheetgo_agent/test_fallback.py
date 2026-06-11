# sheetgo_agent/test_fallback.py
from unittest.mock import patch

from sheetgo_agent.app import app, handle_message_send


def _params(text, context_id="C1"):
    return {"message": {"messageId": "m1", "contextId": context_id,
                        "parts": [{"kind": "text", "text": text}]}}


def _multipart(prior_q, said, prompt, context_id="C1"):
    return {"message": {"messageId": "m1", "contextId": context_id, "parts": [
        {"kind": "text", "text": prior_q},
        {"kind": "text", "text": "For context:"},
        {"kind": "text", "text": f"[root_agent] said: {said}"},
        {"kind": "text", "text": prompt},
    ]}}


def _text(resp):
    return resp.get_json()["result"]["parts"][0]["text"]


def test_fallback_runs_adk_and_returns_text():
    with patch("sheetgo_agent.app.adk_session.run_turn", return_value="adk answer") as run_turn:
        with app.app_context():
            text = _text(handle_message_send("r1", _params("anything about data")))
    assert text == "adk answer"
    assert run_turn.call_args[0][0] == "C1"            # context_id passed
    assert "anything about data" in run_turn.call_args[0][1]  # prompt in message


def test_fallback_prepends_ge_context_to_adk_message():
    with patch("sheetgo_agent.app.adk_session.run_turn", return_value="ok") as run_turn:
        with app.app_context():
            handle_message_send("r1", _multipart(
                "Prior question?", "prior answer chunk", "Current prompt"))
    sent = run_turn.call_args[0][1]
    assert "Current prompt" in sent
    assert "Earlier conversation context:" in sent     # GE context folded in
    assert "prior answer chunk" in sent


def test_fallback_friendly_error_when_adk_raises():
    with patch("sheetgo_agent.app.adk_session.run_turn", side_effect=RuntimeError("boom")):
        with app.app_context():
            text = _text(handle_message_send("r1", _params("hi")))
    assert "couldn't" in text.lower() or "could not" in text.lower()


def test_fallback_threads_client_id_to_run_turn():
    with patch("sheetgo_agent.app.adk_session.run_turn", return_value="ok") as run_turn:
        with app.app_context():
            from flask import g
            g.client_id = "client-xyz"
            handle_message_send("r1", _params("hi"))
    # run_turn(context_id, message_text, client_id) — client_id is 3rd positional
    assert run_turn.call_args[0][2] == "client-xyz"
