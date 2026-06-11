import os
import jwt
import datetime
import functools
from flask import request, g
from .utils import jsonrpc_error

JWT_SECRET = os.environ['JWT_SECRET']


def now():
    return datetime.datetime.now(datetime.timezone.utc)

def generate_access_token(user_id="sheetgo-user", client_id=None, exp=600):
    """Generates a short-lived access token carrying the OAuth client_id."""
    token_payload = {
        "sub": user_id,
        "scope": "default",
        "client_id": client_id,
        "exp": now() + datetime.timedelta(seconds=exp),
    }
    return encode_jwt(token_payload)


def encode_jwt(payload):
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_jwt(token):
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])


# --- 3. Token Verification ---
def verify_token(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonrpc_error(
                None, -32000, "Unauthorized: Missing Bearer token"
            ), 401

        token = auth_header.split(" ")[1]
        try:
            payload = decode_jwt(token)
        except jwt.ExpiredSignatureError:
            return jsonrpc_error(None, -32000, "Unauthorized: Token expired"), 401
        except jwt.InvalidTokenError:
            return jsonrpc_error(None, -32000, "Unauthorized: Invalid token"), 401

        g.client_id = payload.get("client_id")
        return f(*args, **kwargs)

    return wrapper
