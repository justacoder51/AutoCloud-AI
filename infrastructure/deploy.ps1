<# Preview the first deployment. Use -Execute only after human approval. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')]
    [string]$ProjectId,
    [ValidatePattern('^[a-z]+-[a-z]+[0-9]+$')][string]$Region = 'asia-south1',
    [ValidatePattern('^[a-z][a-z0-9-]{0,47}$')][string]$Service = 'autocloud-api',
    [ValidatePattern('^[a-z][a-z0-9-]{0,47}$')][string]$Repository = 'autocloud',
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z][a-z0-9-]+@[a-z][a-z0-9-]+\.iam\.gserviceaccount\.com$')]
    [string]$RuntimeServiceAccount,
    [ValidateRange(1, 2)][int]$MaxInstances = 2,
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$imageTag = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
$image = "${Region}-docker.pkg.dev/$ProjectId/$Repository/${Service}:$imageTag"
$commands = @(
    ,@('builds', 'submit', '.', "--project=$ProjectId", "--region=$Region",
        '--config=infrastructure/cloudbuild.yaml', "--substitutions=_IMAGE=$image")
    ,@('run', 'deploy', $Service, "--project=$ProjectId", "--region=$Region",
        "--image=$image", "--service-account=$RuntimeServiceAccount",
        '--no-allow-unauthenticated', '--min=0', "--max=$MaxInstances",
        '--cpu=1', '--memory=512Mi', '--concurrency=40', '--timeout=30',
        '--port=8080',
        "--set-env-vars=APP_ENV=production,GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region,MIN_INSTANCES=0,MAX_INSTANCES=$MaxInstances")
)
Push-Location -LiteralPath $taskRoot
try {
    foreach ($command in $commands) {
        Write-Host ('gcloud ' + ($command -join ' '))
        if ($Execute) {
            & gcloud @command
            if ($LASTEXITCODE -ne 0) {
                throw "Deployment step failed with exit code $LASTEXITCODE; stopping."
            }
        }
    }
    if (-not $Execute) {
        Write-Host 'Preview only. No cloud resources were changed.'
    }
} finally {
    Pop-Location
}
