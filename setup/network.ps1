function Test-PrivateIPv4([string]$Ip) {
    $addr = $null
    if (-not [Net.IPAddress]::TryParse($Ip, [ref]$addr) -or $addr.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { return $false }
    $b = $addr.GetAddressBytes()
    return (($b[0] -eq 10) -or ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31) -or ($b[0] -eq 192 -and $b[1] -eq 168))
}
function Get-PrivateLanInfo {
    foreach ($c in (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway })) {
        foreach ($x in $c.IPv4Address) {
            if (Test-PrivateIPv4 $x.IPAddress) { return @{ IP=$x.IPAddress; InterfaceIndex=$c.InterfaceIndex } }
        }
    }
    throw 'No private IPv4 LAN interface with a default gateway was found.'
}
function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Invoke-NetworkServer {
    Write-Heading; Write-Host (T 'NeedPrivate') -ForegroundColor Yellow
    if (-not (Test-IsAdmin)) {
        Write-Host (T 'Admin') -ForegroundColor Yellow
        $args = "-NoProfile -ExecutionPolicy Bypass -File `"$script:SetupEntrypoint`" -Mode network-server -Language $script:Language"
        Start-Process powershell.exe -Verb RunAs -ArgumentList $args
        return
    }
    [void](Invoke-Lab @('status'))
    $info = Get-PrivateLanInfo
    $profile = Get-NetConnectionProfile -InterfaceIndex $info.InterfaceIndex -ErrorAction SilentlyContinue
    if ($profile -and $profile.NetworkCategory -ne 'Private') {
        Write-Host (T 'PublicNetwork') -ForegroundColor Yellow
        $answer = Read-Host (T 'MakePrivate')
        if ($answer -and $answer.ToLowerInvariant() -notin @('j','y','yes','ja')) { Write-Host (T 'Cancelled'); return }
        Set-NetConnectionProfile -InterfaceIndex $info.InterfaceIndex -NetworkCategory Private
    }
    $python = Ensure-Python; $rule = "ComputeMesh Lab $script:DefaultPort"
    Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP -LocalPort $script:DefaultPort -LocalAddress $info.IP -RemoteAddress LocalSubnet -Profile Private -Program $python | Out-Null
    Write-Host ''; Write-Host ((T 'ServerIp') + ': ' + $info.IP) -ForegroundColor Cyan
    try { Set-Clipboard -Value $info.IP } catch {}
    Write-Host (T 'ServerInstruction')
    Write-Host (T 'Firewall')
    try { [void](Invoke-Lab @('network-server','--bind',$info.IP,'--port',"$script:DefaultPort")) }
    finally { Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue }
    Write-Host (T 'Done') -ForegroundColor Green; Pause-Ui
}
function Invoke-NetworkClient {
    Write-Heading; Write-Host (T 'NeedPrivate') -ForegroundColor Yellow; [void](Invoke-Lab @('status'))
    $ip = ''
    try { $clip = (Get-Clipboard -Raw -ErrorAction Stop).Trim(); if (Test-PrivateIPv4 $clip) { $ip = $clip } } catch {}
    while (-not (Test-PrivateIPv4 $ip)) {
        $ip = Read-Host (T 'EnterIp')
        if (-not (Test-PrivateIPv4 $ip)) { Write-Host (T 'InvalidPrivateIp') -ForegroundColor Yellow }
    }
    $lines = Invoke-Lab @('network-client','--host',$ip,'--port',"$script:DefaultPort")
    $r = $lines | Select-Object -Last 1 | ConvertFrom-Json
    Write-Host ''; Write-Host ((T 'Results') + ': ' + $r.path) -ForegroundColor Green
    Show-BenchmarkSummary $r.path 'network'; Pause-Ui
}
