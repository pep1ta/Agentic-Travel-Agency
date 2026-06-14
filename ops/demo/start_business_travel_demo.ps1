#Requires -Version 5.1
# ops/demo/start_business_travel_demo.ps1
#
# Starts all local Business Travel demo services in separate PowerShell windows.
# Services are started in dependency order with TCP/HTTP health checks between phases.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1
#   powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1 -StopExistingPython
#
# After starting, verify with:
#   powershell -ExecutionPolicy Bypass -File ops/demo/check_business_travel_demo.ps1
#
# Then run the integration test:
#   uv run python test/business_travel/integration/verify_business_travel.py

param(
    [switch]$StopExistingPython
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $ProjectRoot

# ---------------------------------------------------------------------------
# Start-DemoService
# ---------------------------------------------------------------------------
# Opens a new PowerShell window, sets env vars, and runs a command.
#
# WHY -EncodedCommand:
#   Start-Process -ArgumentList passes the command string to powershell.exe via the
#   Windows CreateProcess API. If the string contains double-quoted URLs like
#   "http://localhost:8004/sse", the Win32 argument parser splits them at the quotes,
#   turning the URL into a bare word that PowerShell tries to execute as a command.
#   Base64-encoding the entire script (UTF-16LE = -EncodedCommand format) avoids
#   every quoting layer completely.
# ---------------------------------------------------------------------------

function Start-DemoService {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Command,
        [hashtable]$EnvVars = @{}
    )

    Write-Host "  Starting $Name..."

    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("Set-Location '$ProjectRoot'")
    $lines.Add("`$host.UI.RawUI.WindowTitle = '$Name'")

    # Env vars are embedded with single-quote delimiters so URLs (with colons and
    # slashes) are never parsed as commands by PowerShell in the child window.
    foreach ($key in $EnvVars.Keys) {
        $val = $EnvVars[$key]
        $lines.Add("`$env:$key = '$val'")
    }
    $lines.Add($Command)

    $script = $lines -join "`n"
    $bytes  = [System.Text.Encoding]::Unicode.GetBytes($script)
    $encoded = [Convert]::ToBase64String($bytes)

    Start-Process powershell -ArgumentList @(
        "-NoExit", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encoded
    )
}

# ---------------------------------------------------------------------------
# Wait-ForTcpPort  — blocks until a TCP port responds or timeout
# ---------------------------------------------------------------------------

function Wait-ForTcpPort {
    param(
        [Parameter(Mandatory)][int]$Port,
        [string]$HostName = "localhost",
        [int]$TimeoutSeconds = 30
    )
    Write-Host "    TCP :$Port" -NoNewline
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect($HostName, $Port)
            $tcp.Close()
            Write-Host " OK"
            return
        } catch {
            Write-Host "." -NoNewline
            Start-Sleep -Milliseconds 500
        }
    }
    Write-Host " TIMEOUT"
    throw "Timeout: TCP port $Port on $HostName not reachable after ${TimeoutSeconds}s."
}

# ---------------------------------------------------------------------------
# Wait-ForHttpOk  — blocks until an HTTP 200 is returned or timeout
# ---------------------------------------------------------------------------

function Wait-ForHttpOk {
    param(
        [Parameter(Mandatory)][string]$Url,
        [int]$TimeoutSeconds = 60
    )
    Write-Host "    $Url" -NoNewline
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -eq 200) {
                Write-Host " OK"
                return
            }
        } catch {
            Write-Host "." -NoNewline
            Start-Sleep -Milliseconds 500
        }
    }
    Write-Host " TIMEOUT"
    throw "Timeout: $Url not responding after ${TimeoutSeconds}s."
}

# ---------------------------------------------------------------------------
# Port conflict check
# ---------------------------------------------------------------------------

$DemoPorts = @(8004, 8005, 8006, 10010, 10011, 10012, 10004, 10002, 10000)
$BusyPorts = @(
    $DemoPorts | Where-Object {
        $null -ne (Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue)
    }
)

