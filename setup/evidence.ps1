[CmdletBinding()]
param(
    [ValidateSet('export','bundle')]
    [string]$Mode='export',
    [ValidateSet('auto','de','en')]
    [string]$Language='auto'
)
$ErrorActionPreference='Stop'
$RepoRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
. (Join-Path $PSScriptRoot 'llama.ps1')
Initialize-Setup -RequestedLanguage $Language -RequestedMode $Mode

function Ensure-BundleDependency {
    $python = Ensure-Python
    & $python -c 'import jsonschema' 2>$null
    if ($LASTEXITCODE -eq 0) { return }
    Write-Host 'Installing the small JSON-schema dependency into .venv...'
    & $python -m pip install 'jsonschema>=4.23,<5'
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install jsonschema into .venv.' }
}

function Invoke-EvidenceExport {
    Write-Heading
    $lines = Invoke-Lab @('export')
    $r = $lines | Select-Object -Last 1 | ConvertFrom-Json
    Write-Host ''
    Write-Host ((T 'Results') + ': ' + $r.path) -ForegroundColor Green
    if ($Language -eq 'de' -or ($Language -eq 'auto' -and (Get-Culture).TwoLetterISOLanguageName -eq 'de')) {
        Write-Host 'Diese ZIP-Datei auf den Coordinator-Rechner kopieren. Sie enthält keine GGUF-Modellgewichte.'
    } else {
        Write-Host 'Copy this ZIP to the coordinator computer. It contains no GGUF model weights.'
    }
}

function Invoke-EvidenceBundle {
    Write-Heading
    Ensure-BundleDependency
    $peer = Select-LocalFile 'ComputeMesh evidence export (*.zip)|*.zip|ZIP (*.zip)|*.zip' 'Choose peer evidence export ZIP'
    if (-not $peer -or -not (Test-Path $peer)) { throw 'Peer export ZIP not selected.' }
    $manifest = Select-LocalFile 'Model manifest (*.json)|*.json|JSON (*.json)|*.json' 'Choose ComputeMesh model manifest JSON'
    if (-not $manifest -or -not (Test-Path $manifest)) { throw 'Model manifest not selected.' }
    $lines = Invoke-Lab @('bundle','--peer-export',$peer,'--model-manifest',$manifest)
    $r = $lines | Select-Object -Last 1 | ConvertFrom-Json
    Write-Host ''
    Write-Host ((T 'Results') + ': ' + $r.path) -ForegroundColor Green
    Write-Host ('Peer node: ' + $r.peer_node_id)
}

try {
    if ($Mode -eq 'export') { Invoke-EvidenceExport } else { Invoke-EvidenceBundle }
} catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
