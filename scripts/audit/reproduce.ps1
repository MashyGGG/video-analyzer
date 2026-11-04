param(
    [switch]$RunRuntime,
    [int]$BuildTimeoutSeconds = 240
)
$ErrorActionPreference = 'Stop'
$auditRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Set-Location -LiteralPath $auditRoot
$auditSha = 'adc13afb47a112f0def0435231e691a5307e5b49'
$auditUpstream = Join-Path $auditRoot '.audit-cache/parse_video'
$auditProbe = Join-Path $PSScriptRoot 'run_probe.py'
$auditRun = 'evidence/A00/replay-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
New-Item -ItemType Directory -Path $auditRun -Force | Out-Null

function Invoke-AuditProbe {
    param([string]$Name, [string]$WorkingDirectory, [string[]]$CommandArgs, [int]$Timeout = 120)
    & python $auditProbe --cwd $WorkingDirectory --output (Join-Path $auditRun ($Name + '.json')) --timeout $Timeout -- @CommandArgs
    # Nonzero is expected for original defects and blocked prerequisites; the JSON records its exact code.
}

if (-not (Test-Path -LiteralPath $auditUpstream)) {
    & git clone --depth 1 https://github.com/XztCloud/parse_video.git $auditUpstream
    if ($LASTEXITCODE -ne 0) { throw 'Upstream clone failed' }
    & git -C $auditUpstream fetch --depth 1 origin $auditSha
    if ($LASTEXITCODE -ne 0) { throw 'Pinned commit fetch failed' }
    & git -C $auditUpstream checkout --detach $auditSha
    if ($LASTEXITCODE -ne 0) { throw 'Pinned checkout failed' }
}
$auditActualSha = & git -C $auditUpstream rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $auditActualSha -ne $auditSha) { throw 'Existing upstream is not the audited revision' }
Invoke-AuditProbe -Name 'integrity' -WorkingDirectory $auditUpstream -CommandArgs @('git', 'status', '--porcelain')
Invoke-AuditProbe -Name 'docker-version' -WorkingDirectory $auditRoot -CommandArgs @('docker', 'version') -Timeout 30
Invoke-AuditProbe -Name 'url-validator' -WorkingDirectory $auditRoot -CommandArgs @('python', 'scripts/audit/probe_url_validator.py', '--output', (Join-Path $auditRun 'url-validator-result.json'))

if (-not $RunRuntime) {
    Write-Output "Read-only probes recorded in $auditRun. Use -RunRuntime in a fresh workspace/cache for install/build attempts."
    exit 0
}
if (Test-Path -LiteralPath (Join-Path $auditUpstream '.env')) {
    throw 'Runtime replay requires a fresh audit cache: refusing to overwrite an existing .env or reuse unknown credentials'
}
& python scripts/audit/prepare_baseline.py
if ($LASTEXITCODE -ne 0) { throw 'Disposable configuration preparation failed' }
Invoke-AuditProbe -Name 'venv-create' -WorkingDirectory $auditRoot -CommandArgs @('uv', 'venv', '--python', '3.12', '.audit-cache/venv')
$auditPython = Join-Path $auditRoot '.audit-cache/venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $auditPython)) { throw 'Python 3.12 audit environment unavailable' }
Invoke-AuditProbe -Name 'uv-install' -WorkingDirectory $auditRoot -CommandArgs @('uv', 'pip', 'install', '--python', $auditPython, '.audit-cache/parse_video/backend') -Timeout 180
Invoke-AuditProbe -Name 'pip-bootstrap' -WorkingDirectory $auditRoot -CommandArgs @($auditPython, '-m', 'ensurepip')
Invoke-AuditProbe -Name 'pip-install' -WorkingDirectory $auditRoot -CommandArgs @($auditPython, '-m', 'pip', 'install', '.audit-cache/parse_video/backend') -Timeout 180
Invoke-AuditProbe -Name 'pytest-bootstrap' -WorkingDirectory $auditRoot -CommandArgs @('uv', 'pip', 'install', '--python', $auditPython, 'pytest==8.4.2')
# Root API tests include real platform fixtures. Do not replay those without authorization.
# The selected original service tests remain subject to upstream conftest/import prerequisites.
Invoke-AuditProbe -Name 'pytest-services' -WorkingDirectory (Join-Path $auditUpstream 'backend') -CommandArgs @($auditPython, '-m', 'pytest', '-q', 'tests/tests/services')
$auditFrontend = Join-Path $auditUpstream 'frontend'
Invoke-AuditProbe -Name 'npm-ci' -WorkingDirectory $auditFrontend -CommandArgs @('npm.cmd', 'ci', '--ignore-scripts', '--no-audit', '--no-fund') -Timeout 180
Invoke-AuditProbe -Name 'typecheck' -WorkingDirectory $auditFrontend -CommandArgs @('node', 'node_modules/typescript/bin/tsc', '--noEmit')
$env:API_PROXY_TARGET = 'http://127.0.0.1:18000'
Invoke-AuditProbe -Name 'build' -WorkingDirectory $auditFrontend -CommandArgs @('npm.cmd', 'run', 'build') -Timeout 180
Invoke-AuditProbe -Name 'lint' -WorkingDirectory $auditFrontend -CommandArgs @('npm.cmd', 'run', 'lint') -Timeout 60
$auditComposeArgs = @('docker', 'compose', '-p', 'video-analyzer-a00', '-f', 'docker-compose.yml', '-f', '../compose.audit.yaml')
try {
    Invoke-AuditProbe -Name 'compose-config' -WorkingDirectory $auditUpstream -CommandArgs ($auditComposeArgs + @('config', '--quiet'))
    Invoke-AuditProbe -Name 'compose-up' -WorkingDirectory $auditUpstream -CommandArgs ($auditComposeArgs + @('up', '-d', '--build')) -Timeout $BuildTimeoutSeconds
    Invoke-AuditProbe -Name 'compose-ps' -WorkingDirectory $auditUpstream -CommandArgs ($auditComposeArgs + @('ps', '--all', '--format', 'json'))
} finally {
    Invoke-AuditProbe -Name 'compose-down' -WorkingDirectory $auditUpstream -CommandArgs ($auditComposeArgs + @('down', '--remove-orphans')) -Timeout 60
}
Write-Output "Replay commands finished. Inspect individual exit codes in $auditRun; script completion is not acceptance PASS."
