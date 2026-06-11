import os
import uuid
import logging
from flask import Flask, request, jsonify, render_template, redirect, send_from_directory, g
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

from sheetgo_agent.agent import message_send_method
from sheetgo_agent.debugbridge import debug_route
from sheetgo_agent import adk_session

load_dotenv()
from . import skills
from .cache import cache
from .auth import verify_token, generate_access_token
from .utils import jsonrpc_error
from .constants import CLIENTS

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# --- Configuration ---
CODE_EXPIRATION = int(os.environ.get('CODE_EXPIRATION', 600))
ACCESS_TOKEN_EXP = int(os.environ.get('ACCESS_TOKEN_EXP', 3600))

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def debug_enabled():
    return cache.get(key='debug-enabled') == '1'

def enable_debug_bridge(enabled):
    cache.set(key='debug-enabled', val='1' if enabled else '0')

def get_cfg(key):
    if key == 'url':
        return os.environ.get('DEBUG_BRIDGE_URL')
    return ""


# --- 1. Discovery Endpoint (The Agent Card) ---
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')


@app.route('/.well-known/agent.json', methods=['GET'])
def get_agent_card():
    return send_from_directory(TEMPLATES_DIR, 'agent_card.json', mimetype='application/json')


# --- 1b. OpenAPI 3.1 Spec for typed skill endpoints ---
def _build_openapi_spec(base_url):
    """Hand-authored OpenAPI 3.1 document describing the typed REST surface
    of each skill. Served so Gemini Enterprise (or any LLM router) can map
    a user prompt into a structured function call."""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Sheetgo AI Execution Agent",
            "version": "1.0.0",
            "description": (
                "Typed skill endpoints for the Sheetgo A2A agent. Each "
                "operation corresponds to a skill declared in the A2A agent "
                "card and accepts a structured JSON body with named "
                "parameters."
            ),
        },
        "servers": [{"url": base_url}],
        "security": [{"sheetgoOAuth": ["default"]}],
        "paths": {
            "/skills/search_workflows": {
                "post": {
                    "operationId": "search_workflows",
                    "summary": "Search Sheetgo workflows by name",
                    "description": (
                        "Search for Sheetgo workflows whose name contains the "
                        "given substring. Returns all workflows when no query "
                        "is provided."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/SearchWorkflowsRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Matching workflows.",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/SearchWorkflowsResponse"}
                                }
                            },
                        },
                        "401": {"description": "Missing or invalid bearer token."},
                    },
                }
            },
            "/skills/get_workflow_context": {
                "post": {
                    "operationId": "get_workflow_context",
                    "summary": "Get details for a specific workflow",
                    "description": (
                        "Look up a Sheetgo workflow by its identifier and "
                        "return its name plus the list of spreadsheets "
                        "connected to it."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/GetWorkflowContextRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Workflow details with connected spreadsheets.",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/GetWorkflowContextResponse"}
                                }
                            },
                        },
                        "400": {"description": "workflow_id missing."},
                        "401": {"description": "Missing or invalid bearer token."},
                        "404": {"description": "Workflow not found."},
                    },
                }
            },
            "/skills/query_spreadsheet_data": {
                "post": {
                    "operationId": "query_spreadsheet_data",
                    "summary": "Retrieve tabular data from a spreadsheet",
                    "description": (
                        "Fetch the column names and rows of data from a "
                        "specific Sheetgo spreadsheet."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/QuerySpreadsheetDataRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Spreadsheet columns and rows.",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/QuerySpreadsheetDataResponse"}
                                }
                            },
                        },
                        "400": {"description": "spreadsheet_id missing."},
                        "401": {"description": "Missing or invalid bearer token."},
                        "404": {"description": "Spreadsheet not found."},
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "sheetgoOAuth": {
                    "type": "oauth2",
                    "flows": {
                        "authorizationCode": {
                            "authorizationUrl": f"{base_url}/auth",
                            "tokenUrl": f"{base_url}/token",
                            "scopes": {
                                "default": "Authenticated access to Sheetgo AI services",
                            },
                        }
                    },
                }
            },
            "schemas": {
                "SearchWorkflowsRequest": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Substring to match against workflow names "
                                "(case-insensitive). Omit or pass an empty "
                                "string to list all workflows."
                            ),
                        }
                    },
                },
                "SearchWorkflowsResponse": {
                    "type": "object",
                    "required": ["workflows", "count"],
                    "properties": {
                        "workflows": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Workflow"},
                        },
                        "count": {"type": "integer", "description": "Number of workflows returned."},
                    },
                },
                "GetWorkflowContextRequest": {
                    "type": "object",
                    "required": ["workflow_id"],
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "Unique identifier of the workflow (e.g., \"wf-001\").",
                        }
                    },
                },
                "GetWorkflowContextResponse": {
                    "type": "object",
                    "required": ["workflow", "spreadsheets"],
                    "properties": {
                        "workflow": {"$ref": "#/components/schemas/Workflow"},
                        "spreadsheets": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Spreadsheet"},
                        },
                    },
                },
                "QuerySpreadsheetDataRequest": {
                    "type": "object",
                    "required": ["spreadsheet_id"],
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Unique identifier of the spreadsheet (e.g., \"ss-001\").",
                        }
                    },
                },
                "QuerySpreadsheetDataResponse": {
                    "type": "object",
                    "required": ["columns", "rows"],
                    "properties": {
                        "columns": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ordered list of column names.",
                        },
                        "rows": {
                            "type": "array",
                            "items": {"type": "array"},
                            "description": "Rows of data; each row is an array aligned with `columns`.",
                        },
                    },
                },
                "Workflow": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                    },
                },
                "Spreadsheet": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                    },
                },
            },
        },
    }


