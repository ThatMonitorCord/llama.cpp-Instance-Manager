param([string]$Version = '0.2.0', [string]$Iscc = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create .venv and install requirements.txt plus PyInstaller first.' }
& $python scripts/prepare_runtimes.py
if ($LASTEXITCODE) { throw 'Runtime preparation failed.' }
$webviewSetup = Join-Path $root 'build\downloads\MicrosoftEdgeWebview2Setup.exe'
if (-not (Test-Path -LiteralPath $webviewSetup)) {
    Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $webviewSetup
}
$signature = Get-AuthenticodeSignature -LiteralPath $webviewSetup
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation,') {
    throw 'WebView2 bootstrapper must have a valid Microsoft signature.'
}
& $python -m PyInstaller --noconfirm --clean --onedir --windowed --name LlamaInstanceManager --icon assets/manager.ico --add-data 'assets/manager.ico;assets' --add-data 'manager/web;manager/web' --add-data 'manager/preset_bridge.cjs;manager' --hidden-import webview.platforms.edgechromium --hidden-import pystray._win32 run_manager.py
if ($LASTEXITCODE) { throw 'Executable build failed.' }
Copy-Item -LiteralPath (Join-Path $root 'build\runtimes') -Destination (Join-Path $root 'dist\LlamaInstanceManager\runtimes') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $root 'LICENSE') -Destination (Join-Path $root 'dist\LlamaInstanceManager\LICENSE.txt')
if (-not $Iscc) { $Iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe' }
if (-not (Test-Path -LiteralPath $Iscc)) { throw 'Inno Setup 6 is required. Supply -Iscc with its ISCC.exe path.' }
& $Iscc /Q "/DAppVersion=$Version" installer/manager.iss
if ($LASTEXITCODE) { throw 'Setup build failed.' }
Get-ChildItem -LiteralPath (Join-Path $root 'dist') -Filter '*-setup.exe' | ForEach-Object {
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($_.Name)" | Set-Content -LiteralPath (Join-Path $root 'dist\SHA256SUMS.txt') -Encoding ascii
}
