$pidFile=Join-Path $PSScriptRoot 'data\v2-server.pid'
if(Test-Path -LiteralPath $pidFile){
 $serverId=[int](Get-Content -LiteralPath $pidFile)
 $running=Get-CimInstance Win32_Process -Filter "ProcessId = $serverId"
 $expected=Join-Path $PSScriptRoot 'server.py'
 if($running -and $running.CommandLine.Contains($expected)){Stop-Process -Id $serverId}
}
