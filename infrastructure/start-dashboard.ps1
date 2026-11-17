param(
    [string]$ForecastRun = 'models/runs/20261116T051914Z_48d41482'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$runPath = (Resolve-Path -LiteralPath (Join-Path $projectRoot $ForecastRun)).Path
if (-not (Test-Path -LiteralPath (Join-Path $runPath 'forecast_manifest.json'))) {
    throw 'Selected run has no native forecast manifest.'
}
foreach ($port in @(8080, 8501)) {
    $probe = New-Object System.Net.Sockets.TcpClient
    try {
        $connection = $probe.ConnectAsync('127.0.0.1', $port)
        $listening = $connection.Wait(1000) -and $probe.Connected
    } catch {
        $listening = $false
    } finally {
        $probe.Dispose()
    }
    if ($listening) {
        throw "Port $port is already in use. Open http://127.0.0.1:8501/ or restart the existing server separately."
    }
}
$logs = Join-Path $projectRoot 'data/dashboard_logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$variables = @{
    GCP_PROJECT_ID = 'astute-sign-506809-j8'
    GCP_REGION = 'asia-south1'
    DASHBOARD_FORECAST_RUN = $runPath
    DASHBOARD_BILLING_TABLE = 'astute-sign-506809-j8.autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560'
}
$previous = @{}
try {
    foreach ($key in $variables.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $variables[$key], 'Process')
    }
    $api = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8080') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'api.out.log') -RedirectStandardError (Join-Path $logs 'api.err.log')
    $dashboard = Start-Process -FilePath $python -ArgumentList @('-m','streamlit','run','app/dashboard/home.py','--server.address=127.0.0.1','--server.port=8501','--server.headless=true','--browser.gatherUsageStats=false') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'dashboard.out.log') -RedirectStandardError (Join-Path $logs 'dashboard.err.log')
    @{api_pid=$api.Id; dashboard_pid=$dashboard.Id; forecast_run=$runPath} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logs 'processes.json')
    Write-Output "Local API PID: $($api.Id); dashboard PID: $($dashboard.Id). Open http://127.0.0.1:8501/"
} finally {
    foreach ($key in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
    }
}
# Keep the supervising terminal alive for environments that clean up child
# processes when their launching command exits.
Wait-Process -Id $api.Id, $dashboard.Id
