# Starts the local Business Travel demo services in separate PowerShell windows.
#
# Run from the project root:
# powershell -ExecutionPolicy Bypass -File scripts/start_business_travel_demo.ps1
#
# If your Windows setup blocks new PowerShell windows, copy the commands below
# and run them manually in separate terminals.

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Services = @(
    @{
        Name = "Rail MCP Server (port 8004)"
        Command = "uv run python mcp_servers/rail_server.py"
    },
    @{
        Name = "Flight MCP Server (port 8005)"
        Command = "uv run python mcp_servers/flight_server.py"
    },
    @{
        Name = "Mobility MCP Server (port 8006)"
        Command = "uv run python mcp_servers/mobility_server.py"
    },
    @{
        Name = "RailProviderAgent (port 10010)"
        Command = "uv run python -m agents.rail"
    },
    @{
        Name = "FlightProviderAgent (port 10011)"
        Command = "uv run python -m agents.flight"
    },
    @{
        Name = "MobilityProviderAgent (port 10012)"
        Command = "uv run python -m agents.mobility"
    },
    @{
        Name = "BusinessTravelAgent (port 10004)"
        Command = "uv run python -m agents.business_travel"
    },
    @{
        Name = "OrchestratorAgent (port 10002)"
        Command = "uv run python -m agents.orchestrator"
    },
    @{
        Name = "CustomerAgent (port 10000)"
        Command = "uv run python -m agents.customer"
    }
)

foreach ($Service in $Services) {
    Write-Host "Starting $($Service.Name)..."

    # Start each long-running server in its own PowerShell window so logs stay visible.
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command",
        "Set-Location '$ProjectRoot'; Write-Host 'Starting $($Service.Name)'; $($Service.Command)"
    )

    # Small delay keeps startup logs readable and avoids all services racing at once.
    Start-Sleep -Seconds 2
}

Write-Host ""
Write-Host "Start the CLI with: uv run python app/cmd/cmd.py --agent http://localhost:10000"
