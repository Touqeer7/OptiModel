param([switch]$SkipSetup)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if ($SkipSetup) { python run.py } else { python run.py --setup }
    if ($LASTEXITCODE -ne 0) { throw "OptiModel exited with code $LASTEXITCODE. See the startup message above." }
} finally { Pop-Location }
