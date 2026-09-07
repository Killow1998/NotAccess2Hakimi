"""User keys and persistent request budgets for a single worker."""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
import copy

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from hakimi_proxy.config import RemoteCredential


class KeyPolicy(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    models: list[str] = Field(default_factory=list, max_length=100)
    concurrency: int = Field(default=2, ge=1, le=100)
    requests_per_minute: int = Field(default=30, ge=1, le=10000)
    requests_per_day: int = Field(default=1000, ge=1, le=1000000)
    enabled: bool = True


class AccessStore:
    def __init__(self, path):
        self.path = str(path)
        self.active = {}
        Path(path).touch(mode=0o600, exist_ok=True)
        Path(path).chmod(0o600)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS user_keys (
                    id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, policy TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS budgets (
                    key_id TEXT, window TEXT, bucket INTEGER, count INTEGER NOT NULL,
                    PRIMARY KEY(key_id, window));
                CREATE TABLE IF NOT EXISTS user_usage (
                    key_id TEXT, day INTEGER, model TEXT, requests INTEGER DEFAULT 0,
                    input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
                    PRIMARY KEY(key_id, day, model));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, policy):
        key_id, token = secrets.token_hex(12), 'na2h_' + secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('INSERT INTO user_keys VALUES (?, ?, ?)',
                       (key_id, hashlib.sha256(token.encode()).hexdigest(), policy.model_dump_json()))
        return {'id': key_id, **policy.model_dump(), 'api_key': token}

    def lookup(self, token):
        with self.connect() as db:
            row = db.execute('SELECT id, policy FROM user_keys WHERE digest=?',
                             (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return {'id': row['id'], **json.loads(row['policy'])} if row else None

    def list_keys(self):
        with self.connect() as db:
            return [{'id': r['id'], **json.loads(r['policy'])} for r in
                    db.execute('SELECT id, policy FROM user_keys ORDER BY rowid')]

    def update(self, key_id, policy):
        with self.connect() as db:
            return db.execute('UPDATE user_keys SET policy=? WHERE id=?',
                              (policy.model_dump_json(), key_id)).rowcount > 0

    def admit(self, key):
        key_id = key['id']
        if self.active.get(key_id, 0) >= key['concurrency']:
            return 'concurrency_limit', 1
        now = int(time.time())
        windows = [('minute', now // 60, key['requests_per_minute'], 60),
                   ('day', now // 86400, key['requests_per_day'], 86400)]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for window, bucket, limit, seconds in windows:
                row = db.execute('SELECT bucket, count FROM budgets WHERE key_id=? AND window=?',
                                 (key_id, window)).fetchone()
                if row and row['bucket'] == bucket and row['count'] >= limit:
                    return window + '_request_limit', seconds - now % seconds
            for window, bucket, _, _ in windows:
                db.execute('''INSERT INTO budgets VALUES (?, ?, ?, 1)
                    ON CONFLICT(key_id, window) DO UPDATE SET bucket=excluded.bucket,
                    count=CASE WHEN budgets.bucket=excluded.bucket THEN budgets.count+1 ELSE 1 END''',
                           (key_id, window, bucket))
        self.active[key_id] = self.active.get(key_id, 0) + 1

    def release(self, key_id):
        self.active[key_id] = max(0, self.active.get(key_id, 0) - 1)

    def record(self, key_id, rec):
        t = rec.tokens
        with self.connect() as db:
            db.execute('''INSERT INTO user_usage VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(key_id, day, model) DO UPDATE SET requests=requests+1,
                input_tokens=input_tokens+excluded.input_tokens,
                output_tokens=output_tokens+excluded.output_tokens''',
                       (key_id, int(time.time()) // 86400, rec.model,
                        t.input + t.cache_read, t.output))

    def usage(self, key_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT day, model, requests, input_tokens, output_tokens FROM user_usage '
                'WHERE key_id=? ORDER BY day DESC, model', (key_id,))]


class UserUsageSink:
    def __init__(self, store, access, key_id):
        self.store, self.access, self.key_id = store, access, key_id

    def record(self, rec):
        try:
            self.access.record(self.key_id, rec)
        finally:
            self.store.record(rec)


router = APIRouter()


@router.get('/api/user-keys')
async def list_keys(request: Request):
    return {'keys': request.app.state.access.list_keys()}


@router.post('/api/user-keys', status_code=201)
async def create_key(policy: KeyPolicy, request: Request):
    from hakimi_proxy.routes.admin import _secret_transport_allowed
    if not _secret_transport_allowed(request):
        raise HTTPException(403, 'Use HTTPS or loopback to create keys')
    return JSONResponse(request.app.state.access.create(policy), status_code=201, headers={'Cache-Control': 'no-store'})


@router.put('/api/user-keys/{key_id}')
async def update_key(key_id: str, policy: KeyPolicy, request: Request):
    if not request.app.state.access.update(key_id, policy):
        raise HTTPException(404, 'Key not found')
    return {'id': key_id, **policy.model_dump()}


@router.get('/api/user-keys/{key_id}/usage')
async def key_usage(key_id: str, request: Request):
    return {'usage': request.app.state.access.usage(key_id)}


@router.get('/v1/me')
async def own_usage(request: Request):
    key = getattr(request.state, 'user_key', None)
    if not key:
        raise HTTPException(400, 'Use a user API key')
    return {'id': key['id'], 'name': key['name'], 'usage': request.app.state.access.usage(key['id'])}


class RemotePolicy(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    group: str = Field(min_length=1, max_length=40)
    base_url: str
    api_key: str = Field(min_length=1)
    models: list[str] = Field(min_length=1, max_length=100)


@router.get('/api/remotes')
async def list_remotes(request: Request):
    return {'remotes': [dict(id=c.id, group=c.group, base_url=c.base_url, models=c.models)
                        for c in request.app.state.config.remote_credentials]}


@router.put('/api/remotes')
async def save_remote(policy: RemotePolicy, request: Request):
    from hakimi_proxy.routes.admin import _load_and_save, _secret_transport_allowed
    if not _secret_transport_allowed(request):
        raise HTTPException(403, 'Use HTTPS or loopback to configure remotes')
    try:
        credential = RemoteCredential(**policy.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    config = copy.deepcopy(request.app.state.config)
    config.remote_credentials = [c for c in config.remote_credentials if c.id != credential.id] + [credential]
    _load_and_save(request, config)
    return {'id': credential.id}


@router.delete('/api/remotes/{remote_id}')
async def remove_remote(remote_id: str, request: Request):
    from hakimi_proxy.routes.admin import _load_and_save
    config = copy.deepcopy(request.app.state.config)
    config.remote_credentials = [c for c in config.remote_credentials if c.id != remote_id]
    _load_and_save(request, config)
    return {'id': remote_id}