@app.route('/openapi.json', methods=['GET'])
def get_openapi_spec():
    base_url = request.url_root.rstrip('/')
    return jsonify(_build_openapi_spec(base_url))


@app.route('/.well-known/openapi.json', methods=['GET'])
def get_openapi_spec_well_known():
    base_url = request.url_root.rstrip('/')
    return jsonify(_build_openapi_spec(base_url))


# --- 2. OAuth2 Authorization Endpoints ---
@app.route('/auth', methods=['GET'])
def oauth_authorize():
    logger.warning("[sheetgo-agent]: /auth")
    redirect_uri = request.args.get('redirect_uri')
    state = request.args.get('state')
    logger.warning(f"[sheetgo-agent]: /auth: redirect_uri={redirect_uri}")
    return render_template('login.html', redirect_uri=redirect_uri, state=state)


@app.route('/auth/confirm', methods=['POST'])
def oauth_confirm():
    logger.warning("[sheetgo-agent]: /auth/confirm")
    redirect_uri = request.form.get('redirect_uri')
    state = request.form.get('state')

    code = str(uuid.uuid4())
    if not cache.set_code(code, CODE_EXPIRATION):
        logger.exception("memcached set failed for auth code")
        return jsonify({"error": "server_error", "error_description": "Failed to store auth code"}), 500

    return_url = f"{redirect_uri}?code={code}&state={state}"
    logger.warning(f"[sheetgo-agent]: /auth/confirm: redirecting to {return_url}")
    return redirect(return_url)


@app.route('/token', methods=['POST'])
def oauth_token():
    if request.content_type and 'application/json' in request.content_type:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form or {}

    code = data.get('code')
    client_id = data.get('client_id')
    client_secret = data.get('client_secret')
    grant_type = data.get('grant_type')
    refresh_token = data.get('refresh_token')

    logger.warning(f"[sheetgo-agent]: /token: client_id={client_id}, grant_type={grant_type}")

    if grant_type == 'authorization_code':

        SECRET = CLIENTS.get(client_id)
        if not SECRET or client_secret != SECRET:
            logger.warning(f"[sheetgo-agent]: /token: invalid client_secret for client_id={client_id}")
            return jsonify({"error": "invalid_client"}), 401

        cached = cache.get_code(code)
        if not cached:
            logger.warning(f"[sheetgo-agent]: /token: invalid code={code} for client_id={client_id}")
            return jsonify({"error": "invalid_grant"}), 400

        cache.delete_code(code)

        access_token = generate_access_token(client_id=client_id, exp=ACCESS_TOKEN_EXP)
        refresh_token = str(uuid.uuid4())

        cache.set_auth(client_id, client_secret, refresh_token)
        logger.info(f"[sheetgo-agent]: /token: valid code={code} for client_id={client_id}")
        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_EXP  # 3600, For debugging
        })

    elif grant_type == 'refresh_token':
        auth_data = cache.get_auth(client_id)

        if not auth_data or auth_data.get('refresh_token') != refresh_token or client_secret != auth_data.get('client_secret'):
            logger.warning(f"[sheetgo-agent]: /token: invalid refresh_token for client_id={client_id}")
            return jsonify({"error": "invalid_grant"}), 400

        access_token = generate_access_token(client_id=client_id, exp=ACCESS_TOKEN_EXP)
        logger.info(f"[sheetgo-agent]: /token: valid refresh_token for client_id={client_id}")
        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_EXP
        })


