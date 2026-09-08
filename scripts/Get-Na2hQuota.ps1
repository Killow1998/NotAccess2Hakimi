#requires -Version 7.0
<##
Query VPS account quotas over a short-lived SSH connection. No port forwarding.
Example: ./Get-Na2hQuota.ps1 -SshTarget user@server
Reads the administrator key on the VPS; it never leaves the remote process.
##>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SshTarget,
    [string]$IdentityFile,
    [int]$SshPort = 22,
    [string]$RemoteBaseUrl,
    [string]$RemoteService = 'na2h',
    [string]$RemoteConfigPath
)
$ErrorActionPreference = 'Stop'
if ($SshTarget.StartsWith('-')) { throw 'Invalid SSH target.' }

# Only the fixed program is passed as a command; parameters travel on SSH stdin.
$program = @'
import json, sys, urllib.request, urllib.error
import os, pathlib, subprocess
p = json.load(sys.stdin)
base = (p.get('base') or '').rstrip('/')
try:
    pid = subprocess.run(['systemctl', 'show', '--property=MainPID', '--value', '--', p['service']],
                         capture_output=True, text=True, check=True).stdout.strip()
    if not pid.isdigit() or int(pid) <= 0:
        raise RuntimeError('Service is not running')
    proc = pathlib.Path('/proc') / pid
    args = (proc / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
    env = dict(item.split('=', 1) for item in (proc / 'environ').read_bytes().decode().split('\0') if '=' in item)
    config = p.get('config') or env.get('HAKIMI_CONFIG')
    if not config:
        for i, arg in enumerate(args):
            if arg == '--config' and i + 1 < len(args):
                config = args[i + 1]
            elif arg.startswith('--config='):
                config = arg.split('=', 1)[1]
    config = pathlib.Path(config or '/var/lib/na2h/config.yaml')
    if not config.is_absolute():
        config = proc / 'cwd' / config
    candidates = [pathlib.Path(arg).parent / 'python' for arg in args
                  if os.path.isabs(arg) and pathlib.Path(arg).name in ('hakimi', 'python', 'python3')]
    candidates += [proc / 'cwd' / '.venv' / 'bin' / 'python', pathlib.Path(sys.executable)]
    reader = "import json,sys,yaml;c=yaml.safe_load(open(sys.argv[1]));print(json.dumps({'key':c.get('auth_token',''),'port':c.get('port',12345)}))"
    for python in dict.fromkeys(candidates):
        if not python.is_file():
            continue
        result = subprocess.run([str(python), '-c', reader, str(config)], capture_output=True, text=True)
        if result.returncode == 0:
            settings = json.loads(result.stdout)
            key = settings['key']
            if not base:
                port = settings['port']
                for i, arg in enumerate(args):
                    if arg == '--port' and i + 1 < len(args):
                        port = args[i + 1]
                    elif arg.startswith('--port='):
                        port = arg.split('=', 1)[1]
                base = 'http://127.0.0.1:' + str(int(port))
            if not isinstance(key, str):
                raise ValueError('Invalid auth token')
            break
    else:
        raise RuntimeError('Cannot read service configuration')
except Exception:
    print('无法读取 VPS 上的 NA2H 配置。请使用有权限的 SSH 用户，并检查 RemoteService / RemoteConfigPath。', file=sys.stderr)
    sys.exit(1)
def request(path, refresh=False):
    req = urllib.request.Request(base + path, data=b'{}' if refresh else None,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)
try:
    accounts = request('/api/credentials').get('antigravity', [])
except urllib.error.HTTPError as e:
    print('Cannot list accounts: HTTP ' + str(e.code), file=sys.stderr)
    sys.exit(1)
except Exception:
    print('Cannot connect to NA2H on the VPS. Check RemoteBaseUrl.', file=sys.stderr)
    sys.exit(1)
from urllib.parse import quote
from datetime import datetime, timezone
import math

def reset_countdown(value):
    if not value:
        return '未知'
    try:
        reset = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if reset.tzinfo is None:
            return '未知'
        seconds = (reset - datetime.now(timezone.utc)).total_seconds()
    except (ValueError, TypeError):
        return '未知'
    if seconds <= 0:
        return '已到重置时间'
    if seconds < 60:
        return '不足1分钟'
    minutes = math.ceil(seconds / 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if days:
        parts.append(str(days) + '天')
    if hours:
        parts.append(str(hours) + '小时')
    if minutes:
        parts.append(str(minutes) + '分')
    return ''.join(parts) + '后'

rows = []
for account in accounts:
    row = {'Account': account.get('account') or account['id'], '5h': '未知', '7d': '未知',
           'Reset5h': '', 'Reset7d': '', 'Status': '正常'}
    try:
        snapshot = request('/api/credentials/antigravity/' + quote(account['id'], safe='') + '/quota/refresh', True)
        found = set()
        for group in snapshot.get('groups', []):
            if group.get('kind') != 'gemini':
                continue
            for bucket in group.get('buckets', []):
                label = ' '.join(str(bucket.get(k) or '') for k in ('bucket_id', 'window', 'display_name')).lower()
                window = '5h' if '5h' in label or 'session' in label else '7d' if '7d' in label or 'week' in label else None
                value = bucket.get('remaining_percent')
                if window and isinstance(value, (int, float)) and 0 <= value <= 100:
                    text = str(value) + '%'
                    row[window] = text if window not in found else row[window] + ' / ' + text
                    reset = reset_countdown(bucket.get('reset_time'))
                    row['Reset' + window] = reset if window not in found else row['Reset' + window] + ' / ' + reset
                    found.add(window)
        if len(found) != 2:
            row['Status'] = '上游未返回完整 5h/7d 额度'
    except urllib.error.HTTPError as e:
        row['Status'] = '查询失败 HTTP ' + str(e.code)
    except Exception:
        row['Status'] = '查询失败或超时'
    rows.append(row)
print(json.dumps(rows, ensure_ascii=True))
'@
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($program))
$sshArgs = @('-p', "$SshPort", '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15')
if ($IdentityFile) { $sshArgs += @('-i', $IdentityFile) }
$sshArgs += @($SshTarget, "python3 -c 'import base64;exec(base64.b64decode(""$encoded""))'")
$payload = @{base = $RemoteBaseUrl; service = $RemoteService; config = $RemoteConfigPath} | ConvertTo-Json -Compress
    $result = $payload | & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) { throw 'SSH 或额度查询失败，请检查上方错误。' }
    $rows = @((($result -join "`n") | ConvertFrom-Json))
    Write-Host "Antigravity 账号数：$($rows.Count)"
    $rows | Format-Table Account, '5h', '7d', Reset5h, Reset7d, Status -AutoSize -Wrap
