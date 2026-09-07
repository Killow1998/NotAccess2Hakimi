"""Bearer token authentication middleware."""

from __future__ import annotations

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

PUBLIC_PATHS = {"/healthz", "/readyz", "/docs", "/openapi.json", "/redoc"}
UI_PATHS = {"/", "/ui", "/favicon.ico"}


class BearerAuthMiddleware:
    """Separate user and administrator keys; hold leases until the stream closes."""

    def __init__(self, app, auth_token: str = "") -> None:
        self.app = app
        self._auth_token = auth_token

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request = Request(scope)
        admin_token = self._auth_token
        path = request.url.path.rstrip("/") or "/"
        if not admin_token and (path.startswith('/api/user-keys') or path.startswith('/api/remotes')):
            response = JSONResponse({'error': {'message': 'Configure an administrator key before sharing access'}}, status_code=403)
            return await response(scope, receive, send)
        if not admin_token or path in PUBLIC_PATHS or path in UI_PATHS:
            return await self.app(scope, receive, send)
        header = request.headers.get('authorization', '')
        token = header[7:] if header.startswith('Bearer ') else ''
        if token and secrets.compare_digest(token.encode(), admin_token.encode()):
            return await self.app(scope, receive, send)
        access = getattr(request.app.state, 'access', None)
        key = access.lookup(token) if access and token else None
        status, message, retry = 401, 'Invalid or missing bearer token', None
        if key and key['enabled']:
            permitted = (request.method == 'GET' and (path == '/v1/models' or
                         path.startswith('/v1/models/') or path == '/v1/me')) or (
                         request.method == 'POST' and path in {'/v1/responses', '/v1/chat/completions'})
            if permitted:
                request.state.user_key = key
                admission = access.admit(key) if request.method == 'POST' else None
                if admission is None:
                    try:
                        return await self.app(scope, receive, send)
                    finally:
                        if request.method == 'POST':
                            access.release(key['id'])
                message, retry = admission
                status = 429
            else:
                status, message = 403, 'Administrator access required'
        response = JSONResponse({'error': {'message': message, 'type': 'auth_error'}},
                                status_code=status, headers={'Retry-After': str(retry)} if retry else None)
        await response(scope, receive, send)
