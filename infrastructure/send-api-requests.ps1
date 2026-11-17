<#
Send a bounded sequence of authenticated requests; Ctrl+C stops the sender.
Printed elapsed times are client round-trip times, not Cloud Monitoring latency.
#>
param(
    [ValidateRange(1, 450)][int]$Count = 12,
    [ValidateRange(1, 60)][int]$IntervalSeconds = 5
)

$ErrorActionPreference = 'Stop'
$apiEndpoint = 'https://autocloud-api-l25hfnltba-el.a.run.app/health/ready'
$cloudCommand = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
if (-not $cloudCommand) { $cloudCommand = Get-Command gcloud -ErrorAction Stop }
$identityToken = & $cloudCommand.Source auth print-identity-token --quiet 2>$null
if ($LASTEXITCODE -ne 0 -or -not $identityToken) {
    throw 'Google Cloud authentication failed. Run gcloud auth login, then retry.'
}
$requestHeaders = @{ Authorization = 'Bearer ' + ($identityToken -join '').Trim() }
$batchId = [guid]::NewGuid().ToString('N')
$requestUri = $apiEndpoint + '?traffic_source=manual-demo&batch=' + $batchId
$deadline = [DateTime]::UtcNow.AddMinutes(30)
$successCount = 0
Write-Host ('Sending up to {0} requests; interval {1}s; hard limit 30 minutes. Ctrl+C stops.' -f $Count, $IntervalSeconds)
Write-Host ('Batch: ' + $batchId)
try {
    for ($requestIndex = 1; $requestIndex -le $Count; $requestIndex++) {
        if ([DateTime]::UtcNow -ge $deadline.AddSeconds(-15)) { break }
        $timer = [Diagnostics.Stopwatch]::StartNew()
        try {
            $response = Invoke-WebRequest -Uri $requestUri -Headers $requestHeaders -Method Get -UseBasicParsing -TimeoutSec 15
            $timer.Stop()
            $status = [int]$response.StatusCode
            if ($status -ge 200 -and $status -lt 300) { $successCount++ }
            Write-Host ('{0}  {1}/{2}  HTTP {3}  client round-trip {4} ms' -f [DateTime]::UtcNow.ToString('o'), $requestIndex, $Count, $status, $timer.ElapsedMilliseconds)
        } catch {
            $timer.Stop()
            $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 'network error / timeout' }
            Write-Host ('{0}  {1}/{2}  {3}' -f [DateTime]::UtcNow.ToString('o'), $requestIndex, $Count, $status)
            if ($status -in 401, 403) { throw 'API access denied. Use a Google account with Cloud Run Invoker access; no permissions were changed.' }
        }
        if ($requestIndex -lt $Count -and [DateTime]::UtcNow.AddSeconds($IntervalSeconds + 15) -lt $deadline) {
            Start-Sleep -Seconds $IntervalSeconds
        } elseif ($requestIndex -lt $Count) { break }
    }
} finally {
    $requestHeaders.Clear()
    $identityToken = $null
    Write-Host ('Successful requests: ' + $successCount)
    Write-Host 'Allow the next collector cycle and monitoring ingestion delay before refreshing the dashboard.'
}
