

# Client ID: secrets.token_hex(24)
# Client Secret: secrets.token_hex(64)
# print(f"\"{secrets.token_hex(24)}\": \"{secrets.token_urlsafe(64)}\",")
CLIENTS = {
    "<CLIENT ID>": "<SECRET>", # Google Hackathon Judges
}

# Sheetgo API key per OAuth client (MVP source of truth; production: DB lookup).
# Fill real sg_… keys per client_id (mirrors the client_ids in CLIENTS above).
SHEETGO_API_KEYS = {
    "<CLIENT ID>": "<SHEETGO API KEY>"
}
