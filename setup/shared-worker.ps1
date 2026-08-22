[CmdletBinding()]
param(
    [ValidateSet('auto','de','en')]
    [string]$Language='auto'
)
$ErrorActionPreference='Stop'
$RepoRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
. (Join-Path $PSScriptRoot 'llama.ps1')
. (Join-Path $PSScriptRoot 'network.ps1')
Initialize-Setup -RequestedLanguage $Language -RequestedMode 'shared-worker'

function Find-RpcServer([string]$Preferred='') {
    $names = @('rpc-server.exe','ggml-rpc-server.exe')
    if ($Preferred -and (Test-Path $Preferred)) {
        $dir = Split-Path -Parent $Preferred
        foreach ($name in $names) {
            $direct = Join-Path $dir $name
            if (Test-Path $direct -PathType Leaf) { return $direct }
        }
        foreach ($name in $names) {
            $found = Get-ChildItem -Path $dir -Filter $name -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }
    $runtime = Join-Path $RepoRoot 'artifacts\lab\runtime\llama.cpp'
    if (Test-Path $runtime) {
        foreach ($name in $names) {
            $found = Get-ChildItem -Path $runtime -Filter $name -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }
    foreach ($name in $names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

try {
    Write-Heading
    Write-Host 'ComputeMesh M1 shared worker' -ForegroundColor Cyan
    Write-Host 'Trusted private LAN only. Never expose llama.cpp RPC to the public internet.' -ForegroundColor Yellow

    if (-not (Test-IsAdmin)) {
        Write-Host 'Administrator rights are needed only for the temporary private-LAN firewall rule.' -ForegroundColor Yellow
        $uacArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Language $Language"
        Start-Process powershell.exe -Verb RunAs -ArgumentList $uacArgs
        exit 0
    }

    $info = Get-PrivateLanInfo
    $profile = Get-NetConnectionProfile -InterfaceIndex $info.InterfaceIndex -ErrorAction SilentlyContinue
    if ($profile -and $profile.NetworkCategory -ne 'Private') {
        $answer = Read-Host 'Windows marks this LAN as Public. Change it to Private for this lab? [y/N]'
        if ($answer.ToLowerInvariant() -notin @('y','yes','j','ja')) { throw 'Cancelled because the LAN profile is not Private.' }
        Set-NetConnectionProfile -InterfaceIndex $info.InterfaceIndex -NetworkCategory Private
    }

    $bench = Find-Llama
    $rpc = Find-RpcServer $bench
    if (-not $rpc) { $rpc = Select-LocalFile 'RPC server (*.exe)|rpc-server.exe;ggml-rpc-server.exe|Executables (*.exe)|*.exe' 'Choose rpc-server.exe / ggml-rpc-server.exe' }
    if (-not $rpc -or -not (Test-Path $rpc -PathType Leaf)) { throw 'RPC server executable not selected.' }

    $python = Ensure-Python
    $port = 50052
    $threads = [Math]::Max(1, [Environment]::ProcessorCount)
    $rule = 'ComputeMesh M1 RPC Worker 50052'
    Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -LocalAddress $info.IP -RemoteAddress LocalSubnet -Profile Private -Program $rpc | Out-Null
    try {
        $endpoint = $info.IP + ':' + $port
        Write-Host ''
        Write-Host ('Worker RPC endpoint: ' + $endpoint) -ForegroundColor Green
        Write-Host ('CPU threads if CPU fallback is used: ' + $threads)
        try { Set-Clipboard -Value $info.IP } catch {}
        Write-Host 'Keep this window open while the coordinator runs SHARED-PROOF.cmd. Ctrl+C stops the worker.'
        Push-Location $RepoRoot
        try { & $python -m runtime.llama.rpc_spike worker --rpc-server $rpc --bind $info.IP --port $port --threads $threads }
        finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
        Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
    }
} catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