# --- 4. JSON-RPC Method Handlers ---

@message_send_method
def handle_message_send(user_text, context_id=None, context_text=None):
    if not context_id:
        context_id = str(uuid.uuid4())
    client_id = g.get("client_id")
    logger.info(f"[sheetgo-agent]: /message_send: user_text={user_text}")
    try:
        message_text = user_text
        if context_text:
            message_text = f"{context_text}\n\n---\nCurrent question:\n{user_text}"
        return adk_session.run_turn(context_id, message_text, client_id)
    except Exception as exc:
        logger.error(f"[sheetgo-agent]: ADK turn failed: {exc}")
        return (
            "Sorry, I couldn't analyze the data right now. "
            "Please try again later."
        )


# --- 5. Main A2A Endpoint (JSON-RPC Dispatcher) ---
@app.route('/', methods=['POST'])
@verify_token
@debug_route(debug_enabled, enable_debug_bridge, get_cfg)
def a2a_dispatch():
    try:
        data = request.get_json(force=True)
    except Exception:
        logger.warning(f"[sheetgo-agent]: /: invalid JSON")
        return jsonrpc_error(None, -32700, "Parse error: Invalid JSON"), 400

    if not isinstance(data, dict):
        logger.warning(f"[sheetgo-agent]: /: invalid JSON object")
        return jsonrpc_error(None, -32600, "Invalid Request: Expected JSON object"), 400

    req_id = data.get("id")
    method = data.get("method")
    params = data.get("params", {})

    if data.get("jsonrpc") != "2.0":
        logger.warning(f"[sheetgo-agent]: /: invalid jsonrpc version")
        return jsonrpc_error(req_id, -32600, "Invalid Request: Missing or wrong jsonrpc version"), 400

    if not method:
        logger.warning(f"[sheetgo-agent]: /: missing method")
        return jsonrpc_error(req_id, -32600, "Invalid Request: Missing method"), 400

    logger.info(f"A2A request: method={method}, id={req_id}")

    handlers = {
        "message/send": handle_message_send,
    }

    handler = handlers.get(method)
    if not handler:
        logger.warning(f"[sheetgo-agent]: /: unknown method {method}")
        return jsonrpc_error(req_id, -32601, f"Method not found: {method}"), 400

    logger.info(f"[sheetgo-agent]: /: calling method {method}")
    return handler(req_id, params)


# --- 6. Typed REST endpoints per skill (described by /openapi.json) ---
@app.route('/skills/search_workflows', methods=['POST'])
@verify_token
def skill_search_workflows():
    data = request.get_json(silent=True) or {}
    query = data.get('query') or None
    logger.info(f"[sheetgo-agent]: /skills/search_workflows: query={query!r}")
    return jsonify(skills.search_workflows(query))


@app.route('/skills/get_workflow_context', methods=['POST'])
@verify_token
def skill_get_workflow_context():
    data = request.get_json(silent=True) or {}
    workflow_id = data.get('workflow_id')
    if not workflow_id:
        return jsonify({"error": "workflow_id is required"}), 400
    logger.info(f"[sheetgo-agent]: /skills/get_workflow_context: workflow_id={workflow_id!r}")
    result = skills.get_workflow_context(workflow_id)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route('/skills/query_spreadsheet_data', methods=['POST'])
@verify_token
def skill_query_spreadsheet_data():
    data = request.get_json(silent=True) or {}
    spreadsheet_id = data.get('spreadsheet_id')
    if not spreadsheet_id:
        return jsonify({"error": "spreadsheet_id is required"}), 400
    logger.info(f"[sheetgo-agent]: /skills/query_spreadsheet_data: spreadsheet_id={spreadsheet_id!r}")
    result = skills.query_spreadsheet_data(spreadsheet_id)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route('/test', methods=['GET', 'POST', 'DELETE', 'PATCH', 'PUT'])
@debug_route(debug_enabled, enable_debug_bridge, get_cfg)
def test_endpoint():
    data = {
        'url': request.url,
        'request_method': request.method,
        'headers': dict(request.headers),
        'body': request.get_data().decode('utf-8'),
    }
    return jsonify(data)

@app.route('/ping', methods=['GET', 'POST'])
@debug_route(debug_enabled, enable_debug_bridge, get_cfg)
def ping():

    status = {
        'debug-bridge': getattr(debug_route, '__enabled__', False),
    }

    return jsonify(status)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
