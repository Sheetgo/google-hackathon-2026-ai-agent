from sheetgo_agent import auth


def test_access_token_carries_client_id():
    tok = auth.generate_access_token(client_id="client-abc")
    assert auth.decode_jwt(tok)["client_id"] == "client-abc"


def test_access_token_client_id_defaults_none():
    tok = auth.generate_access_token()
    assert auth.decode_jwt(tok)["client_id"] is None


def test_verify_token_sets_g_client_id_from_token():
    import flask
    app = flask.Flask(__name__)
    token = auth.generate_access_token(client_id="client-xyz")

    @auth.verify_token
    def handler():
        return "ok"

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        result = handler()
        assert flask.g.client_id == "client-xyz"
        assert result == "ok"


def test_verify_token_missing_bearer_returns_401():
    import flask
    app = flask.Flask(__name__)

    @auth.verify_token
    def handler():
        return "ok"

    with app.test_request_context(headers={}):
        resp = handler()
        # verify_token returns a (body, 401) tuple on missing token
        assert resp[1] == 401