if ($BusyPorts.Count -gt 0) {
    Write-Warning "Port(s) already in use: $($BusyPorts -join ', ')"
    Write-Host "  To stop all Python processes manually:"
    Write-Host "    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force"
    if ($StopExistingPython) {
        Write-Host "  -StopExistingPython flag set: stopping all Python processes..."
        Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 2
        Write-Host "  Stopped."
    } else {
        Write-Host "  Pass -StopExistingPython to stop them automatically."
        Write-Host "  Continuing - conflicting ports will cause service startup errors."
    }
}

# ---------------------------------------------------------------------------
# Phase 1: MCP servers (ports 8004, 8005, 8006)
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Phase 1: MCP servers"
Start-DemoService -Name "Rail MCP Server (port 8004)"     -Command "uv run python mcp_servers/rail_server.py"
Start-DemoService -Name "Flight MCP Server (port 8005)"   -Command "uv run python mcp_servers/flight_server.py"
Start-DemoService -Name "Mobility MCP Server (port 8006)" -Command "uv run python mcp_servers/mobility_server.py"

Write-Host "  Waiting for MCP servers..."
Wait-ForTcpPort -Port 8004 -TimeoutSeconds 30
Wait-ForTcpPort -Port 8005 -TimeoutSeconds 30
Wait-ForTcpPort -Port 8006 -TimeoutSeconds 30

# ---------------------------------------------------------------------------
# Phase 2: Provider agents (ports 10010, 10011, 10012)
# Each agent reads its MCP URL from an env var set in the child window.
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Phase 2: Provider agents"
Start-DemoService `
    -Name    "RailProviderAgent (port 10010)" `
    -Command "uv run python -m agents.rail" `
    -EnvVars @{ RAIL_MCP_URL = "http://localhost:8004/sse" }

Start-DemoService `
    -Name    "FlightProviderAgent (port 10011)" `
    -Command "uv run python -m agents.flight" `
    -EnvVars @{ FLIGHT_MCP_URL = "http://localhost:8005/sse" }

Start-DemoService `
    -Name    "MobilityProviderAgent (port 10012)" `
    -Command "uv run python -m agents.mobility" `
    -EnvVars @{ MOBILITY_MCP_URL = "http://localhost:8006/sse" }

Write-Host "  Waiting for provider agent cards..."
Wait-ForHttpOk -Url "http://localhost:10010/.well-known/agent-card.json" -TimeoutSeconds 120
Wait-ForHttpOk -Url "http://localhost:10011/.well-known/agent-card.json" -TimeoutSeconds 120
Wait-ForHttpOk -Url "http://localhost:10012/.well-known/agent-card.json" -TimeoutSeconds 120

# ---------------------------------------------------------------------------
# Phase 3: Business travel agents (ports 10004, 10002, 10000)
# BusinessTravelAgent connects to Sepolia via ALCHEMY_RPC_URL (from .env).
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Phase 3: Business travel agents"
Start-DemoService -Name "BusinessTravelAgent (port 10004)" -Command "uv run python -m agents.business_travel"
Start-DemoService -Name "OrchestratorAgent (port 10002)"   -Command "uv run python -m agents.orchestrator"
Start-DemoService -Name "CustomerAgent (port 10000)"       -Command "uv run python -m agents.customer"

Write-Host "  Waiting for agent cards..."
Wait-ForHttpOk -Url "http://localhost:10004/.well-known/agent-card.json" -TimeoutSeconds 120
Wait-ForHttpOk -Url "http://localhost:10002/.well-known/agent-card.json" -TimeoutSeconds 120
Wait-ForHttpOk -Url "http://localhost:10000/.well-known/agent-card.json" -TimeoutSeconds 120

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Demo ready."
Write-Host "  Health check:     powershell -ExecutionPolicy Bypass -File ops/demo/check_business_travel_demo.ps1"
Write-Host "  Integration test: uv run python test/business_travel/integration/verify_business_travel.py"
Write-Host "  CLI:              uv run python app/cmd/cmd.py --agent http://localhost:10000"
