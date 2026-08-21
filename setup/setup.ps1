[CmdletBinding()]
param(
    [ValidateSet('menu','node','network-server','network-client','llama','tests')]
    [string]$Mode='menu',
    [ValidateSet('auto','de','en')]
    [string]$Language='auto'
)
$ErrorActionPreference='Stop'
$RepoRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
. (Join-Path $PSScriptRoot 'network.ps1')
. (Join-Path $PSScriptRoot 'llama.ps1')
Initialize-Setup -RequestedLanguage $Language -RequestedMode $Mode
try {
    switch ($Mode) {
        'menu' { Show-SetupMenu }
        'node' { Invoke-NodeSetup }
        'network-server' { Invoke-NetworkServer }
        'network-client' { Invoke-NetworkClient }
        'llama' { Invoke-LlamaSetup }
        'tests' { Invoke-AllTests }
    }
} catch {
    Write-Host ''; Write-Host $_.Exception.Message -ForegroundColor Red
    if ($Host.Name -match 'ConsoleHost') { [void](Read-Host (T 'Press')) }
    exit 1
}
