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
Initialize-Setup -RequestedLanguage $Language -RequestedMode 'shared-proof'

function Ensure-JsonSchema {
    $python = Ensure-Python
    & $python -c 'import jsonschema' 2>$null
    if ($LASTEXITCODE -eq 0) { return $python }
    Write-Host 'Installing the small JSON-schema dependency into .venv...'
    & $python -m pip install 'jsonschema>=4.23,<5'
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install jsonschema into .venv.' }
    return $python
}

function Find-RuntimeBinary([string[]]$Names, [string]$Preferred='') {
    if ($Preferred -and (Test-Path $Preferred)) {
        $dir = Split-Path -Parent $Preferred
        foreach ($name in $Names) {
            $direct = Join-Path $dir $name
            if (Test-Path $direct -PathType Leaf) { return $direct }
        }
        foreach ($name in $Names) {
            $found = Get-ChildItem -Path $dir -Filter $name -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }
    $runtime = Join-Path $RepoRoot 'artifacts\lab\runtime\llama.cpp'
    if (Test-Path $runtime) {
        foreach ($name in $Names) {
            $found = Get-ChildItem -Path $runtime -Filter $name -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }
    foreach ($name in $Names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

try {
    Write-Heading
    Write-Host 'ComputeMesh M1 shared proof - coordinator' -ForegroundColor Cyan
    Write-Host 'Trusted private LAN only. The upstream llama.cpp RPC socket is not authenticated.' -ForegroundColor Yellow
    $python = Ensure-JsonSchema
    $status = Get-LabStatus

    $bundle = Select-LocalFile 'Experiment bundle (*.json)|*.json|JSON (*.json)|*.json' 'Choose current experiment_bundle.json'
    if (-not $bundle -or -not (Test-Path $bundle -PathType Leaf)) { throw 'Experiment bundle not selected.' }

    $model = $null
    if ($status.model_path -and (Test-Path $status.model_path -PathType Leaf)) { $model = $status.model_path }
    if (-not $model) { $model = Select-LocalFile 'GGUF model (*.gguf)|*.gguf|All files (*.*)|*.*' 'Choose the exact GGUF used for the bundle' }
    if (-not $model -or -not (Test-Path $model -PathType Leaf)) { throw 'GGUF model not selected.' }

    $bench = Find-Llama
    $server = Find-RuntimeBinary @('llama-server.exe') $bench
    if (-not $server) { $server = Select-LocalFile 'llama-server.exe|llama-server.exe|Executables (*.exe)|*.exe' 'Choose llama-server.exe from the same llama.cpp build' }
    if (-not $server -or -not (Test-Path $server -PathType Leaf)) { throw 'llama-server.exe not selected.' }
    $cli = Find-RuntimeBinary @('llama-cli.exe') $server

    $workerIp = ''
    try {
        $clip = (Get-Clipboard -Raw -ErrorAction Stop).Trim()
        if (Test-PrivateIPv4 $clip) { $workerIp = $clip }
    } catch {}
    while (-not (Test-PrivateIPv4 $workerIp)) {
        $workerIp = (Read-Host 'Worker private IPv4').Trim()
        if (-not (Test-PrivateIPv4 $workerIp)) { Write-Host 'Enter an RFC1918 private IPv4 address.' -ForegroundColor Yellow }
    }
    $worker = $workerIp + ':50052'

    $stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmssZ')
    $nodeRoot = Join-Path (Join-Path $RepoRoot 'artifacts\lab') $status.node_id
    $output = Join-Path $nodeRoot ($stamp + '-shared-proof')

    $trialArgs = @('-m','runtime.llama.shared_trial','--bundle',$bundle,'--llama-server',$server,'--model',$model,'--worker-rpc',$worker,'--output-dir',$output)
    if ($cli -and (Test-Path $cli -PathType Leaf)) { $trialArgs += @('--llama-cli',$cli) }
    Push-Location $RepoRoot
    try { & $python @trialArgs }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) {
        Write-Host ('Trial artifacts/failure record: ' + $output) -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
    Write-Host ''
    Write-Host ('Shared proof: ' + (Join-Path $output 'shared_run_evidence.json')) -ForegroundColor Green
    Write-Host ('Comparison: ' + (Join-Path $output 'comparison.json'))
} catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
