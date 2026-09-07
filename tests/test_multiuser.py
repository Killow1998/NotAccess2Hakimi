"""Public API boundaries, streaming leases, persistence, and remote failover."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from starlette.responses import StreamingResponse

from hakimi_proxy.access import AccessStore, KeyPolicy, UserUsageSink, router
from hakimi_proxy.auth import BearerAuthMiddleware
from hakimi_proxy.config import ProxyConfig, RemoteCredential, load_config, save_config
from hakimi_proxy.main import create_app
from hakimi_proxy.metering.models import TokenBreakdown, UsageRecord
from hakimi_proxy.pool import CredentialPool


@pytest.fixture
def app(tmp_path, monkeypatch):
    config = tmp_path / 'config.yaml'
    save_config(ProxyConfig(auth_token='admin-secret', db_path=str(tmp_path / 'usage.db')), config)
    monkeypatch.setenv('HAKIMI_CONFIG', str(config))
    return create_app()


async def call(app, method, path, token='admin-secret', **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://test') as c:
        return await c.request(method, path, headers={'Authorization': 'Bearer ' + token}, **kw)


async def test_user_key_permissions_revocation_and_secret_storage(app):
    created = await call(app, 'POST', '/api/user-keys', json={'name': 'Alice', 'models': ['gemini-only']})
    assert created.status_code == 201
    assert created.headers['cache-control'] == 'no-store'
    key = created.json()
    token = key.pop('api_key')
    assert token not in str(app.state.access.list_keys())
    assert token.encode() not in open(app.state.access.path, 'rb').read()
    for path in ['/api/config', '/api/credentials', '/api/user-keys', '/api/remotes', '/v1/usage']:
        assert (await call(app, 'GET', path, token)).status_code == 403
    assert (await call(app, 'GET', '/v1/models', token)).json()['data'] == []
    r = await call(app, 'POST', '/v1/chat/completions', token, json={'model': 'forbidden'})
    assert r.status_code == 403
    assert app.state.access.active[key['id']] == 0
    assert (await call(app, 'GET', '/v1/me', token)).json()['name'] == 'Alice'
    key['enabled'] = False
    assert (await call(app, 'PUT', '/api/user-keys/' + key.pop('id'), json=key)).status_code == 200
    assert (await call(app, 'GET', '/v1/models', token)).status_code == 401


def test_daily_budget_persists_and_users_are_isolated(tmp_path):
    path = tmp_path / 'access.db'
    store = AccessStore(path)
    alice = store.create(KeyPolicy(name='Alice', requests_per_day=1))
    bob = store.create(KeyPolicy(name='Bob'))
    assert store.admit(alice) is None
    store.release(alice['id'])
    restarted = AccessStore(path)
    assert restarted.admit(alice)[0] == 'day_request_limit'
    assert restarted.admit(bob) is None
    rec = UsageRecord('upstream', 'model', 'remote:g', TokenBreakdown(input=5, output=7, reasoning=2), 0)
    sink = UserUsageSink(SimpleNamespace(record=lambda r: None), store, alice['id'])
    sink.record(rec)
    assert restarted.usage(alice['id'])[0]['output_tokens'] == 7
    assert restarted.usage(bob['id']) == []


async def test_stream_concurrency_is_held_until_cancelled(tmp_path):
    app = FastAPI()
    app.state.access = AccessStore(tmp_path / 'access.db')
    app.add_middleware(BearerAuthMiddleware, auth_token='admin-secret')
    key = app.state.access.create(KeyPolicy(name='Alice', concurrency=1))
    started = asyncio.Event()
    hold = asyncio.Event()

    @app.post('/v1/chat/completions')
    async def stream():
        async def chunks():
            started.set()
            yield b'data: first\n\n'
            await hold.wait()
        return StreamingResponse(chunks())

    task = asyncio.create_task(call(app, 'POST', '/v1/chat/completions', key['api_key']))
    await asyncio.wait_for(started.wait(), 2)
    try:
        r = await call(app, 'POST', '/v1/chat/completions', key['api_key'])
        assert r.status_code == 429 and r.headers['retry-after'] == '1'
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert app.state.access.active[key['id']] == 0


async def test_remote_failover_model_mapping_and_user_metering(app):
    creds = [RemoteCredential(id='a', group='gemini', base_url='https://a.example/v1', api_key='a-key', models=['antigravity/gemini']),
             RemoteCredential(id='b', group='gemini', base_url='https://b.example/v1', api_key='b-key', models=['antigravity/gemini'])]
    app.state.config.remote_credentials = creds
    for c in creds:
        app.state.pool.add_remote(c)
    seen = []
    def handler(req):
        seen.append((req.url.host, req.headers['authorization'], json.loads(req.content)['model']))
        if req.url.host == 'a.example':
            return httpx.Response(429, json={'error': {'message': 'busy'}}, headers={'retry-after': '60'})
        return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 5, 'completion_tokens': 3}})
    app.state.upstream_client_factory = lambda proxy=None: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    key = app.state.access.create(KeyPolicy(name='Alice'))
    model = 'remote/gemini/antigravity/gemini'
    assert model in [m['id'] for m in (await call(app, 'GET', '/v1/models', key['api_key'])).json()['data']]
    r = await call(app, 'POST', '/v1/responses', key['api_key'], json={'model': model, 'input': 'Hi'})
    assert r.status_code == 200, r.text
    assert seen == [('a.example', 'Bearer a-key', 'antigravity/gemini'), ('b.example', 'Bearer b-key', 'antigravity/gemini')]
    assert all(c.in_flight == 0 for c in app.state.pool.all_credentials)
    assert app.state.access.usage(key['id'])[0]['output_tokens'] == 3


def test_remote_config_roundtrip_and_incompatible_group_rejected(tmp_path):
    a = RemoteCredential('a', 'g', 'https://a.example/v1', 'secret', ['m'])
    b = RemoteCredential('b', 'g', 'https://b.example/v1', 'secret2', ['n'])
    config = ProxyConfig(remote_credentials=[a])
    path = tmp_path / 'config.yaml'
    save_config(config, path)
    assert load_config(path).remote_credentials == [a]
    with pytest.raises(ValueError, match='same model'):
        CredentialPool().validate_reconfiguration([], [], [a, b])
    for url in ['http://public.example/v1', 'https://secret@public.example/v1', 'https://public.example/v1?key=secret']:
        with pytest.raises(ValueError):
            RemoteCredential('c', 'g', url, 'key', ['m'])


async def test_remote_api_redacts_key_and_refuses_busy_replacement(app):
    payload = dict(id='upstream', group='g', base_url='https://upstream.example/v1', api_key='private-secret', models=['m'])
    assert (await call(app, 'PUT', '/api/remotes', json=payload)).status_code == 200
    r = await call(app, 'GET', '/api/remotes')
    assert 'private-secret' not in r.text and 'api_key' not in r.text
    pc = await app.state.pool.acquire('remote:g', timeout_seconds=0)
    try:
        changed = {**payload, 'api_key': 'replacement'}
        assert (await call(app, 'PUT', '/api/remotes', json=changed)).status_code == 409
        assert (await call(app, 'DELETE', '/api/remotes/upstream')).status_code == 409
        assert app.state.config.remote_credentials[0].api_key == 'private-secret'
    finally:
        await app.state.pool.release(pc)
    assert (await call(app, 'DELETE', '/api/remotes/upstream')).status_code == 200
    assert app.state.pool.all_credentials == []


def test_minute_window_recovers_without_erasing_daily_budget(tmp_path, monkeypatch):
    clock = [120]
    monkeypatch.setattr('hakimi_proxy.access.time.time', lambda: clock[0])
    store = AccessStore(tmp_path / 'limits.db')
    key = store.create(KeyPolicy(name='User', requests_per_minute=1, requests_per_day=2))
    assert store.admit(key) is None
    store.release(key['id'])
    assert store.admit(key) == ('minute_request_limit', 60)
    clock[0] = 180
    assert store.admit(key) is None
    store.release(key['id'])
    clock[0] = 240
    assert store.admit(key)[0] == 'day_request_limit'
    clock[0] = 86400
    assert store.admit(key) is None


async def test_user_cannot_create_keys_or_write_config(app):
    key = app.state.access.create(KeyPolicy(name='User'))['api_key']
    for method, path in [('POST','/api/user-keys'),('PUT','/api/config'),('PUT','/api/remotes'),('DELETE','/api/remotes/anything')]:
        assert (await call(app, method, path, key, json={})).status_code == 403
    assert (await call(app, 'POST', '/v1/chat/completions', key, json={'model': []})).status_code == 400


def test_user_metering_failure_does_not_block_upstream_aggregate():
    def fail(*args):
        raise sqlite3.OperationalError('injected')
    import sqlite3
    records = []
    sink = UserUsageSink(SimpleNamespace(record=records.append), SimpleNamespace(record=fail), 'u')
    with pytest.raises(sqlite3.OperationalError):
        sink.record('record')
    assert records == ['record']
