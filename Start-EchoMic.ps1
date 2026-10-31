$ErrorActionPreference = 'Stop'
$appPath = Join-Path $PSScriptRoot 'dist\EchoMic\EchoMic.exe'
if (Test-Path -LiteralPath $appPath) {
    Start-Process -FilePath $appPath -WorkingDirectory (Split-Path -Parent $appPath)
} else {
    $pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw '找不到程式，請先執行 Build.ps1。' }
    Start-Process -FilePath $pythonPath -ArgumentList ('"' + (Join-Path $PSScriptRoot 'echo_mic.py') + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
}
