param([string]$Archive = (Join-Path $PSScriptRoot 'dist\EchoMic-Windows-x64.zip'))

$ErrorActionPreference = 'Stop'
# 解壓到含空白與中文的新目錄，不與原始碼或開發環境放在一起。
$checkRoot = Join-Path $PSScriptRoot ('build\portable-check\免安裝 測試 ' + [guid]::NewGuid().ToString('N'))
Expand-Archive -LiteralPath $Archive -DestinationPath $checkRoot
$appRoot = Join-Path $checkRoot 'EchoMic'
$executable = Join-Path $appRoot 'EchoMic.exe'
if ((Test-Path -LiteralPath (Join-Path $appRoot 'settings.json')) -or
    (Test-Path -LiteralPath (Join-Path $appRoot 'logs'))) {
    throw '分享用 ZIP 不應包含既有使用者設定或紀錄。'
}
foreach ($file in @('EchoMic.exe', '_internal\python312.dll', '_internal\assets\calibration_speech.wav',
                    '_internal\assets\EchoMic.ico', 'Install-VirtualMic.ps1',
                    'drivers\HiFiCable\HiFiCableAsioBridgeSetup.exe', '使用說明.md', '快速開始.txt')) {
    if (-not (Test-Path -LiteralPath (Join-Path $appRoot $file))) { throw "免安裝版缺少必要檔案：$file" }
}

function Invoke-PackagedCheck([string]$Arguments) {
    $process = Start-Process -FilePath $executable -ArgumentList $Arguments -WorkingDirectory $checkRoot -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(45000)) {
        $process.Kill()
        throw '免安裝版檢查逾時。'
    }
    if ($process.ExitCode -ne 0) { throw "免安裝版檢查失敗，結束碼：$($process.ExitCode)" }
}

$previousPath = $env:Path
$previousPythonHome = $env:PYTHONHOME
$previousPythonPath = $env:PYTHONPATH
try {
    # 子程序只能從系統路徑找到 Windows 元件，不可借用開發機的 Python。
    $env:Path = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONHOME = $null
    $env:PYTHONPATH = $null
    Invoke-PackagedCheck '--self-check'
    $report = Get-Content -LiteralPath (Join-Path $appRoot 'logs\self-check.json') -Encoding UTF8 -Raw | ConvertFrom-Json
    foreach ($field in @('ok', 'bundled_runtime', 'dpi_aware', 'aec', 'tray_backend', 'layout_fits', 'calibration_button', 'startup_button', 'close_behavior_checkbox')) {
        if (-not $report.$field) { throw "免安裝版檢查未通過：$field" }
    }

    # 預先取消的校正工作不開啟音訊，仍會載入封裝內的校正模組與語音資產。
    $request = Join-Path $appRoot 'logs\portable-worker.request.json'
    $workerReport = Join-Path $appRoot 'logs\portable-worker.json'
    $requestJson = @{microphone_name='portable check'; speaker_name='portable check'; delay_ms=40} | ConvertTo-Json
    [System.IO.File]::WriteAllText($request, $requestJson, [System.Text.UTF8Encoding]::new($false))
    Set-Content -LiteralPath (Join-Path $appRoot 'logs\portable-worker.cancel') -Value 'cancel' -Encoding UTF8
    Invoke-PackagedCheck ('--calibrate-worker "' + $request + '" "' + $workerReport + '"')
    $worker = Get-Content -LiteralPath $workerReport -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($worker.state -ne 'cancelled' -or $worker.audio_saved) { throw '封裝後的校正子程序檢查失敗。' }
    Write-Output "免 Python 驗證通過：$appRoot"
    Write-Output 'EXE、原生 AEC、音訊裝置列舉、UI、系統匣及校正子程序皆可獨立執行。'
} finally {
    $env:Path = $previousPath
    $env:PYTHONHOME = $previousPythonHome
    $env:PYTHONPATH = $previousPythonPath
}
