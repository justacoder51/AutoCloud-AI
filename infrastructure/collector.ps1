<# Preview or explicitly execute one reviewed collector deployment stage. #>
[CmdletBinding()]
param(
    [ValidateSet('Identity', 'Build', 'Deploy', 'Run', 'Schedule', 'Pause', 'Resume', 'Status')]
    [string]$Step = 'Identity',
    [ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')]
    [string]$ProjectId = 'astute-sign-506809-j8',
    [ValidatePattern('^[a-z]+-[a-z]+[0-9]+$')]
    [string]$Region = 'asia-south1',
    [ValidatePattern('^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')]
    [string]$ImageTag = 'v1',
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$collectorAccount = "autocloud-collector@$ProjectId.iam.gserviceaccount.com"
$schedulerAccount = "autocloud-scheduler@$ProjectId.iam.gserviceaccount.com"
$image = "${Region}-docker.pkg.dev/$ProjectId/autocloud/autocloud-collector:$ImageTag"
$commands = [System.Collections.Generic.List[object]]::new()

function Add-Command {
    param([string]$Tool, [string[]]$Arguments, [string]$ExistingAccountEmail = '')
    $commands.Add(@{
        Tool = $Tool
        Arguments = $Arguments
        ExistingAccountEmail = $ExistingAccountEmail
    })
}

switch ($Step) {
    'Identity' {
        Add-Command 'gcloud' @('iam', 'service-accounts', 'create', 'autocloud-collector',
            '--display-name=AutoCloud metric collector', "--project=$ProjectId") $collectorAccount
        Add-Command 'gcloud' @('iam', 'service-accounts', 'create', 'autocloud-scheduler',
            '--display-name=AutoCloud schedule invoker', "--project=$ProjectId") $schedulerAccount
        foreach ($role in @('roles/monitoring.viewer', 'roles/bigquery.jobUser')) {
            Add-Command 'gcloud' @('projects', 'add-iam-policy-binding', $ProjectId,
                "--member=serviceAccount:$collectorAccount", "--role=$role", '--condition=None')
        }
        # bq supports table-level IAM; dataset access is not needed for this load.
        Add-Command 'bq' @("--project_id=$ProjectId", 'add-iam-policy-binding', '--table=true',
            "--member=serviceAccount:$collectorAccount", '--role=roles/bigquery.dataEditor',
            "${ProjectId}:autocloud.infrastructure_metrics")
    }
    'Build' {
        Add-Command 'gcloud' @('builds', 'submit', '.', "--project=$ProjectId", "--region=$Region",
            '--config=infrastructure/cloudbuild.yaml',
            "--substitutions=_IMAGE=$image,_DOCKERFILE=infrastructure/collector.Dockerfile")
    }
    'Deploy' {
        Add-Command 'gcloud' @('run', 'jobs', 'deploy', 'autocloud-collector',
            "--project=$ProjectId", "--region=$Region", "--image=$image",
            "--service-account=$collectorAccount", '--tasks=1', '--parallelism=1',
            '--max-retries=1', '--task-timeout=300s', '--cpu=1', '--memory=512Mi',
            '--args=--minutes=30,--output=/tmp/metrics.ndjson,--write-bigquery',
            "--set-env-vars=APP_ENV=production,GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region")
    }
    'Run' {
        Add-Command 'gcloud' @('run', 'jobs', 'execute', 'autocloud-collector',
            "--project=$ProjectId", "--region=$Region", '--wait')
    }
    'Schedule' {
        Add-Command 'gcloud' @('services', 'enable', 'cloudscheduler.googleapis.com',
            "--project=$ProjectId")
        Add-Command 'gcloud' @('run', 'jobs', 'add-iam-policy-binding', 'autocloud-collector',
            "--project=$ProjectId", "--region=$Region",
            "--member=serviceAccount:$schedulerAccount", '--role=roles/run.invoker')
        Add-Command 'gcloud' @('scheduler', 'jobs', 'create', 'http', 'autocloud-collect',
            "--project=$ProjectId", "--location=$Region", '--schedule=*/5 * * * *',
            '--time-zone=Asia/Kolkata',
            "--uri=https://run.googleapis.com/v2/projects/$ProjectId/locations/$Region/jobs/autocloud-collector:run",
            '--http-method=POST', '--headers=Content-Type=application/json', '--message-body={}',
            "--oauth-service-account-email=$schedulerAccount", '--attempt-deadline=30s',
            '--max-retry-attempts=0')
    }
    'Pause' {
        Add-Command 'gcloud' @('scheduler', 'jobs', 'pause', 'autocloud-collect',
            "--project=$ProjectId", "--location=$Region")
    }
    'Resume' {
        Add-Command 'gcloud' @('scheduler', 'jobs', 'resume', 'autocloud-collect',
            "--project=$ProjectId", "--location=$Region")
    }
    'Status' {
        Add-Command 'gcloud' @('run', 'jobs', 'executions', 'list', '--job=autocloud-collector',
            "--project=$ProjectId", "--region=$Region", '--limit=5')
        Add-Command 'gcloud' @('scheduler', 'jobs', 'describe', 'autocloud-collect',
            "--project=$ProjectId", "--location=$Region")
    }
}

Push-Location -LiteralPath $taskRoot
try {
    foreach ($entry in $commands) {
        # Quote preview arguments containing whitespace, preserving literal text.
        # Invoke with an argument array; never execute the rendered preview string.
        $displayArguments = foreach ($argument in $entry.Arguments) {
            if ($argument -match '\s') { '"' + $argument + '"' } else { $argument }
        }
        Write-Host ($entry.Tool + ' ' + ($displayArguments -join ' '))
        if (-not $Execute) { continue }
        if ($entry.ExistingAccountEmail) {
            $existing = & gcloud iam service-accounts list "--project=$ProjectId" `
                "--filter=email=$($entry.ExistingAccountEmail)" '--format=value(email)'
            if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect existing service accounts.' }
            if ($existing -eq $entry.ExistingAccountEmail) {
                Write-Host 'Service account already exists; skipping creation.'
                continue
            }
        }
        $executable = $entry.Tool
        $commandArguments = $entry.Arguments
        & $executable @commandArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Collector stage $Step failed with exit code $LASTEXITCODE; stopping."
        }
    }
    if (-not $Execute) { Write-Host 'Preview only. No cloud resources were changed.' }
} finally {
    Pop-Location
}
