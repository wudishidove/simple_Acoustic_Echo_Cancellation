$ErrorActionPreference = 'Stop'
$currentPath = Join-Path $PSScriptRoot 'logs\debug_current.json'
if (-not (Test-Path -LiteralPath $currentPath)) { Write-Output '目前沒有背景診斷紀錄。'; exit 0 }
$currentDebug = Get-Content -LiteralPath $currentPath -Raw -Encoding UTF8 | ConvertFrom-Json
$reportDirectory = [System.IO.Path]::GetFullPath($currentDebug.directory)
$allowedPrefix = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'logs')) + '\'
if (-not $reportDirectory.StartsWith($allowedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) { throw '診斷路徑不在專案 logs 目錄內。' }
Set-Content -LiteralPath (Join-Path $reportDirectory 'stop.request') -Value 'stop' -Encoding UTF8
Write-Output '已通知背景診斷停止；音訊緩衝將隨程式結束釋放。'
