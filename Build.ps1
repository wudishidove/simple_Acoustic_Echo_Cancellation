param([switch]$SkipDependencyInstall, [switch]$PackageOnly)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# 原始碼不追蹤第三方驅動二進位檔；乾淨 checkout 由官方來源取得並驗證。
$driverPath = Join-Path $PSScriptRoot 'drivers\HiFiCable\HiFiCableAsioBridgeSetup.exe'
if (-not (Test-Path -LiteralPath $driverPath)) {
    $downloadRoot = Join-Path $PSScriptRoot 'build\downloads'
    New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null
    $driverArchive = Join-Path $downloadRoot 'HiFiCableAsioBridgeSetup_v1007.zip'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://download.vb-audio.com/Download_CABLE/HiFiCableAsioBridgeSetup_v1007.zip' -OutFile $driverArchive
    Expand-Archive -LiteralPath $driverArchive -DestinationPath (Join-Path $downloadRoot 'HiFiCable') -Force
    $downloadedInstaller = Get-ChildItem -LiteralPath (Join-Path $downloadRoot 'HiFiCable') -Filter 'HiFiCableAsioBridgeSetup.exe' -File -Recurse | Select-Object -First 1
    if (-not $downloadedInstaller) { throw '官方下載檔中找不到虛擬音訊驅動安裝程式' }
    $downloadedHash = (Get-FileHash -LiteralPath $downloadedInstaller.FullName -Algorithm SHA256).Hash
    if ($downloadedHash -ne '8AD78652B0AC89CC34CE5CEE05F66C9CA8A751FEB4ED06AF34532C996B4DBADD') {
        throw '官方驅動安裝檔雜湊值不符，已停止建置'
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $driverPath) -Force | Out-Null
    Copy-Item -LiteralPath $downloadedInstaller.FullName -Destination $driverPath
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    if ($SkipDependencyInstall) { throw '找不到建置環境，請先不加 -SkipDependencyInstall 執行 Build.ps1。' }
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '建立 Python 環境失敗' }
}
if (-not $SkipDependencyInstall) {
    & '.\.venv\Scripts\python.exe' -m pip install --only-binary=:all: -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw '安裝套件失敗' }
}
$calibrationAsset = Join-Path $PSScriptRoot 'assets\calibration_speech.wav'
if (-not (Test-Path -LiteralPath $calibrationAsset)) {
    New-Item -ItemType Directory -Path 'assets' -Force | Out-Null
    Add-Type -AssemblyName System.Speech
    $calibrationVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        $calibrationVoice.SelectVoice('Microsoft David Desktop')
        $calibrationVoice.SetOutputToWaveFile($calibrationAsset)
        $calibrationVoice.Speak('This is an acoustic echo cancellation test. The sound coming from the speakers should be removed from the microphone. Your own voice should remain clear. We are checking timing, room reflections, and the speaker reference signal. One, two, three, four, five.')
    } finally {
        $calibrationVoice.Dispose()
    }
}
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw '測試失敗' }
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean --distpath 'build\release' EchoMic.spec
if ($LASTEXITCODE -ne 0) { throw '打包失敗' }

# 封裝環境、音效資產與官方驅動皆一併提供，終端使用者不需安裝 Python。
Copy-Item -LiteralPath 'Install-VirtualMic.ps1' -Destination 'build\release\EchoMic\Install-VirtualMic.ps1' -Force
Copy-Item -LiteralPath 'README.md' -Destination 'build\release\EchoMic\使用說明.md' -Force
Copy-Item -LiteralPath '快速開始.txt' -Destination 'build\release\EchoMic\快速開始.txt' -Force
New-Item -ItemType Directory -Path 'build\release\EchoMic\drivers\HiFiCable' -Force | Out-Null
Copy-Item -LiteralPath 'drivers\HiFiCable\HiFiCableAsioBridgeSetup.exe' -Destination 'build\release\EchoMic\drivers\HiFiCable\HiFiCableAsioBridgeSetup.exe' -Force

New-Item -ItemType Directory -Path 'dist' -Force | Out-Null
if (-not $PackageOnly) {
    New-Item -ItemType Directory -Path 'dist\EchoMic' -Force | Out-Null
    # /E 合併更新程式檔案，保留既有 settings.json 與 logs；不使用 /MIR。
    & robocopy 'build\release\EchoMic' 'dist\EchoMic' /E /R:1 /W:1 /NFL /NDL /NJH /NJS
    if ($LASTEXITCODE -ge 8) { throw '更新可執行程式失敗；請先關閉 EchoMic 再重試' }
}

# 從乾淨產物封裝，避免把 dist 中既有設定、紀錄或校正報告一起散布。
Compress-Archive -LiteralPath 'build\release\EchoMic' -DestinationPath 'dist\EchoMic-Windows-x64.zip' -Force
& (Join-Path $PSScriptRoot 'Verify-Portable.ps1')
if (-not $PackageOnly) { Write-Output '完成：dist\EchoMic\EchoMic.exe' }
Write-Output '分享用免安裝版：dist\EchoMic-Windows-x64.zip（請完整解壓縮）'
