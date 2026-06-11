from typing import Any, Callable, Dict, List, Optional, Union
import requests
from flask import request
import functools
from urllib.parse import urljoin


def debug_route(is_enabled: Callable[[], bool], enable_route: Callable[[bool], None], get_cfg: Callable[[str], Any]):
    def decorator(f):

        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            headers = request.headers
            x_enabled_debug_bridge = headers.get('X-Enabled-Debug-Bridge')
            x_disable_debug_bridge = headers.get('X-Disable-Debug-Bridge')

            debug_bridge_url = get_cfg('url')

            if x_enabled_debug_bridge == 'true':
                enable_route(True)
            elif x_disable_debug_bridge == 'true':
                enable_route(False)
            elif debug_bridge_url and is_enabled():
                with requests.Session() as session:
                    resp = session.request(
                        request.method,
                        urljoin(debug_bridge_url, request.path.lstrip("/")),
                        data=request.get_data(),
                        params=request.args,
                        headers={k: v for k, v in request.headers if k.lower() != 'host'}
                    )
                    return resp.content, resp.status_code

            return f(*args, **kwargs)

        return wrapper

    return decorator
