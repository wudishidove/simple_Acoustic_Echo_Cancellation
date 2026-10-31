# 使用官方 VB-Audio Hi-Fi Cable，新增獨立端點，不占用現有 VB-CABLE。
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try {
    $installerPath = Join-Path $PSScriptRoot 'drivers\HiFiCable\HiFiCableAsioBridgeSetup.exe'
    if (-not (Test-Path -LiteralPath $installerPath)) {
        throw '找不到官方驅動安裝檔，請保留完整 EchoMic 資料夾。'
    }
    $expectedHash = '8AD78652B0AC89CC34CE5CEE05F66C9CA8A751FEB4ED06AF34532C996B4DBADD'
    $actualHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash
    if ($actualHash -ne $expectedHash) { throw '安裝檔雜湊值不符，已停止。' }
    $signature = Get-AuthenticodeSignature -LiteralPath $installerPath
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Vincent Burel') {
        throw '官方數位簽章驗證失敗，已停止。'
    }
    # 安裝程式會顯示操作介面，UAC 必須由使用者本人核准。
    Start-Process -FilePath $installerPath -Verb RunAs -WorkingDirectory (Split-Path -Parent $installerPath)
} catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '獨立虛擬麥克風安裝', 'OK', 'Error') | Out-Null
    exit 1
}
