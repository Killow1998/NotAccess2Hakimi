"""Explicit groups of OpenAI Chat-compatible remote gateways."""
import httpx
from hakimi_proxy.adapters.aistudio import AIStudioAdapter


class RemoteAdapter(AIStudioAdapter):
    def __init__(self, group, proxy=''):
        super().__init__(proxy)
        self.group = group

    @property
    def kind(self):
        return 'remote:' + self.group

    def supports_model(self, model):
        return model.startswith('remote/' + self.group + '/')

    async def forward(self, body, cred, stream, client):
        credential = cred.credential
        model = body['model'].removeprefix('remote/' + self.group + '/')
        if model not in credential.models:
            raise ValueError('Remote model is not configured')
        payload = {**body, 'model': model}
        if stream:
            payload['stream_options'] = {**payload.get('stream_options', {}), 'include_usage': True}
        request = client.build_request('POST', credential.base_url.rstrip('/') + '/chat/completions',
            json=payload, headers={'Authorization': 'Bearer ' + credential.api_key},
            timeout=httpx.Timeout(120, connect=30))
        return await client.send(request, stream=stream, follow_redirects=False)
