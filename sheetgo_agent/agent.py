import functools
import uuid
import logging
from .utils import jsonrpc_response, jsonrpc_error
from . import skills
from . import message_parser

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def message_response(message_id, context_id, parts):
    """Build an A2A message envelope with the given parts list."""
    return {
        "messageId": message_id,
        "contextId": context_id,
        "role": "agent",
        "kind": "message",
        "parts": parts,
    }


# ---------------------------------------------------------------------------
# Skill routing
# ---------------------------------------------------------------------------

SKILL_HANDLERS = {
    "search_workflows": lambda data: _handle_search_workflows(data),
    "get_workflow_context": lambda data: _handle_get_workflow_context(data),
    "query_spreadsheet_data": lambda data: _handle_query_spreadsheet_data(data),
}


def _handle_search_workflows(data):
    query = data.get("query")
    results = skills.search_workflows(query)
    count = results.get('count')
    summary = f"Found {count} workflow(s)" + (f" matching '{query}'" if query else "")
    return summary, results


def _handle_get_workflow_context(data):
    workflow_id = data.get("workflow_id")
    result = skills.get_workflow_context(workflow_id)
    if "error" in result:
        return result["error"], result
    name = result["workflow"]["name"]
    count = len(result["spreadsheets"])
    return f"Workflow '{name}' has {count} spreadsheet(s)", result


def _handle_query_spreadsheet_data(data):
    spreadsheet_id = data.get("spreadsheet_id")
    result = skills.query_spreadsheet_data(spreadsheet_id)
    if "error" in result:
        return result["error"], result
    rows = len(result["rows"])
    cols = len(result["columns"])
    return f"Returned {rows} row(s) across {cols} column(s)", result


def _route_by_text(user_text):
    """Fall back to keyword matching in the user's text."""
    text_lower = user_text.lower()

    if "search workflows" in text_lower:
        # Try to extract a query string after the keyword phrase
        idx = text_lower.index("search workflows") + len("search workflows")
        query = user_text[idx:].strip().strip("\"'") or None
        return _handle_search_workflows({"query": query})

    if "workflow context" in text_lower:
        return _handle_search_workflows({"query": None})

    if "query spreadsheet" in text_lower or "spreadsheet data" in text_lower:
        return (
            "Please specify a spreadsheet_id via a data part: "
            '{\"skill\": \"query_spreadsheet_data\", \"spreadsheet_id\": \"...\"}',
            {"error": "No spreadsheet_id provided"},
        )

    return None


def route_skill(skill_data, user_text):
    """Route to a skill handler. Returns (text_summary, data_payload) or None."""
    # 1. Structured data part routing
    if skill_data:
        skill_name = skill_data.get("skill")
        handler = SKILL_HANDLERS.get(skill_name)
        if handler:
            return handler(skill_data)

    # 2. Text keyword fallback
    if user_text:
        return _route_by_text(user_text)

    return None


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def message_send_method(f):
    @functools.wraps(f)
    def wrapper(request_id, params, **kwargs):
        try:
            message = params.get("message", {})
            context_id = message.get("contextId", str(uuid.uuid4()))
            message_id = message.get("messageId", str(uuid.uuid4()))

            # Parse the current prompt + inlined prior context; collect skill data.
            parts = message.get("parts", [])
            prompt, context_text = message_parser.parse_parts(parts)
            skill_data = None
            for part in parts:
                kind = part.get("kind") or part.get("type")
                if kind == "data":
                    data = part.get("data", {})
                    if isinstance(data, dict) and "skill" in data:
                        skill_data = data

            logger.info(f"message/send: messageId={message_id}, text={prompt!r}, skill_data={skill_data!r}")

            # Try skill routing first (on the correct, current prompt)
            skill_result = route_skill(skill_data, prompt)

            if skill_result:
                text_summary, data_payload = skill_result
                response_parts = [
                    {"kind": "text", "text": text_summary},
                    {"kind": "data", "data": data_payload, "mimeType": "application/json"},
                ]
                msg = message_response(message_id, context_id, response_parts)
                return jsonrpc_response(request_id, msg)

            # Fallback to the original handler (context_id + inlined context)
            result = f(prompt, context_id, context_text)
            msg = message_response(message_id, context_id, [{"kind": "text", "text": result}])
            return jsonrpc_response(request_id, msg)

        except Exception as exc:
            logger.error(f"Error processing message[{request_id}]: {exc}")
            return jsonrpc_error(request_id, -32000, f"Internal error: error on processing message [{request_id}]")
    return wrapper
