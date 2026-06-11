"""Google ADK agent: the model decides when to load/switch/reload a dataset
(via the load_dataset tool) and analyzes against whatever it last loaded.

load_dataset fetches the dataset, pushes it into a Vertex CachedContent via
gemini_client.create_cache, and stores ONLY metadata (cache name, file name,
row count) in session state — keeping rows out of the conversation context and
out of memcached (the session is serialized to memcached).

When the dataset is below Vertex's explicit-cache token floor (or the cache
call fails), create_cache returns None and load_dataset falls back to storing
the full dataset inline in session state for the analyze tool to use directly.
"""
import os

# ADK builds its OWN genai.Client for the model and selects the backend (Vertex
# vs the Gemini Developer API) from these env vars — it does NOT inherit the
# vertexai=True we pass in gemini_client. Map our GCP_* config onto the names
# ADK/google-genai read so the reasoning engine runs on Vertex (ADC). Must run
# before ADK constructs the client.
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"
if os.environ.get("GCP_PROJECT_ID"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ["GCP_PROJECT_ID"]
if os.environ.get("GCP_LOCATION"):
    os.environ["GOOGLE_CLOUD_LOCATION"] = os.environ["GCP_LOCATION"]

from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext
from google.genai import types

from . import data_client
from . import gemini_client
from .constants import SHEETGO_API_KEYS

MODEL = "gemini-2.5-flash"

# Per-call HTTP retry for the model (env-tunable). Smooths transient throttling
# (429) and brief unavailability before our run_turn falls back to a friendly
# message. initial_delay is in seconds; attempts is the total number of tries.
RETRY_ATTEMPTS = int(os.environ.get("AGENT_LLM_RETRY_ATTEMPTS", 2))
RETRY_INITIAL_DELAY = float(os.environ.get("AGENT_LLM_RETRY_INITIAL_DELAY", 1))

INSTRUCTION = (
    "You analyze Sheetgo spreadsheet data for the user.\n"
    "- When the user names a dataset or asks to load, switch, or reload one, call "
    "`load_dataset` with that name.\n"
    "- For any question about the loaded data (counts, trends, totals, comparisons, "
    "summaries), call `analyze` with the user's question.\n"
    "- If no dataset is loaded yet and the question requires data, ask the user which "
    "file to use before calling `analyze`.\n"
    "- Reply in professional English with relevant numbers, trends, and insights."
)


def _history_from_events(events, current_invocation_id):
    """Map ADK session events -> google-genai contents (oldest first), skipping
    streaming-partial events, the current invocation, and events with no text."""
    history = []
    for e in (events or []):
        if getattr(e, "partial", False) or e.invocation_id == current_invocation_id:
            continue
        content = getattr(e, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            continue
        text = "".join(p.text for p in parts if getattr(p, "text", None))
        if not text:
            continue
        history.append({"role": content.role, "text": text})
    return history


def analyze(question: str, tool_context: ToolContext) -> str:
    """Answer a question about the dataset that was loaded with `load_dataset`,
    using the conversation so far for context. Call this for every question about
    the data after a dataset has been loaded."""
    active = tool_context.state.get("active_dataset")
    if not active:
        return ("No dataset is loaded yet. Tell me which file to analyze and I'll "
                "load it first.")
    history = _history_from_events(tool_context.session.events, tool_context.invocation_id)
    return gemini_client.analyze(
        question,
        cache_ref=active.get("cache_name"),
        inline_dataset=active.get("inline_dataset"),
        history=history,
    )


def load_dataset(name: str, tool_context: ToolContext) -> dict:
    """Search the user's Google Sheets for `name`, load the first match, cache
    it at Vertex, and store metadata in session state. Call whenever the user
    refers to a dataset by name or asks to load / switch / reload one.
    """
    client_id = tool_context.state.get("client_id")
    api_key = SHEETGO_API_KEYS.get(client_id)
    if not api_key:
        return {"error": "You're not authenticated for Sheetgo. "
                         "Please connect your Sheetgo account."}
    hits = data_client.search_files(name, api_key)
    if not hits:
        return {"error": f"I couldn't find a file named '{name}'."}
    file = hits[0]
    dataset = data_client.fetch_dataset(file["id"], api_key)
    columns = list(dataset[0].keys()) if dataset else []
    cache_name = gemini_client.create_cache(dataset)
    active = {"file_name": file["name"], "row_count": len(dataset), "cache_name": cache_name}
    if cache_name is None:
        # Below the cache token floor (or cache failed) — keep rows for inline analysis.
        active["inline_dataset"] = dataset
    tool_context.state["active_dataset"] = active
    return {"file_name": file["name"], "row_count": len(dataset), "columns": columns}


def build_agent():
    """Construct the ADK LlmAgent. Data flows via the tool's return value — no
    before_model_callback / cached_content (explicit caching is incompatible with
    ADK tool-calling). A per-call HTTP retry handles transient 429/503/504."""
    generate_content_config = types.GenerateContentConfig(
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=RETRY_ATTEMPTS,
                initial_delay=RETRY_INITIAL_DELAY,
                http_status_codes=[429, 503, 504],
            ),
        ),
    )
    return LlmAgent(
        model=MODEL,
        name="sheetgo_data_agent",
        instruction=INSTRUCTION,
        tools=[load_dataset, analyze],
        generate_content_config=generate_content_config,
    )
