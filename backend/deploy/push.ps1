# Upload backend and run remote install.
# Usage:
#   .\deploy\push.ps1 -User root -Password 'yourpass'
#   .\deploy\push.ps1 -User root -KeyPath "$env:USERPROFILE\.ssh\id_ed25519"

param(
    [Parameter(Mandatory = $true)][string]$User,
    [string]$Password = "",
    [string]$KeyPath = "",
    [string]$HostName = "121.41.67.80",
    [string]$RemoteDir = "/opt/hand-recognition"
)

$ErrorActionPreference = "Stop"
$Backend = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path (Join-Path $Backend "backend\app\main.py"))) {
    $Backend = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$LocalBackend = Join-Path $Backend "backend"
$Archive = Join-Path $env:TEMP "hand-recognition-backend.tgz"

Write-Host "Packing $LocalBackend ..."
if (Test-Path $Archive) { Remove-Item $Archive -Force }
Push-Location $LocalBackend
tar -czf $Archive --exclude=.venv --exclude=__pycache__ --exclude=*.pyc .
Pop-Location

$sshBase = @("-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=15")
if ($KeyPath) {
    $sshTarget = @("-i", $KeyPath) + $sshBase + @("${User}@${HostName}")
    function Invoke-Remote([string]$cmd) {
        & ssh @sshTarget $cmd
        if ($LASTEXITCODE -ne 0) { throw "remote failed: $cmd" }
    }
    function Send-File([string]$local, [string]$remote) {
        & scp @("-i", $KeyPath) @sshBase $local "${User}@${HostName}:$remote"
        if ($LASTEXITCODE -ne 0) { throw "scp failed" }
    }
} elseif ($Password) {
    function Invoke-Remote([string]$cmd) {
        & sshpass -p $Password ssh @sshBase "${User}@${HostName}" $cmd
        if ($LASTEXITCODE -ne 0) { throw "remote failed: $cmd" }
    }
    function Send-File([string]$local, [string]$remote) {
        & sshpass -p $Password scp @sshBase $local "${User}@${HostName}:$remote"
        if ($LASTEXITCODE -ne 0) { throw "scp failed" }
    }
} else {
    throw "Provide -Password or -KeyPath"
}

Write-Host "Creating remote dirs..."
Invoke-Remote "mkdir -p $RemoteDir/backend /tmp"

Write-Host "Uploading archive..."
Send-File $Archive "/tmp/hand-recognition-backend.tgz"

Write-Host "Extracting and installing..."
Invoke-Remote "mkdir -p $RemoteDir/backend && tar -xzf /tmp/hand-recognition-backend.tgz -C $RemoteDir/backend && bash $RemoteDir/backend/deploy/install.sh"

Write-Host "Done. Health:"
Invoke-Remote "curl -sS http://127.0.0.1:8000/api/health; echo"
