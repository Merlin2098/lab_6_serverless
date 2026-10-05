<#
.SYNOPSIS
    PowerShell equivalent of scripts/python/update_venv.sh for students without Git Bash.

.DESCRIPTION
    Runs `uv sync --upgrade` against an existing .venv from pyproject.toml /
    uv.lock. Mirrors update_venv.sh phase for phase.

.PARAMETER IncludeDev
    Install the dev dependency-group explicitly (default behavior).

.PARAMETER NoDev
    Skip the dev dependency-group.

.EXAMPLE
    .\scripts\python\update_venv.ps1

.EXAMPLE
    .\scripts\python\update_venv.ps1 -NoDev
#>
[CmdletBinding()]
param(
    [switch]$IncludeDev,
    [switch]$NoDev
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($IncludeDev -and $NoDev) {
    Write-Error "Use either -IncludeDev or -NoDev, but not both."
    exit 1
}
$useDevDependencies = -not $NoDev

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")

function Write-Step {
    param([string]$Message)
    Write-Host $Message
}

function Write-Phase {
    param([string]$Title)
    Write-Host ""
    Write-Host "=== $Title ==="
}

function Resolve-VenvPython {
    param([string]$VenvDir)
    $winPython = Join-Path $VenvDir "Scripts\python.exe"
    $posixPython = Join-Path $VenvDir "bin/python"
    if (Test-Path $winPython) {
        return $winPython
    }
    elseif (Test-Path $posixPython) {
        return $posixPython
    }
    else {
        Write-Error "No python interpreter found under '$VenvDir' (checked Scripts\python.exe and bin/python)."
        exit 1
    }
}

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    Write-Error "uv is required but was not found on PATH. Install it from https://docs.astral.sh/uv/getting-started/installation/ and retry."
    exit 1
}

$venvDir = Join-Path $repoRoot ".venv"
if (-not (Test-Path $venvDir)) {
    Write-Error "No .venv directory was found. Run .\scripts\python\setup_env.ps1 first."
    exit 1
}
$venvPython = Resolve-VenvPython $venvDir

Write-Step "Starting virtual environment update via uv."

Write-Phase "Phase 1: Validate Environment"
Write-Step "[venv] Using existing interpreter: $venvPython"
& $venvPython --version

$pyprojectPath = Join-Path $repoRoot "pyproject.toml"
if (-not (Test-Path $pyprojectPath)) {
    Write-Error "pyproject.toml is required for the uv update flow."
    exit 1
}
Write-Step "[Project] Verified pyproject.toml and existing .venv."

Write-Phase "Phase 2: Update Dependencies"
$env:UV_LINK_MODE = "copy"

$syncArgs = @("sync", "--upgrade")
if (-not $useDevDependencies) {
    $syncArgs += @("--no-group", "dev")
}
Write-Step "[Dependencies] Running: uv $($syncArgs -join ' ')"

Push-Location $repoRoot
try {
    & uv @syncArgs
}
finally {
    Pop-Location
}

Write-Phase "Phase 3: Summary"
Write-Step "Virtual environment updated successfully."
Write-Host "Suggested interpreter path: $venvPython"
