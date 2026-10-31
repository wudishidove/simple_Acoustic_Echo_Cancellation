param([ValidateRange(3,3600)][int]$Seconds = 600)
$ErrorActionPreference = 'Stop'
$logsPath = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logsPath -Force | Out-Null
$currentPath = Join-Path $logsPath 'debug_current.json'
if (Test-Path -LiteralPath $currentPath) {
    $currentDebug = Get-Content -LiteralPath $currentPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $statusPath = Join-Path $currentDebug.directory 'status.json'
    if (Test-Path -LiteralPath $statusPath) {
        $currentStatus = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($currentStatus.state -in @('starting', 'running') -and (Get-Process -Id $currentDebug.pid -ErrorAction SilentlyContinue)) {
            Write-Output ('已有背景診斷執行中：' + $currentDebug.directory)
            exit 0
        }
    }
}
$reportDirectory = Join-Path $logsPath ('debug_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$debugPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$debugScript = Join-Path $PSScriptRoot 'debug_monitor.py'
$debugArguments = @('"' + $debugScript + '"', '--seconds', $Seconds, '--directory', '"' + $reportDirectory + '"')
$debugProcess = Start-Process -FilePath $debugPython -ArgumentList $debugArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $reportDirectory 'stdout.log') -RedirectStandardError (Join-Path $reportDirectory 'stderr.log')
@{pid=$debugProcess.Id; directory=$reportDirectory; seconds=$Seconds} | ConvertTo-Json | Set-Content -LiteralPath $currentPath -Encoding UTF8
Write-Output ('背景診斷 PID：' + $debugProcess.Id)
Write-Output ('統計結果：' + $reportDirectory)
Write-Output '只儲存數值統計，不儲存音訊。執行 Stop-Debug.ps1 可提前停止。'
