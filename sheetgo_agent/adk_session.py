"""Memcached-backed ADK SessionService and run_turn helper.

SessionService contract
-----------------------
- Key format: ``adk-sess:{app_name}:{user_id}:{session_id}``
- TTL: ``AGENT_CONV_TTL`` env var (default 3600 s).
- Serialisation: ``Session.model_dump_json()`` / ``Session.model_validate_json()``.

All four abstract methods are async (as required by the ABC); ``append_event``
delegates to super (which does in-memory bookkeeping) then persists.
"""

import asyncio
import logging
import os
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

# User-facing messages returned (never raised) when a turn can't be answered.
QUOTA_MESSAGE = (
    "I'm temporarily over the AI service's request limit. "
    "Please try again in a little while."
)
GENERIC_MESSAGE = (
    "Sorry, I couldn't produce an answer right now. "
    "Please try again in a little while."
)


def _is_quota_error(exc: Exception) -> bool:
    """True for Vertex/Gemini 429 RESOURCE_EXHAUSTED (quota / rate limit)."""
    blob = f"{type(exc).__name__} {exc}"
    return "RESOURCE_EXHAUSTED" in blob or "429" in blob or "ResourceExhausted" in blob

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, Session
from google.adk.sessions.base_session_service import ListSessionsResponse
from google.genai import types

from .adk_agent import build_agent
from .cache import cache

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

APP_NAME: str = "sheetgo_data_agent"
USER_ID: str = "sheetgo-user"
KEY_PREFIX: str = "adk-sess"
TTL: int = int(os.environ.get("AGENT_CONV_TTL", 3600))


def _cache_key(app_name: str, user_id: str, session_id: str) -> str:
    return f"{KEY_PREFIX}:{app_name}:{user_id}:{session_id}"


# ---------------------------------------------------------------------------
# MemcachedSessionService
# ---------------------------------------------------------------------------


class MemcachedSessionService(BaseSessionService):
    """ADK ``BaseSessionService`` backed by memcached via the module ``cache``."""

    # -- abstract implementations -------------------------------------------

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        sid = session_id or str(uuid.uuid4())
        session = Session(
            id=sid,
            app_name=app_name,
            user_id=user_id,
            state=state or {},
        )
        self._persist(session)
        return session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config=None,
    ) -> Optional[Session]:
        key = _cache_key(app_name, user_id, session_id)
        raw = cache.get(key=key)
        if raw is None:
            return None
        return Session.model_validate_json(raw)

    async def list_sessions(
        self,
        *,
        app_name: str,
        user_id: Optional[str] = None,
    ) -> ListSessionsResponse:
        # Memcached does not support enumeration; return empty list.
        return ListSessionsResponse(sessions=[])

    async def delete_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> None:
        key = _cache_key(app_name, user_id, session_id)
        try:
            cache.client.delete(key=key)
        except Exception:
            pass

    # -- override append_event to persist after in-memory update --------------

    async def append_event(self, session: Session, event: Event) -> Event:
        result = await super().append_event(session, event)
        self._persist(session)
        return result

    # -- helpers ---------------------------------------------------------------

    def _persist(self, session: Session) -> None:
        key = _cache_key(session.app_name, session.user_id, session.id)
        cache.set(key=key, val=session.model_dump_json(), time=TTL)


# ---------------------------------------------------------------------------
# _ensure_session
# ---------------------------------------------------------------------------


def _ensure_session(svc: MemcachedSessionService, context_id: str, client_id=None) -> None:
    """Get or create a session for (APP_NAME, USER_ID, context_id), seeding the
    client_id into session state so tools can resolve the per-client key."""
    session = asyncio.run(
        svc.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=context_id)
    )
    if session is None:
        asyncio.run(
            svc.create_session(
                app_name=APP_NAME,
                user_id=USER_ID,
                session_id=context_id,
                state={"client_id": client_id},
            )
        )


# ---------------------------------------------------------------------------
# _final_text
# ---------------------------------------------------------------------------


def _final_text(events: list) -> str:
    """Return the concatenated text of the first final-response event."""
    text = ""
    for event in events:
        if event.is_final_response():
            content = getattr(event, "content", None)
            parts = getattr(content, "parts", None) if content else None
            if parts:
                text = "".join(p.text for p in parts if getattr(p, "text", None))
    return text


# ---------------------------------------------------------------------------
# run_turn (public entry point)
# ---------------------------------------------------------------------------


def run_turn(context_id: str, message_text: str, client_id=None) -> str:
    """Drive the ADK agent for one user turn and return the response text.

    Must be called from synchronous code (it uses asyncio.run to drive the
    async session service); do not call from within a running event loop.

    Args:
        context_id: Identifies the ongoing conversation (maps to session_id).
        message_text: The user's message for this turn.
        client_id: Optional client identifier seeded into session state so
            tools can resolve the per-client key.

    Returns:
        The agent's response text. Never raises and never returns "": on a quota
        (429) error it returns QUOTA_MESSAGE, and on any other failure or an empty
        result it returns GENERIC_MESSAGE — so the caller always has an answer.
    """
    service = MemcachedSessionService()
    _ensure_session(service, context_id, client_id)

    runner = Runner(
        app_name=APP_NAME,
        agent=build_agent(),
        session_service=service,
    )
    try:
        events = list(
            runner.run(
                user_id=USER_ID,
                session_id=context_id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part(text=message_text)],
                ),
            )
        )
    except Exception as exc:  # ADK/Vertex errors (quota, model, transport, ...)
        logger.warning("ADK run failed for context %s: %s", context_id, exc)
        return QUOTA_MESSAGE if _is_quota_error(exc) else GENERIC_MESSAGE

    return _final_text(events) or GENERIC_MESSAGE
