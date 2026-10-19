$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) { $runtime = $localPython }
elseif (Test-Path -LiteralPath $bundledPython) { $runtime = $bundledPython }
else { $runtime = 'python' }
& $runtime -c "import pypdf, docx"
if ($LASTEXITCODE -ne 0) { Write-Host 'Install Python 3.11+ and run: python -m pip install -r requirements.txt'; Read-Host 'Press Enter'; exit 1 }
$portNumber = if ($env:COPILOT_PORT) { $env:COPILOT_PORT } else { '8765' }
$localUrl = "http://127.0.0.1:$portNumber"
Write-Host "Open Microsoft Edge: $localUrl"
Write-Host 'Keep this window open. Press Ctrl+C to stop.'
& $runtime server.py
