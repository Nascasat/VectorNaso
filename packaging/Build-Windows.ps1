param(
    [string]$Python = "py"
)

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot
Push-Location $Project
try {
    $pythonCommand = Get-Command $Python -ErrorAction Stop
    $release = Join-Path $Project "Releases\Windows"
    $dist = Join-Path $release "dist"
    $work = Join-Path $release "work"
    $spec = Join-Path $release "spec"
    $dependencies = Join-Path $release "dependencies"
    $temporary = Join-Path $release "temp"
    $setupDist = Join-Path $release "setup-dist"
    $setupWork = Join-Path $release "setup-work"
    $setupSpec = Join-Path $release "setup-spec"
    $pipCache = Join-Path $release "pip-cache"
    $installerPayload = Join-Path $release "installer-payload"
    $venv = Join-Path $release "venv"
    $legacyInstallerFiles = @(
        (Join-Path $release "VectorNaso-Setup.sed"),
        (Join-Path $release "~VectorNaso-Setup.DDF")
    )
    New-Item -ItemType Directory -Force -Path $release | Out-Null
    $safeRoot = [IO.Path]::GetFullPath($release) + [IO.Path]::DirectorySeparatorChar
    foreach ($path in @($dist, $work, $spec, $dependencies, $temporary, $setupDist, $setupWork, $setupSpec, $pipCache, $installerPayload, $venv)) {
        $absolute = [IO.Path]::GetFullPath($path)
        if (-not $absolute.StartsWith($safeRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Percorso di build fuori dalla cartella Releases: $absolute"
        }
        if (Test-Path -LiteralPath $absolute) { Remove-Item -LiteralPath $absolute -Recurse -Force }
    }
    foreach ($path in $legacyInstallerFiles) {
        $absolute = [IO.Path]::GetFullPath($path)
        if (-not $absolute.StartsWith($safeRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Percorso di build fuori dalla cartella Releases: $absolute"
        }
        if (Test-Path -LiteralPath $absolute) { Remove-Item -LiteralPath $absolute -Force }
    }

    New-Item -ItemType Directory -Force -Path $temporary | Out-Null
    $env:TEMP = $temporary
    $env:TMP = $temporary
    $env:PIP_CACHE_DIR = Join-Path $release "pip-cache"
    New-Item -ItemType Directory -Force -Path $env:PIP_CACHE_DIR | Out-Null
    New-Item -ItemType Directory -Force -Path $dependencies | Out-Null
    & $pythonCommand.Source -m pip install --target $dependencies -r requirements.txt pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Installazione dipendenze di build non riuscita." }
    $env:PYTHONPATH = "$dependencies;$env:PYTHONPATH"

    $pyArgs = @(
        "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
        "--name", "VectorNaso", "--icon", (Join-Path $Project "assets\branding\VectorNaso.ico"),
        "--distpath", $dist, "--workpath", $work, "--specpath", $spec,
        "--add-data", "$(Join-Path $Project 'index.html');.",
        "--add-data", "$(Join-Path $Project 'editor.js');.",
        "--add-data", "$(Join-Path $Project 'enhancements.js');.",
        "--add-data", "$(Join-Path $Project 'assets');assets",
        "--add-data", "$(Join-Path $Project 'Samples');Samples",
        "--collect-all", "vtracer",
        "--collect-all", "ezdxf",
        "--collect-all", "svgpathtools",
        "--collect-all", "svglib",
        "--collect-all", "reportlab",
        (Join-Path $Project "vectornaso_server.py")
    )
    & $pythonCommand.Source @pyArgs
    if ($LASTEXITCODE -ne 0) { throw "Build PyInstaller non riuscita." }

    $app = Join-Path $dist "VectorNaso"
    Copy-Item -LiteralPath (Join-Path $Project "Samples") -Destination (Join-Path $app "Samples") -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $Project "LEGGIMI.txt") -Destination $app
    $zip = Join-Path $release "VectorNaso-Windows.zip"
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Compress-Archive -Path (Join-Path $app "*") -DestinationPath $zip -CompressionLevel Optimal

    $zipData = "$zip;."
    $installerArgs = @(
        "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "VectorNaso-Setup", "--icon", (Join-Path $Project "assets\branding\VectorNaso.ico"),
        "--distpath", $setupDist, "--workpath", $setupWork, "--specpath", $setupSpec,
        "--add-data", $zipData,
        (Join-Path $PSScriptRoot "installer_windows.py")
    )
    & $pythonCommand.Source @installerArgs
    if ($LASTEXITCODE -ne 0) { throw "Build installer Windows non riuscita." }
    $installer = Join-Path $setupDist "VectorNaso-Setup.exe"
    Copy-Item -LiteralPath $installer -Destination (Join-Path $release "VectorNaso-Setup.exe") -Force
    $installer = Join-Path $release "VectorNaso-Setup.exe"

    Write-Host "Build Windows completata: $app\VectorNaso.exe"
    Write-Host "Pacchetto con Samples: $zip"
    Write-Host "Installer Windows: $installer"
}
finally { Pop-Location }
