# sheetgo_agent/gemini_client.py
"""Vertex AI client: dataset caching, multi-turn analysis, filename extraction.

Auth: Application Default Credentials (ADC) via Vertex AI — NOT an API key.
The Cloud Run service account MUST have `roles/aiplatform.user`.
"""
import json
import logging
import os

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
CACHE_TTL = int(os.environ.get("AGENT_CONV_TTL", 3600))

SYSTEM_PROMPT = (
    "You are a data analyst. You are given a dataset (a JSON array of "
    "records) and a user question.\n"
    "- Use the dataset as the sole source of truth.\n"
    "- Answer the user's question directly, in professional English.\n"
    "- Include relevant numbers, trends, and insights when present.\n"
    "- Never invent data that is not present in the dataset."
)

EXTRACT_PROMPT = (
    "From the user's message, extract ONLY the name of the data file/spreadsheet "
    "they want to analyze. Return just the name with no quotes or extra words. "
    "If the message names no file, return an empty string.\n\nMessage: {msg}"
)


def _client():
    return genai.Client(
        vertexai=True,
        project=os.environ["GCP_PROJECT_ID"],
        location=os.environ["GCP_LOCATION"],
    )


def create_cache(dataset):
    """Create a Vertex CachedContent holding the dataset + system prompt.

    Returns the cache resource name, or None when caching is unavailable
    (e.g. the dataset is below the explicit-cache minimum-token floor, or the
    create call fails) — the caller then inlines the dataset instead.
    """
    try:
        # Bind the client to a local: a throwaway `_client().caches...` temporary
        # is GC'd the instant `.caches` is dereferenced, and genai's
        # BaseApiClient.__del__ closes the shared httpx client before the request
        # is sent ("Cannot send a request, as the client has been closed.").
        client = _client()
        cached = client.caches.create(
            model=MODEL,
            config=types.CreateCachedContentConfig(
                contents=json.dumps(dataset),
                system_instruction=SYSTEM_PROMPT,
                ttl=f"{CACHE_TTL}s",
            ),
        )
        return cached.name
    except Exception as exc:
        logger.warning("context cache unavailable (%s); will inline dataset", exc)
        return None


def _build_contents(history, prompt, inline_dataset):
    """Build the generate_content `contents` list from history + new turn."""
    contents = [
        {"role": turn["role"], "parts": [{"text": turn["text"]}]}
        for turn in (history or [])
    ]
    user_text = prompt
    if inline_dataset is not None:
        user_text = (
            f"Dataset (JSON):\n{json.dumps(inline_dataset)}\n\n"
            f"User question:\n{prompt}"
        )
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    return contents


def analyze(prompt, cache_ref=None, inline_dataset=None, history=None):
    """Answer `prompt` over the dataset, in the context of `history`.

    When `cache_ref` is set, the dataset + system prompt live in that Vertex
    cache. Otherwise the dataset is inlined and the system prompt is sent here.
    """
    if cache_ref:
        config = types.GenerateContentConfig(cached_content=cache_ref)
        contents = _build_contents(history, prompt, inline_dataset=None)
    else:
        config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)
        contents = _build_contents(history, prompt, inline_dataset=inline_dataset)

    # Bind to a local so the client isn't GC-closed before the request is sent.
    client = _client()
    response = client.models.generate_content(
        model=MODEL, contents=contents, config=config
    )
    return response.text


def extract_filename_llm(text: str) -> str | None:
    """Ask Gemini to extract the intended filename from free text.

    Returns the name, or None if the model finds none.
    """
    # Bind to a local so the client isn't GC-closed before the request is sent.
    client = _client()
    response = client.models.generate_content(
        model=MODEL, contents=EXTRACT_PROMPT.format(msg=text)
    )
    name = (response.text or "").strip()
    return name or None
