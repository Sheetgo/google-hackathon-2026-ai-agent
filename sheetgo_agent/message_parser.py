"""Parse Gemini Enterprise message/send parts into (current prompt, prior context).

GE flattens a prior conversation into the parts list:
    [prior user question] -> ("For context:" marker -> context chunk) x N -> [current prompt]
The current prompt is the LAST non-marker text part. Earlier non-marker parts are
cleaned into a single 'Earlier conversation context:' blob (Option A): the
'For context:' markers are dropped, consecutive '[agent] said:' chunks (a single
streamed answer split across parts) are concatenated, tool-activity lines are
dropped, and any other text is kept verbatim. The blob is byte-capped.
"""
import os
import re

MARKER = "For context:"
MAX_CONTEXT_BYTES = int(os.environ.get("AGENT_CONTEXT_MAX_BYTES", 200 * 1024))

_SAID = re.compile(r"^\[[^\]]*\]\s*said:\s?", re.IGNORECASE)
_TOOL = re.compile(r"^\[[^\]]*\].*(called tool|tool returned)", re.IGNORECASE)


def _text_parts(parts):
    out = []
    for p in parts:
        if (p.get("kind") or p.get("type")) == "text":
            text = p.get("text", "")
            if not isinstance(text, str):
                continue
            if text.strip() == MARKER:
                continue  # drop "For context:" markers
            out.append(text)
    return out


def _clean_context(parts):
    pieces = []
    answer = []

    def flush():
        if answer:
            pieces.append("".join(answer))
            answer.clear()

    for text in parts:
        said = _SAID.match(text)
        if said:
            answer.append(text[said.end():])  # streamed answer chunk (kept even if it mentions tools)
            continue
        if _TOOL.search(text):
            flush()
            continue  # drop tool-activity lines
        flush()
        pieces.append(text)  # other text (e.g. the prior user question), kept verbatim
    flush()

    body = "\n".join(p for p in pieces if p.strip())
    if not body:
        return None
    blob = f"Earlier conversation context:\n{body}"
    encoded = blob.encode("utf-8")
    if len(encoded) > MAX_CONTEXT_BYTES:
        blob = encoded[:MAX_CONTEXT_BYTES].decode("utf-8", errors="ignore")
    return blob


def parse_parts(parts):
    """Return (prompt, context_text). context_text is None when there is no
    inlined prior context (the direct-conversation case)."""
    texts = _text_parts(parts)
    if not texts:
        return "", None
    prompt = texts[-1]
    context_parts = texts[:-1]
    if not context_parts:
        return prompt, None
    return prompt, _clean_context(context_parts)
