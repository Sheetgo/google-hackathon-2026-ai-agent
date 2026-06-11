"""Per-contextId conversation state over the shared memcached cache.

State value shape:
    {"file_id": str, "cache_ref": str|None,
     "inline_dataset": list|None, "context_turn": turn|None,
     "history": [ {"role","text"}, ... ]}
History is a sliding window of the most recent AGENT_HISTORY_MAX_TURNS turns.
"""
import os

from .cache import cache

KEY = "ai-agent-conv:{}"
MAX_TURNS = int(os.environ.get("AGENT_HISTORY_MAX_TURNS", 20))
TTL = int(os.environ.get("AGENT_CONV_TTL", 3600))


def _key(context_id):
    return KEY.format(context_id)


def load(context_id):
    """Return the stored state dict, or None if there is no conversation yet."""
    return cache.get(key=_key(context_id))


def save(context_id, file_id, cache_ref, inline_dataset, history, context_turn=None):
    """Persist a fresh conversation state (own history trimmed to the window)."""
    state = {
        "file_id": file_id,
        "cache_ref": cache_ref,
        "inline_dataset": inline_dataset,
        "context_turn": context_turn,
        "history": history[-MAX_TURNS:],
    }
    cache.set(key=_key(context_id), val=state, time=TTL)
    return state


def append(context_id, user_turn, model_turn, context_turn=None):
    """Append a user+model turn to an existing conversation (sliding window).

    When `context_turn` is given it refreshes the stored one (latest wins);
    when omitted the existing context turn is left untouched.
    Returns the updated state, or None if there is no conversation to append to.
    """
    # Read-modify-write; no atomic CAS — acceptable for single-user agent conversations.
    state = load(context_id)
    if not state:
        return None
    state["history"] = (state.get("history", []) + [user_turn, model_turn])[-MAX_TURNS:]
    if context_turn is not None:
        state["context_turn"] = context_turn
    cache.set(key=_key(context_id), val=state, time=TTL)
    return state


def combined_history(state):
    """History to send to Vertex: the single context turn (if any) followed by
    the windowed own-conversation turns."""
    context_turn = state.get("context_turn")
    own = (state.get("history") or [])[-MAX_TURNS:]
    return ([context_turn] if context_turn else []) + own
