$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$portNumber=if($env:COPILOT_PORT){$env:COPILOT_PORT}else{'8765'}
$v2Url="http://127.0.0.1:$portNumber"
try {
    $state=Invoke-RestMethod -Uri "$v2Url/api/state" -TimeoutSec 2
    if($state.version -eq '2.0'){Start-Process "microsoft-edge:$v2Url";exit}
    Write-Host 'Another version is using this port. Close its server window before starting V2.'
    Read-Host 'Press Enter';exit 1
} catch [System.Net.WebException] {}
$bundled=Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$local=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runtime=if(Test-Path -LiteralPath $local){$local}elseif(Test-Path -LiteralPath $bundled){$bundled}else{'python'}
& $runtime -c 'import pypdf, docx'
if($LASTEXITCODE -ne 0){Write-Host 'Install requirements first: python -m pip install -r requirements.txt';Read-Host 'Press Enter';exit 1}
$serverPath=Join-Path $PSScriptRoot 'server.py'
$process=Start-Process -FilePath $runtime -ArgumentList ('"'+$serverPath+'"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
$process.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'data\v2-server.pid')
for($i=0;$i -lt 20;$i++){
    Start-Sleep -Milliseconds 500
    try{$state=Invoke-RestMethod -Uri "$v2Url/api/state" -TimeoutSec 2;if($state.version -eq '2.0'){Start-Process "microsoft-edge:$v2Url";exit}}catch{}
}
Write-Host 'Startup failed. Run Start.cmd to see the error.'
Read-Host 'Press Enter'
