import os

MEMCACHED_URL = os.environ.get('MEMCACHED_URL')
LOCAL = os.environ.get('LOCAL') == '1'

if LOCAL:
    MEMCACHED_URL = 'localhost:11211'

from memcache import Client

CODE_PREFIX = "ai-agent-code:{}"
AUTH_DATA = "ai-agent-auth:{}"


class CacheController(object):
    def __init__(self):
        self.client = Client([MEMCACHED_URL], debug=0)

    def get(self, key):
        return self.client.get(key=key)

    def set(self, key, val, time=0):
        return self.client.set(key=key, val=val, time=time)

    def get_code(self, code):
        try:
            return self.client.get(key=CODE_PREFIX.format(code))
        except Exception:
            pass
        return None

    def set_code(self, code, exp) -> bool:
        try:
            self.client.set(key=CODE_PREFIX.format(code), val="1", time=exp)
            return True
        except Exception:
            pass
        return False

    def delete_code(self, code) -> bool:
        try:
            self.client.delete(key=CODE_PREFIX.format(code))
            return True
        except Exception:
            pass
        return False

    def get_auth(self, client_id):
        try:
            return self.client.get(key=AUTH_DATA.format(client_id))
        except Exception:
            pass
        return {}

    def set_auth(self, client_id, client_secret, refresh_token):
        try:
            auth_payload = {
                'client_id': client_id,
                'client_secret': client_secret,
                'refresh_token': refresh_token
            }
            self.client.set(key=AUTH_DATA.format(client_id), val=auth_payload)
            return auth_payload
        except Exception:
            pass
        return {}




cache = CacheController()