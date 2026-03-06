<#
Setup GorCode CLI command (Windows)
Creates user-local shim and adds to PATH (user scope).
#>

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$launcher = Join-Path $repoRoot "run_gorcode.py"

if (-not (Test-Path $launcher)) {
    Write-Error "Launcher not found: $launcher"
    exit 1
}

$binDir = Join-Path $env:LOCALAPPDATA "GorCode\\bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

$cmdPath = Join-Path $binDir "gorcode.cmd"
$ps1Path = Join-Path $binDir "gorcode.ps1"

$cmdContent = "@echo off`r`npython `"$launcher`" %*`r`n"
$ps1Content = "python `"$launcher`" @args`r`n"

Set-Content -Path $cmdPath -Value $cmdContent -Encoding ASCII
Set-Content -Path $ps1Path -Value $ps1Content -Encoding ASCII

# Add to PATH (user)
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }

$pathEntries = $userPath.Split(";") | Where-Object { $_ -ne "" }
if ($pathEntries -notcontains $binDir) {
    $newPath = ($pathEntries + $binDir) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "Added to user PATH: $binDir"
} else {
    Write-Host "User PATH already contains: $binDir"
}

Write-Host "Installed gorcode command. Open a new terminal and run: gorcode --help"
