param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "Project interpreter not found at $pythonExecutable. Create .venv and install the project first."
}

Push-Location $projectRoot
try {
    & $pythonExecutable -m PyInstaller --noconfirm --clean "packaging\apokalypse.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $builtExecutable = Join-Path $projectRoot "dist\BT Apokalypse\BT Apokalypse.exe"
    if (-not (Test-Path -LiteralPath $builtExecutable)) {
        throw "Build completed without producing $builtExecutable"
    }

    $smokeTest = Start-Process -FilePath $builtExecutable -ArgumentList "--self-test" -Wait -PassThru -WindowStyle Hidden
    if ($smokeTest.ExitCode -ne 0) {
        throw "Packaged application self-test failed with exit code $($smokeTest.ExitCode)."
    }

    Write-Host "Standalone application passed its self-test: $builtExecutable" -ForegroundColor Green

    if ($SkipInstaller) { return }

    $compilerCandidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $innoCompiler = $compilerCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $innoCompiler) {
        Write-Warning "Inno Setup 6 or 7 is not installed. The standalone folder is ready; install Inno Setup and rerun this script to create the installer."
        return
    }

    & $innoCompiler "/DAppVersion=0.1.0" "packaging\installer.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed." }
    Write-Host "Installer: $projectRoot\release\BT-Apokalypse-Setup-0.1.0.exe" -ForegroundColor Green
}
finally {
    Pop-Location
}
