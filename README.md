# Echo Mic 回音消除麥克風

將原始麥克風與喇叭播放參考交給 WebRTC Acoustic Echo Cancellation，輸出到**另外新增的虛擬麥克風端點**。保留原有 VB-CABLE 的用途，不會將它當作輸出。

[下載 Windows x64 免安裝版](https://github.com/wudishidove/simple_Acoustic_Echo_Cancellation/releases/latest/download/EchoMic-Windows-x64.zip) · [版本與更新紀錄](https://github.com/wudishidove/simple_Acoustic_Echo_Cancellation/releases)

## 使用

一般使用者不需要安裝 Python、pip 或任何 Python 套件。從上方下載免安裝版（檔名 `EchoMic-Windows-x64.zip`），先解壓縮整個資料夾，再雙擊其中的 `EchoMic.exe`。請保留 `_internal`（內含 Python 執行環境與音訊函式庫）、`drivers` 及安裝工具，不能只複製 EXE。支援 Windows 10 / 11 x64，建議放在「文件」等可寫入的位置，供程式保存設定與診斷紀錄。

1. 開啟解壓後的 `EchoMic/EchoMic.exe`（開發環境輸出位置為 `dist/EchoMic/EchoMic.exe`）。
2. 第一次在「音訊裝置」按「安裝虛擬裝置…」，在 Windows 管理員授權視窗按「是」，依官方安裝程式完成 **VB-Audio Hi-Fi Cable & ASIO Bridge** 安裝。這是新增一組獨立音訊端點。若要求重新啟動，請先儲存工作再自行重開機。
3. 在 Windows 音效控制台，確認 **Hi-Fi Cable Input**（播放）和 **Hi-Fi Cable Output**（錄製）的進階預設格式取樣率相同，建議 **48000 Hz**。程式也能重取樣至裝置的其他預設取樣率。保留平常的實體喇叭作為預設播放裝置。
4. 回到 Echo Mic 按「重新整理裝置」，選擇原始麥克風，勾選真正發聲的喇叭，再選新裝置 **Hi-Fi Cable Input**，按「啟動回音消除」。
5. Discord、OBS、遊戲或其他軟體的麥克風選 **Hi-Fi Cable Output (VB-Audio Hi-Fi Cable)**。這就是處理後的新麥克風。Windows 可能將前綴翻譯為本地語系。

介面分為「音訊裝置」、「音效與校正」與「一般設定」。右側顯示三路即時音量及通話軟體的麥克風選擇提示；底部的狀態、啟動與停止按鈕固定顯示。小視窗、較大的字型或較多音訊裝置時，設定區可用滑鼠滾輪或捲軸瀏覽。

支援 4K 與 Windows 高 DPI 縮放：程式使用 Per-Monitor V2 DPI 感知，字體以原生解析度繪製，控制項、間距與圖示依螢幕 DPI 同步調整。移到不同縮放比例的螢幕時會重新計算版面。更新後請從系統匣結束舊程式，再重新開啟新版 EXE。

```text
原始實體麥克風 ──────────────┐
                            ├─ WebRTC AEC ─ Hi-Fi Cable Input ─ Hi-Fi Cable Output ─ Discord/OBS
勾選的實體喇叭 ─ WASAPI 參考 ──┘

原有 CABLE Input / CABLE Output：保留原本用途
```

## 開機自動啟動與系統匣

- 按「開機自動啟動：已關閉」可開啟，再按一次可關閉。此設定只影響目前 Windows 使用者，不需要管理員權限。Windows 登入後會啟動 Echo Mic，縮到右下角系統匣，並使用上次按「啟動回音消除」時儲存的設定。
- 第一次請先選好裝置並成功啟動一次。登入後會等待原本的裝置約 30 秒；若尚未設定或裝置不齊，會顯示視窗讓你確認，不會自動改用其他麥克風。
- 「最小化替代關閉」預設勾選：按主視窗 X 會縮到系統匣，音訊與校正照常運作；取消勾選後，按 X 才會停止並結束程式。勾選狀態會立即儲存，下次開啟沿用。右下角圖示可能收在 Windows 的「顯示隱藏的圖示」內。
- 點擊系統匣圖示，或在圖示按右鍵選「開啟 Echo Mic」，即可恢復主視窗。再次點開 EXE 也會喚回原視窗，不會同時開兩個音訊處理程式。
- 系統匣右鍵選「結束 Echo Mic」一律會停止音訊並結束程式，不受「最小化替代關閉」設定影響。縮到系統匣不會自行啟動尚未開啟的回音消除；開機自動啟動仍會使用上次音訊設定自動開始輸出。
- 沒開 APP 時 Discord 仍可選 **Hi-Fi Cable Output**，因為虛擬音訊驅動仍在；但 Echo Mic 沒有執行、或未啟動回音消除時，就不會送出處理後的人聲。APP 在系統匣執行即可繼續使用。
- 啟用自動啟動後請保留程式位置。移動整個資料夾後，請在新位置將自動啟動關閉再開啟一次，更新登入啟動路徑。若曾在 Windows「啟動應用程式」停用 EchoMic，也需在 Windows 設定中重新允許。

## 調整與限制

- 程式必須保持開啟。停止或關閉後，新虛擬裝置仍存在，但不再收到本程式的音訊。
- 先以延遲 40 ms 使用。若仍有回音，停止後以 20 ms 為單位調整。USB、藍牙與螢幕喇叭的延遲不同；藍牙可能需更大的值。
- **預設延遲仍為 40 ms**，這是 AEC 的延遲提示參數，不代表整條麥克風處理路徑的總延遲。
- 可按「校正延遲（約 25 秒）」：先選一個原始麥克風與一個實體喇叭。程式會暫停虛擬麥克風輸出，透過選定喇叭播放約 20 秒內建語音，請保持安靜且不要調整喇叭音量；完成後恢復先前的運作狀態。
- 校正比較純 AEC 的多個延遲值，只有多個有效視窗中均有明確改善（中位數至少約 3 dB，且沒有明顯退步）才套用新值。量測到的聲學路徑延遲不會直接填入 AEC 參數。候選效果相近、喇叭太小聲、近端聲音過強或擷取中斷時都保留原設定。
- 校正會把量到的訊號偏移四捨五入至整數毫秒，加入該值及附近的細部候選。例如量到 50.1 ms 時，會實測 50 ms，也比較 49、51 ms 等相鄰值；AEC 介面本身接受整數毫秒。畫面分別顯示「測得訊號偏移」與「實際 AEC 設定」，避免把估計值誤認為已套用參數。
- 校正結果會儲存在程式旁的 `logs/calibration_*.json`，並把參數與裝置資訊保存在 `settings.json`；不會保存或上傳麥克風錄音。可按「取消校正」提前停止，原設定不變；取消後不會自行恢復輸出。
- 勾選每個真正發聲的喇叭。若音訊先經過原有 VB-CABLE 再送到喇叭，選擇最後實際播放的喇叭即可，避免把同一訊號重複加入參考。
- WASAPI 是逐一擷取播放端點，並非安裝 VB-CABLE 就會自動收到所有喇叭。未勾選裝置、獨佔模式或受保護內容可能無法取得完整參考。
- AEC 需要短暫收斂；喇叭破音、麥克風爆音、很強的房間反射與不同硬體的時鐘漂移會影響效果。音訊處理不保證所有房間都完全無回音。
- 採 10 ms 分段，含約 40 ms 的擷取對齊等待與輸出緩衝；端到端延遲仍會加上驅動及其他軟體的緩衝。
- 所有音訊只在本機記憶體處理，不錄音、不上傳。`logs` 只記錄裝置名稱、啟停及錯誤。`settings.json` 儲存上次選擇的裝置名稱與參數。
- 執行中更換裝置或喇叭時，請停止、重新整理，再啟動。
- 軟體的其他回音消除／降噪功能可能影響音質，可先停用重複處理，再比較效果。
- 如需自訂新裝置顯示名稱，可在 Windows 音效控制台的錄製裝置內容中將 Hi-Fi Cable Output 命名為「回音消除麥克風」。

## 開發與驗證

只有開發與重新建置需要 Python：Windows x64、Python 3.12。執行 `Build.ps1` 安裝隔離依賴、跑測試並建立可攜式資料夾和 `dist/EchoMic-Windows-x64.zip`，最後自動執行免 Python 的封裝檢查。ZIP 從乾淨的建置產物建立，不包含本機的 `settings.json`、操作紀錄或校正報告；更新 `dist/EchoMic` 則保留既有使用者設定。已安裝完整建置依賴時可加上 `-SkipDependencyInstall`，離線重建。

第一次從 Git 建置請執行：

```powershell
git clone https://github.com/wudishidove/simple_Acoustic_Echo_Cancellation.git
cd simple_Acoustic_Echo_Cancellation
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1
```

首次建置需要網路以安裝 Python 套件並下載官方 Hi-Fi Cable 驅動；建置腳本會核對安裝檔的固定 SHA-256。驅動安裝時另會檢查官方數位簽章。`assets/calibration_speech.wav` 是隨原始碼提供的合成測試語音，不是使用者錄音。

加上 `-PackageOnly` 可只建立並驗證分享用 ZIP，方便在本機 Echo Mic 仍執行時製作 Release，不更新正在使用的 `dist/EchoMic` 資料夾。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe echo_mic.py --list-devices
.\.venv\Scripts\python.exe echo_mic.py --smoke-test 5
.\dist\EchoMic\EchoMic.exe --self-check
.\Verify-Portable.ps1
```

合成測試驗證延遲與多路反射的回音抑制、近端訊號保留、時間戳記環形緩衝及原有 VB-CABLE 排除；另有 Windows 真實檔案鎖定、並行 JSON 讀寫與校正完成狀態的回歸測試。合成測試不代表已完成使用者房間的實測。

`--self-check` 會驗證封裝後的 AEC 原生模組、裝置列舉與介面初始化，結果寫入程式旁的 `logs/self-check.json`。`diagnose_capture.py` 則可在不輸出聲音、不儲存錄音的情況下驗證實體輸入與喇叭 loopback 擷取。

`Verify-Portable.ps1` 不需要 Python：它會將 ZIP 解壓至含中文與空白的獨立測試目錄，移除子程序的 Python 環境變數、將 PATH 限為 Windows 系統目錄，再驗證 EXE 的 UI、原生 AEC、系統匣與已取消的校正子程序。這是本機隔離檢查，仍建議正式散布前在乾淨的 Windows 電腦測試。

## 背景診斷（AM310 + Q serial）

執行 `Start-Debug.ps1`，會在背景診斷最多 10 分鐘；以 `Stop-Debug.ps1` 可提前停止。診斷程式不送音訊到虛擬麥克風，因此可以與正式 EchoMic 並行。每次分析最多保留一個 10 秒視窗的音訊於記憶體，不保存或上傳錄音。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Debug.ps1 -Seconds 600
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Stop-Debug.ps1
```

`logs/debug_current.json` 指向本次報告資料夾；`status.json` 每秒更新，`metrics.jsonl` 每 10 秒增加一筆統計，結束後產生 `summary.json`。欄位包含參考訊號覆蓋率、串流遺失、麥克風與喇叭聲的相關性、估計聲學延遲，以及各個 AEC 延遲值的喇叭相關成分抑制量。

診斷分別運行純 AEC 與目前 AEC 加降噪設定，不把整體音量下降直接當作回音消除。只有喇叭參考足夠、與麥克風相關時才估算抑制量；估計值不代表雙向說話時的人聲品質。沒有保存音訊，因此不能在事後回放聆聽。

`play_probe.py` 可將 `assets/calibration_speech.wav` 的本機合成語音透過 Q serial 播放，用於實際房間測試。播放峰值固定為約 -14 dBFS；最終聽感仍取決於喇叭音量。這個測試 WAV 是合成音檔，不是使用者麥克風錄音。

## 第三方元件

- [WebRTC Python AEC 封裝](https://pypi.org/project/aec-audio-processing/)：BSD-3-Clause。
- [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)：WASAPI loopback 擷取。
- [VB-Audio Hi-Fi Cable 官方說明及下載](https://vb-audio.com/Cable/)：獨立虛擬驅動，終端使用者可免費使用，遵循原廠授權。此專案的 AEC 程式不包含自行簽署的核心驅動。

官方驅動原始 ZIP 下載網址：`https://download.vb-audio.com/Download_CABLE/HiFiCableAsioBridgeSetup_v1007.zip`。
安裝工具會驗證官方安裝 EXE 的 SHA-256 與 Vincent Burel 數位簽章。
解除安裝可在 Windows「應用程式與功能」移除 VB-Audio Hi-Fi Cable & ASIO Bridge；不必解除安裝現有 VB-CABLE。
