#Requires -Version 5.1
# ops/demo/check_business_travel_demo.ps1
#
# Checks that all demo services respond correctly.
# Run this before the integration test to confirm all services are up.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File ops/demo/check_business_travel_demo.ps1

$ErrorActionPreference = "SilentlyContinue"

function Test-TcpPort {
    param([int]$Port, [string]$HostName = "localhost")
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect($HostName, $Port)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

function Test-HttpOk {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Write-CheckLine {
    param([string]$Label, [bool]$Ok)
    if ($Ok) {
        Write-Host ("  [OK]   " + $Label) -ForegroundColor Green
    } else {
        Write-Host ("  [FAIL] " + $Label) -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Business Travel Demo - Health Check"
Write-Host "===================================="

$items = @(
    @{ Label = "Rail MCP Server       TCP :8004";           Ok = (Test-TcpPort 8004) }
    @{ Label = "Flight MCP Server     TCP :8005";           Ok = (Test-TcpPort 8005) }
    @{ Label = "Mobility MCP Server   TCP :8006";           Ok = (Test-TcpPort 8006) }
    @{ Label = "RailProviderAgent     agent-card :10010";   Ok = (Test-HttpOk "http://localhost:10010/.well-known/agent-card.json") }
    @{ Label = "FlightProviderAgent   agent-card :10011";   Ok = (Test-HttpOk "http://localhost:10011/.well-known/agent-card.json") }
    @{ Label = "MobilityProviderAgent agent-card :10012";   Ok = (Test-HttpOk "http://localhost:10012/.well-known/agent-card.json") }
    @{ Label = "BusinessTravelAgent   agent-card :10004";   Ok = (Test-HttpOk "http://localhost:10004/.well-known/agent-card.json") }
    @{ Label = "OrchestratorAgent     agent-card :10002";   Ok = (Test-HttpOk "http://localhost:10002/.well-known/agent-card.json") }
    @{ Label = "CustomerAgent         agent-card :10000";   Ok = (Test-HttpOk "http://localhost:10000/.well-known/agent-card.json") }
)

$failCount = 0
foreach ($item in $items) {
    Write-CheckLine -Label $item.Label -Ok $item.Ok
    if (-not $item.Ok) { $failCount++ }
}

Write-Host ""
if ($failCount -eq 0) {
    Write-Host "All checks passed. Demo is ready." -ForegroundColor Green
    Write-Host "  Integration test: uv run python test/business_travel/integration/verify_business_travel.py"
    Write-Host "  CLI:              uv run python app/cmd/cmd.py --agent http://localhost:10000"
} else {
    Write-Host "$failCount check(s) failed. Diagnose with the error guide below." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Common causes:"
    Write-Host "    TCP :8004/:8005/:8006 FAIL  -> MCP server not started or crashed"
    Write-Host "    agent-card FAIL (10010-12)  -> Provider agent not running or RAIL_MCP_URL/FLIGHT_MCP_URL/MOBILITY_MCP_URL not set in that window"
    Write-Host "    agent-card FAIL (10004)     -> BusinessTravelAgent failed to connect to registry (check ALCHEMY_RPC_URL in .env)"
    Write-Host "    agent-card FAIL (10002/0)   -> Orchestrator/Customer agent crashed on startup"
    Write-Host ""
    Write-Host "  To restart everything cleanly:"
    Write-Host "    powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1 -StopExistingPython"
}
Write-Host ""
