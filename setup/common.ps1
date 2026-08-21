$script:Mode = 'menu'
$script:Language = 'en'
$script:VenvDir = Join-Path $RepoRoot '.venv'
$script:VenvPython = Join-Path $script:VenvDir 'Scripts\python.exe'
$script:LabHelper = Join-Path $PSScriptRoot 'lab.py'
$script:DefaultPort = 43191
$script:SetupEntrypoint = Join-Path $PSScriptRoot 'setup.ps1'

$script:Text = @{
    de = @{
        Title='ComputeMesh Lab Setup'; Menu='Was möchtest du tun?'; Node='Diesen Rechner vorbereiten und Profil erstellen'; Server='Netzwerktest: dieser Rechner wartet (Server / Node B)'; Client='Netzwerktest: Verbindung zum anderen Rechner messen (Client / Node A)'; Llama='llama.cpp Prefill/Decode messen'; Tests='Alle lokalen Tests ausführen'; Exit='Beenden'; Choice='Auswahl'; Press='Enter drücken zum Fortfahren'; PythonMissing='Python 3.10+ fehlt. Installation über winget wird versucht.'; NoWinget='winget fehlt. Bitte Python 3.10+ installieren und SETUP.cmd erneut starten.'; Preparing='Lokale Python-Umgebung wird vorbereitet...'; Done='Fertig.'; Results='Ergebnisse'; Summary='Kurzergebnis'; TestsInstall='Test-Abhängigkeiten werden nur in .venv installiert.'; Profile='Profil'; Memory='RAM'; Rtt='RTT p50 / p95'; Throughput='Upload / Download'; Prefill='Prefill'; Decode='Decode'; Cancelled='Abgebrochen.'; NeedPrivate='Nur in einem vertrauenswürdigen privaten LAN ausführen.'; PublicNetwork='Windows stuft dieses Netzwerk nicht als Privat ein.'; MakePrivate='Dieses Netzwerk jetzt auf Privat umstellen? [J/n]'; Admin='Für den LAN-Server wird einmal Administratorfreigabe benötigt.'; ServerIp='IP dieses Rechners'; ServerInstruction='Auf dem anderen Rechner SETUP.cmd starten, Client wählen und diese IP eingeben.'; Firewall='Port 43191 wird nur temporär für LocalSubnet/Privat geöffnet und danach wieder geschlossen.'; EnterIp='IP des Server-Rechners'; InvalidPrivateIp='Private LAN-IP eingeben (10.x, 172.16-31.x oder 192.168.x).'; AutoLlama='Offizielles llama.cpp automatisch herunterladen'; BrowseLlama='Vorhandene llama-bench.exe auswählen'; DownloadLlama='Neueste offizielle llama.cpp-Windows-Version wird geladen...'; NoLlamaAsset='Kein passendes offizielles Windows-llama.cpp-Paket gefunden.'; PickLlama='llama-bench.exe auswählen'; PickModel='GGUF-Modelldatei auswählen'; ShaFail='SHA256-Prüfung fehlgeschlagen.'
    }
    en = @{
        Title='ComputeMesh Lab Setup'; Menu='What do you want to do?'; Node='Prepare this computer and capture its profile'; Server='Network test: wait here (Server / Node B)'; Client='Network test: measure the other computer (Client / Node A)'; Llama='Measure llama.cpp prefill/decode'; Tests='Run all local tests'; Exit='Exit'; Choice='Choice'; Press='Press Enter to continue'; PythonMissing='Python 3.10+ is missing. Setup will try winget.'; NoWinget='winget is unavailable. Install Python 3.10+ and run SETUP.cmd again.'; Preparing='Preparing local Python environment...'; Done='Done.'; Results='Results'; Summary='Summary'; TestsInstall='Test dependencies are installed only into .venv.'; Profile='Profile'; Memory='RAM'; Rtt='RTT p50 / p95'; Throughput='Upload / Download'; Prefill='Prefill'; Decode='Decode'; Cancelled='Cancelled.'; NeedPrivate='Run only on a trusted private LAN.'; PublicNetwork='Windows does not classify this network as Private.'; MakePrivate='Change this network to Private now? [Y/n]'; Admin='The LAN server needs one administrator approval.'; ServerIp='This computer IP'; ServerInstruction='On the other computer run SETUP.cmd, choose Client, and enter this IP.'; Firewall='Port 43191 is opened only temporarily for LocalSubnet/Private and closed afterwards.'; EnterIp='Server computer IP'; InvalidPrivateIp='Enter a private LAN IP (10.x, 172.16-31.x, or 192.168.x).'; AutoLlama='Download official llama.cpp automatically'; BrowseLlama='Choose existing llama-bench.exe'; DownloadLlama='Downloading latest official llama.cpp Windows release...'; NoLlamaAsset='No suitable official Windows llama.cpp package found.'; PickLlama='Choose llama-bench.exe'; PickModel='Choose GGUF model file'; ShaFail='SHA256 verification failed.'
    }
}

