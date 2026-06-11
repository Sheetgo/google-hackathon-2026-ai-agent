from flask import jsonify


# --- JSON-RPC Helpers ---

def jsonrpc_response(req_id, result):
    return jsonify({"jsonrpc": "2.0", "id": req_id, "result": result})


def jsonrpc_error(req_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return jsonify({"jsonrpc": "2.0", "id": req_id, "error": error})
