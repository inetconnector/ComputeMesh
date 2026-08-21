function Select-LocalFile([string]$Filter, [string]$Title) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $d = New-Object System.Windows.Forms.OpenFileDialog; $d.Filter = $Filter; $d.Title = $Title; $d.CheckFileExists = $true
        if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { return $d.FileName }
    } catch {}
    return (Read-Host $Title)
}
function Verify-Asset($Asset, [string]$Path) {
    if ($Asset.digest -and [string]$Asset.digest -match '^sha256:([0-9a-fA-F]{64})$') {
        $expected = $Matches[1].ToLowerInvariant(); $actual = (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw (T 'ShaFail') }
    }
}
function Install-OfficialLlama {
    Write-Host (T 'DownloadLlama')
    $root = Join-Path $RepoRoot 'artifacts\lab\runtime\llama.cpp'; New-Item -ItemType Directory -Force -Path $root | Out-Null
    $release = Invoke-RestMethod -Headers @{ 'User-Agent'='ComputeMesh-Lab-Setup' } -Uri 'https://api.github.com/repos/ggml-org/llama.cpp/releases/latest'
    $hasNvidia = [bool](Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)
    $mainAsset = $null; $runtimeAsset = $null
    if ($hasNvidia) {
        $mainAsset = $release.assets | Where-Object { $_.name -match '^llama-.*-bin-win-cuda-12\.4-x64\.zip$' } | Select-Object -First 1
        $runtimeAsset = $release.assets | Where-Object { $_.name -match '^cudart-llama-bin-win-cuda-12\.4-x64\.zip$' } | Select-Object -First 1
    }
    if (-not $mainAsset) {
        $mainAsset = $release.assets | Where-Object { $_.name -match '^llama-.*-bin-win-vulkan-x64\.zip$' } | Select-Object -First 1
        $runtimeAsset = $null
    }
    if (-not $mainAsset) { throw (T 'NoLlamaAsset') }
    $dest = Join-Path $root $release.tag_name; New-Item -ItemType Directory -Force -Path $dest | Out-Null
    foreach ($asset in @($mainAsset,$runtimeAsset) | Where-Object { $_ }) {
        $zip = Join-Path $root $asset.name
        Write-Host ('Downloading: ' + $asset.name)
        Invoke-WebRequest -UseBasicParsing -Headers @{ 'User-Agent'='ComputeMesh-Lab-Setup' } -Uri $asset.browser_download_url -OutFile $zip
        Verify-Asset $asset $zip; Expand-Archive -Path $zip -DestinationPath $dest -Force; Remove-Item $zip -Force
    }
    $bench = Get-ChildItem -Path $dest -Filter 'llama-bench.exe' -File -Recurse | Select-Object -First 1
    if (-not $bench) { throw 'llama-bench.exe not found after extraction.' }
    return $bench.FullName
}
function Find-Llama {
    $status = Get-LabStatus
    if ($status.llama_bench -and (Test-Path $status.llama_bench)) { return $status.llama_bench }
    $cmd = Get-Command llama-bench.exe -ErrorAction SilentlyContinue; if ($cmd) { return $cmd.Source }
    $found = Get-ChildItem (Join-Path $RepoRoot 'artifacts\lab\runtime') -Filter 'llama-bench.exe' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) { return $found.FullName }; return $null
}
function Invoke-LlamaSetup {
    Write-Heading; [void](Invoke-Lab @('status')); $bench = Find-Llama
    if (-not $bench) {
        Write-Host ('1. ' + (T 'AutoLlama')); Write-Host ('2. ' + (T 'BrowseLlama'))
        $choice = Read-Host (T 'Choice')
        if (-not $choice -or $choice -eq '1') { try { $bench = Install-OfficialLlama } catch { Write-Host $_.Exception.Message -ForegroundColor Yellow } }
        if (-not $bench) { $bench = Select-LocalFile 'llama-bench.exe|llama-bench.exe|Executables (*.exe)|*.exe' (T 'PickLlama') }
    }
    if (-not $bench -or -not (Test-Path $bench)) { Write-Host (T 'Cancelled'); return }
    $status = Get-LabStatus; $model = $null
    if ($status.model_path -and (Test-Path $status.model_path)) { $model = $status.model_path }
    if (-not $model) { $model = Select-LocalFile 'GGUF model (*.gguf)|*.gguf|All files (*.*)|*.*' (T 'PickModel') }
    if (-not $model -or -not (Test-Path $model)) { Write-Host (T 'Cancelled'); return }
    $lines = Invoke-Lab @('llama','--llama-bench',$bench,'--model',$model)
    $r = $lines | Select-Object -Last 1 | ConvertFrom-Json
    Write-Host ''; Write-Host ((T 'Results') + ': ' + $r.path) -ForegroundColor Green
    Show-BenchmarkSummary $r.path 'llama'; Pause-Ui
}