function Initialize-Setup([string]$RequestedLanguage, [string]$RequestedMode) {
    $script:Mode = $RequestedMode
    if ($RequestedLanguage -eq 'auto') {
        try { $script:Language = (Get-Culture).TwoLetterISOLanguageName } catch { $script:Language = 'en' }
        if ($script:Language -ne 'de') { $script:Language = 'en' }
    } else { $script:Language = $RequestedLanguage }
}
function T([string]$Key) { return $script:Text[$script:Language][$Key] }
function Write-Heading { Clear-Host; Write-Host ('=' * 64); Write-Host ('  ' + (T 'Title')); Write-Host ('=' * 64); Write-Host '' }
function Pause-Ui { if ($script:Mode -eq 'menu') { [void](Read-Host (T 'Press')) } }

function Test-Python([string]$Exe, [string[]]$Prefix = @()) {
    try {
        $v = & $Exe @Prefix -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if (-not $v) { return $false }
        $p = $v.Trim().Split('.')
        return ([int]$p[0] -gt 3 -or ([int]$p[0] -eq 3 -and [int]$p[1] -ge 10))
    } catch { return $false }
}
function Find-Python {
    if ((Get-Command py.exe -ErrorAction SilentlyContinue) -and (Test-Python 'py.exe' @('-3'))) { return @{ Exe='py.exe'; Prefix=@('-3') } }
    if ((Get-Command python.exe -ErrorAction SilentlyContinue) -and (Test-Python 'python.exe')) { return @{ Exe='python.exe'; Prefix=@() } }
    foreach ($p in @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
    )) {
        if ((Test-Path $p) -and (Test-Python $p)) { return @{ Exe=$p; Prefix=@() } }
    }
    return $null
}
function Ensure-Python {
    if ((Test-Path $script:VenvPython) -and (Test-Python $script:VenvPython)) { return $script:VenvPython }
    $candidate = Find-Python
    if (-not $candidate) {
        Write-Host (T 'PythonMissing') -ForegroundColor Yellow
        if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw (T 'NoWinget') }
        foreach ($id in @('Python.Python.3.13','Python.Python.3.12')) {
            & winget.exe install --id $id -e --scope user --accept-package-agreements --accept-source-agreements --silent
            if ($LASTEXITCODE -eq 0) { break }
        }
        $candidate = Find-Python
        if (-not $candidate) { throw (T 'NoWinget') }
    }
    Write-Host (T 'Preparing')
    $args = @($candidate.Prefix) + @('-m','venv',$script:VenvDir)
    & $candidate.Exe @args
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $script:VenvPython)) {
        if ((Test-Path $script:VenvPython) -and (Test-Python $script:VenvPython)) { return $script:VenvPython }
        throw 'Unable to create .venv'
    }
    return $script:VenvPython
}
function Invoke-Lab([string[]]$CommandArgs) {
    $python = Ensure-Python
    Push-Location $RepoRoot
    try {
        $lines = & $python $script:LabHelper @CommandArgs
        if ($LASTEXITCODE -ne 0) { throw "Lab helper failed ($LASTEXITCODE)" }
        if ($lines) { $lines | ForEach-Object { Write-Host $_ } }
        return $lines
    } finally { Pop-Location }
}
function Get-LabStatus {
    $python = Ensure-Python
    $line = & $python $script:LabHelper status | Select-Object -Last 1
    return ($line | ConvertFrom-Json)
}
function Show-BenchmarkSummary([string]$Path, [string]$Kind) {
    if (-not $Path -or -not (Test-Path $Path)) { return }
    Write-Host ''; Write-Host ((T 'Summary') + ':') -ForegroundColor Cyan
    try {
        if ($Kind -eq 'inventory') {
            $d = Get-Content -Raw (Join-Path $Path 'node_profile.json') | ConvertFrom-Json
            $gpu = if ($d.devices -and $d.devices.Count -gt 0) { ($d.devices | ForEach-Object { $_.name }) -join ', ' } else { '-' }
            Write-Host ('  CPU: ' + $d.cpu.model); Write-Host ('  GPU: ' + $gpu)
            Write-Host ("  $(T 'Memory'): $([math]::Round([double]$d.memory.total_bytes / 1GB, 1)) GB")
        } elseif ($Kind -eq 'network') {
            $f = Get-ChildItem $Path -Filter 'network_*.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            $d = Get-Content -Raw $f.FullName | ConvertFrom-Json
            Write-Host ("  $(T 'Rtt'): $($d.metrics.rtt_ms_p50) / $($d.metrics.rtt_ms_p95) ms")
            Write-Host ("  $(T 'Throughput'): $($d.metrics.upload_mbps_p50) / $($d.metrics.download_mbps_p50) Mbit/s")
        } elseif ($Kind -eq 'llama') {
            $all = Get-ChildItem $Path -Filter 'benchmark_*.json' | ForEach-Object { Get-Content -Raw $_.FullName | ConvertFrom-Json }
            $p = $all | Where-Object benchmark_name -eq 'llama_cpp_prefill' | Select-Object -First 1
            $d = $all | Where-Object benchmark_name -eq 'llama_cpp_decode' | Select-Object -First 1
            if ($p) { Write-Host ("  $(T 'Prefill'): $($p.metrics.prefill_tokens_per_second_avg) tokens/s") }
            if ($d) { Write-Host ("  $(T 'Decode'): $($d.metrics.decode_tokens_per_second_avg) tokens/s, $($d.metrics.inter_token_ms_avg) ms/token") }
        }
    } catch { Write-Host $_.Exception.Message -ForegroundColor Yellow }
}
function Invoke-NodeSetup {
    Write-Heading
    $lines = Invoke-Lab @('inventory')
    $r = $lines | Select-Object -Last 1 | ConvertFrom-Json
    Write-Host ''; Write-Host ((T 'Results') + ': ' + $r.path) -ForegroundColor Green
    Show-BenchmarkSummary $r.path 'inventory'; Pause-Ui
}
function Invoke-AllTests {
    Write-Heading; $python = Ensure-Python; Write-Host (T 'TestsInstall')
    Push-Location $RepoRoot
    try {
        & $python -m pip install -r requirements-dev.txt
        if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
        & $python $script:LabHelper tests
        if ($LASTEXITCODE -ne 0) { throw 'tests failed' }
    } finally { Pop-Location }
    Write-Host (T 'Done') -ForegroundColor Green; Pause-Ui
}
function Show-SetupMenu {
    while ($true) {
        Write-Heading; Write-Host (T 'Menu'); Write-Host ''
        Write-Host "1. $(T 'Node')"; Write-Host "2. $(T 'Server')"; Write-Host "3. $(T 'Client')"; Write-Host "4. $(T 'Llama')"; Write-Host "5. $(T 'Tests')"; Write-Host "0. $(T 'Exit')"
        switch (Read-Host (T 'Choice')) { '1' { Invoke-NodeSetup }; '2' { Invoke-NetworkServer }; '3' { Invoke-NetworkClient }; '4' { Invoke-LlamaSetup }; '5' { Invoke-AllTests }; '0' { return } }
    }
}
