"""
A2A Agent Test Suite
====================

Automated tests for the Sheetgo A2A agent. Runs against the Flask test
client by default (no server needed), or against a live deployment.

Usage:
    # Local (no server needed):
    pytest sheetgo_agent/test_agent.py -v

    # Against a deployed instance:
    pytest sheetgo_agent/test_agent.py -v --base-url https://sheetgo-agent-xyz.run.app

    # Or via environment variable:
    AGENT_BASE_URL=https://deployed.run.app pytest sheetgo_agent/test_agent.py -v

Requires: pip install pytest
"""

import os
import uuid
import pytest
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]


# ---------------------------------------------------------------------------
# HTTP Client Abstraction
# ---------------------------------------------------------------------------


class Response:
    """Normalized HTTP response for both Flask test client and requests."""

    def __init__(self, status_code, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}

    def json(self):
        return self._json

    @property
    def location(self):
        return self.headers.get("Location")


class AgentTestClient:
    """Unified HTTP client that works with Flask test client or a live server."""

    def __init__(self, flask_client=None, base_url=None):
        self._flask = flask_client
        self._base_url = base_url
        if base_url:
            import requests as _req

            self._session = _req.Session()

    def _from_flask(self, resp):
        return Response(
            resp.status_code, resp.get_json(silent=True), dict(resp.headers)
        )

    def _from_requests(self, resp):
        try:
            data = resp.json()
        except Exception:
            data = None
        return Response(resp.status_code, data, dict(resp.headers))

    def get(self, path):
        if self._flask:
            return self._from_flask(self._flask.get(path))
        return self._from_requests(self._session.get(f"{self._base_url}{path}"))

    def post_form(self, path, data, follow_redirects=False):
        if self._flask:
            return self._from_flask(
                self._flask.post(
                    path, data=data, follow_redirects=follow_redirects
                )
            )
        return self._from_requests(
            self._session.post(
                f"{self._base_url}{path}",
                data=data,
                allow_redirects=follow_redirects,
            )
        )

    def post_json(self, path, data, headers=None):
        if self._flask:
            return self._from_flask(
                self._flask.post(path, json=data, headers=headers)
            )
        return self._from_requests(
            self._session.post(
                f"{self._base_url}{path}", json=data, headers=headers
            )
        )

    def jsonrpc(self, method, params, headers=None, req_id=None):
        """Send a JSON-RPC 2.0 request to the A2A endpoint (POST /)."""
        payload = {
            "jsonrpc": "2.0",
            "id": req_id or str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        return self.post_json("/", payload, headers=headers)

    def obtain_access_token(self):
        """Run the full OAuth flow programmatically, return an access token."""
        redirect_uri = "http://localhost:9999/callback"
        state = str(uuid.uuid4())

        # Simulate consent form submission
        resp = self.post_form(
            "/auth/confirm",
            data={"redirect_uri": redirect_uri, "state": state},
        )
        assert resp.status_code == 302, f"Expected redirect, got {resp.status_code}"

        # Extract auth code from redirect URL
        parsed = urlparse(resp.location)
        params = parse_qs(parsed.query)
        code = params["code"][0]
        assert params["state"][0] == state

        # Exchange code for token
        resp = self.post_form(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": redirect_uri,
            },
        )
        assert resp.status_code == 200, f"Token exchange failed: {resp.json()}"

        token_data = resp.json()
        assert "access_token" in token_data
        assert token_data["token_type"] == "Bearer"
        return token_data["access_token"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(request):
    """Provide an AgentTestClient — local (Flask test client) or remote."""
    base_url = os.environ.get("AGENT_BASE_URL") or request.config.getoption(
        "--base-url", default=None
    )

    if base_url:
        yield AgentTestClient(base_url=base_url)
    else:
        from sheetgo_agent.app import app as flask_app, auth_codes, tasks

        flask_app.config["TESTING"] = True
        auth_codes.clear()
        tasks.clear()
        yield AgentTestClient(flask_client=flask_app.test_client())


@pytest.fixture
def access_token(client):
    """A valid access token obtained through the full OAuth flow."""
    return client.obtain_access_token()


@pytest.fixture
def auth_headers(access_token):
    """Authorization headers with a valid Bearer token."""
    return {"Authorization": f"Bearer {access_token}"}


# ---------------------------------------------------------------------------
# Tests: Agent Card Discovery
# ---------------------------------------------------------------------------


class TestAgentCard:
    def test_returns_valid_json(self, client):
        resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200
        assert resp.json() is not None

    def test_required_fields(self, client):
        card = client.get("/.well-known/agent.json").json()
        for field in ("name", "description", "url", "version", "protocolVersion"):
            assert field in card, f"Missing required field: {field}"

    def test_capabilities_structure(self, client):
        card = client.get("/.well-known/agent.json").json()
        caps = card["capabilities"]
        assert isinstance(caps.get("streaming"), bool)
        assert isinstance(caps.get("pushNotifications"), bool)
        assert isinstance(caps.get("stateTransitionHistory"), bool)

    def test_default_modes_are_mime_types(self, client):
        card = client.get("/.well-known/agent.json").json()
        for mode in card["defaultInputModes"]:
            assert "/" in mode, f"Expected MIME type, got: {mode}"
        for mode in card["defaultOutputModes"]:
            assert "/" in mode, f"Expected MIME type, got: {mode}"

    def test_skills_structure(self, client):
        card = client.get("/.well-known/agent.json").json()
        skills = card["skills"]
        assert len(skills) >= 1
        skill = skills[0]
        for field in ("id", "name", "description", "tags"):
            assert field in skill, f"Skill missing field: {field}"
        assert isinstance(skill["tags"], list)
        assert len(skill["tags"]) >= 1

    def test_security_scheme_declared(self, client):
        card = client.get("/.well-known/agent.json").json()
        assert "securitySchemes" in card
        assert "security" in card
        assert len(card["securitySchemes"]) >= 1
        # security array references a declared scheme
        for entry in card["security"]:
            for scheme_name in entry:
                assert scheme_name in card["securitySchemes"]

    def test_oauth_urls_present(self, client):
        card = client.get("/.well-known/agent.json").json()
        scheme = list(card["securitySchemes"].values())[0]
        assert scheme["type"] == "oauth2"
        flow = scheme["flows"]["authorizationCode"]
        assert "authorizationUrl" in flow
        assert "tokenUrl" in flow
        assert "scopes" in flow


# ---------------------------------------------------------------------------
# Tests: OAuth Flow
# ---------------------------------------------------------------------------


class TestOAuth:
    def test_auth_page_loads(self, client):
        resp = client.get("/auth?redirect_uri=http://example.com&state=abc")
        assert resp.status_code == 200

    def test_confirm_redirects_with_code_and_state(self, client):
        resp = client.post_form(
            "/auth/confirm",
            data={"redirect_uri": "http://example.com/cb", "state": "xyz"},
        )
        assert resp.status_code == 302
        parsed = urlparse(resp.location)
        params = parse_qs(parsed.query)
        assert "code" in params
        assert params["state"][0] == "xyz"
        assert parsed.scheme == "http"
        assert parsed.netloc == "example.com"

    def test_token_exchange_form_encoded(self, client):
        # Get a code
        resp = client.post_form(
            "/auth/confirm",
            data={"redirect_uri": "http://example.com/cb", "state": "s1"},
        )
        code = parse_qs(urlparse(resp.location).query)["code"][0]

        # Exchange for token
        resp = client.post_form(
            "/token",
            data={
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
        assert resp.status_code == 200
        token_data = resp.json()
        assert "access_token" in token_data
        assert token_data["token_type"] == "Bearer"
        assert token_data["expires_in"] == 3600

    def test_token_exchange_json_body(self, client):
        resp = client.post_form(
            "/auth/confirm",
            data={"redirect_uri": "http://example.com/cb", "state": "s2"},
        )
        code = parse_qs(urlparse(resp.location).query)["code"][0]

        resp = client.post_json(
            "/token",
            data={
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_token_invalid_client_credentials(self, client):
        resp = client.post_form(
            "/auth/confirm",
            data={"redirect_uri": "http://example.com/cb", "state": "s3"},
        )
        code = parse_qs(urlparse(resp.location).query)["code"][0]

        resp = client.post_form(
            "/token",
            data={
                "code": code,
                "client_id": "wrong-id",
                "client_secret": "wrong-secret",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_client"

    def test_token_invalid_code(self, client):
        resp = client.post_form(
            "/token",
            data={
                "code": "nonexistent-code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"

    def test_auth_code_is_single_use(self, client):
        resp = client.post_form(
            "/auth/confirm",
            data={"redirect_uri": "http://example.com/cb", "state": "s4"},
        )
        code = parse_qs(urlparse(resp.location).query)["code"][0]

        # First use succeeds
        resp = client.post_form(
            "/token",
            data={
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
        assert resp.status_code == 200

        # Second use fails
        resp = client.post_form(
            "/token",
            data={
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"


# ---------------------------------------------------------------------------
# Tests: Authentication on the A2A endpoint
# ---------------------------------------------------------------------------


class TestA2AAuth:
    def test_no_token_returns_401(self, client):
        resp = client.jsonrpc("message/send", {})
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        resp = client.jsonrpc(
            "message/send",
            {},
            headers={"Authorization": "Bearer invalid.token.value"},
        )
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client):
        import jwt as pyjwt
        import datetime

        expired = pyjwt.encode(
            {
                "sub": "user",
                "exp": datetime.datetime.utcnow() - datetime.timedelta(hours=1),
            },
            os.environ["JWT_SECRET"],
            algorithm="HS256",
        )
        resp = client.jsonrpc(
            "message/send",
            {},
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401

    def test_auth_error_is_jsonrpc_format(self, client):
        resp = client.jsonrpc("message/send", {})
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert "error" in body
        assert body["error"]["code"] == -32000


# ---------------------------------------------------------------------------
# Tests: JSON-RPC Validation
# ---------------------------------------------------------------------------


class TestJsonRpcValidation:
    def test_missing_jsonrpc_version(self, client, auth_headers):
        resp = client.post_json(
            "/",
            {"id": "1", "method": "message/send", "params": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == -32600

    def test_wrong_jsonrpc_version(self, client, auth_headers):
        resp = client.post_json(
            "/",
            {"jsonrpc": "1.0", "id": "1", "method": "message/send", "params": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == -32600

    def test_missing_method(self, client, auth_headers):
        resp = client.post_json(
            "/",
            {"jsonrpc": "2.0", "id": "1", "params": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == -32600

    def test_unknown_method(self, client, auth_headers):
        resp = client.jsonrpc("nonexistent/method", {}, headers=auth_headers)
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == -32601
        assert "nonexistent/method" in body["error"]["message"]

    def test_response_echoes_request_id(self, client, auth_headers):
        resp = client.jsonrpc(
            "message/send",
            {"message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]}},
            headers=auth_headers,
            req_id="my-req-42",
        )
        assert resp.json()["id"] == "my-req-42"


# ---------------------------------------------------------------------------
# Tests: message/send
# ---------------------------------------------------------------------------


class TestMessageSend:
    def test_returns_completed_task(self, client, auth_headers):
        resp = client.jsonrpc(
            "message/send",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Configure Sheetgo"}],
                    "taskId": str(uuid.uuid4()),
                }
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert "result" in body
        assert body["result"]["status"]["state"] == "completed"

    def test_task_structure(self, client, auth_headers):
        task_id = str(uuid.uuid4())
        ctx_id = str(uuid.uuid4())
        resp = client.jsonrpc(
            "message/send",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Configure"}],
                    "taskId": task_id,
                    "contextId": ctx_id,
                }
            },
            headers=auth_headers,
        )
        task = resp.json()["result"]

        # IDs match what was sent
        assert task["id"] == task_id
        assert task["contextId"] == ctx_id

        # Status structure
        assert task["status"]["state"] == "completed"
        assert "timestamp" in task["status"]
        assert task["status"]["message"]["role"] == "agent"
        parts = task["status"]["message"]["parts"]
        assert len(parts) >= 1
        assert parts[0]["type"] == "text"
        assert len(parts[0]["text"]) > 0

    def test_artifacts_structure(self, client, auth_headers):
        resp = client.jsonrpc(
            "message/send",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Configure"}],
                    "taskId": str(uuid.uuid4()),
                }
            },
            headers=auth_headers,
        )
        task = resp.json()["result"]

        assert "artifacts" in task
        assert len(task["artifacts"]) >= 1
        artifact = task["artifacts"][0]
        assert "artifactId" in artifact
        assert "name" in artifact
        assert len(artifact["parts"]) >= 1
        part = artifact["parts"][0]
        assert part["type"] == "data"
        assert "mimeType" in part
        assert "data" in part

    def test_auto_generates_ids_when_omitted(self, client, auth_headers):
        resp = client.jsonrpc(
            "message/send",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Configure"}],
                }
            },
            headers=auth_headers,
        )
        task = resp.json()["result"]
        assert task["id"]  # auto-generated
        assert task["contextId"]  # auto-generated


# ---------------------------------------------------------------------------
# Tests: tasks/get
# ---------------------------------------------------------------------------


class TestTasksGet:
    def test_retrieve_existing_task(self, client, auth_headers):
        task_id = str(uuid.uuid4())

        # Create the task
        client.jsonrpc(
            "message/send",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Configure"}],
                    "taskId": task_id,
                }
            },
            headers=auth_headers,
        )

        # Retrieve it
        resp = client.jsonrpc("tasks/get", {"id": task_id}, headers=auth_headers)
        assert resp.status_code == 200
        task = resp.json()["result"]
        assert task["id"] == task_id
        assert task["status"]["state"] == "completed"

    def test_returns_same_data_as_message_send(self, client, auth_headers):
        task_id = str(uuid.uuid4())

        send_resp = client.jsonrpc(
            "message/send",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Configure"}],
                    "taskId": task_id,
                }
            },
            headers=auth_headers,
        )

        get_resp = client.jsonrpc(
            "tasks/get", {"id": task_id}, headers=auth_headers
        )

        assert send_resp.json()["result"] == get_resp.json()["result"]

    def test_not_found(self, client, auth_headers):
        resp = client.jsonrpc(
            "tasks/get", {"id": "nonexistent-id"}, headers=auth_headers
        )
        assert resp.status_code == 404
        error = resp.json()["error"]
        assert error["code"] == -32001
        assert "taskId" in error.get("data", {})


# ---------------------------------------------------------------------------
# Tests: tasks/cancel
# ---------------------------------------------------------------------------


class TestTasksCancel:
    def test_completed_task_not_cancelable(self, client, auth_headers):
        task_id = str(uuid.uuid4())
        client.jsonrpc(
            "message/send",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Configure"}],
                    "taskId": task_id,
                }
            },
            headers=auth_headers,
        )

        resp = client.jsonrpc(
            "tasks/cancel", {"id": task_id}, headers=auth_headers
        )
        assert resp.status_code == 400
        error = resp.json()["error"]
        assert error["code"] == -32002

    def test_cancel_not_found(self, client, auth_headers):
        resp = client.jsonrpc(
            "tasks/cancel", {"id": "nonexistent-id"}, headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == -32001


# ---------------------------------------------------------------------------
# Tests: Full Integration Flow
# ---------------------------------------------------------------------------


class TestFullFlow:
    def test_discovery_to_execution_round_trip(self, client):
        """End-to-end: discover -> OAuth -> message/send -> tasks/get."""
        # 1. Discover agent
        resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200
        card = resp.json()
        assert card["name"]
        assert len(card["skills"]) >= 1

        # 2. Obtain token via OAuth
        token = client.obtain_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Send a message
        task_id = str(uuid.uuid4())
        resp = client.jsonrpc(
            "message/send",
            {
                "message": {
                    "role": "user",
                    "parts": [
                        {
                            "type": "text",
                            "text": "Configure Sheetgo for AI operations",
                        }
                    ],
                    "taskId": task_id,
                    "contextId": str(uuid.uuid4()),
                }
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["status"]["state"] == "completed"

        # 4. Retrieve the task
        resp = client.jsonrpc("tasks/get", {"id": task_id}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["result"]["id"] == task_id
        assert resp.json()["result"]["status"]["state"] == "completed"
