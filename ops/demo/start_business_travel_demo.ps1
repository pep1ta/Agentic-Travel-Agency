#Requires -Version 5.1
# ops/demo/start_business_travel_demo.ps1
#
# Starts all local Business Travel demo services in separate PowerShell windows.
# Services are started in dependency order with TCP/HTTP health checks.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1
#   powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1 -StopExistingPython
#   powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1 -SlowStartup
#
# After starting, verify with:
#   powershell -ExecutionPolicy Bypass -File ops/demo/check_business_travel_demo.ps1

param(
    [switch]$StopExistingPython,
    [switch]$SlowStartup
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $ProjectRoot

# ---------------------------------------------------------------------------
# Python interpreter: use venv directly to bypass uv's per-invocation
# environment sync (which can take 5-30s per service on cold starts).
# ---------------------------------------------------------------------------
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Host "FEHLER: Virtuelle Umgebung nicht gefunden: $PythonExe"
    Write-Host "Bitte zuerst 'uv sync' ausfuehren um die Abhaengigkeiten zu installieren."
    exit 1
}
Write-Host "  Python: $PythonExe"

# ---------------------------------------------------------------------------
# Timeouts: short by default. Use -SlowStartup on machines where agents
# need >60s to initialize (e.g. slow I/O, cold Alchemy connections, AV scans).
# ---------------------------------------------------------------------------
if ($SlowStartup) {
    $McpTcpTimeout   = 60
    $ProviderTimeout = 360
    $AgentTimeout    = 180
    $CustomerTimeout = 180
    Write-Host "  Modus: SlowStartup (Provider 360s, BTA/Orch 180s, Customer 180s)"
} else {
    $McpTcpTimeout   = 30
    $ProviderTimeout = 60
    $AgentTimeout    = 60
    $CustomerTimeout = 90
}

# ---------------------------------------------------------------------------
# Start-DemoService: opens a new PS window and runs a command with optional
# env vars and log transcription.
#
# WHY -EncodedCommand:
#   Start-Process passes args via Win32 CreateProcess. Double-quoted URLs get
#   split at the quote boundary - the URL becomes a bare command token.
#   UTF-16LE base64 (-EncodedCommand) bypasses every quoting layer.
#
# WHY Start-Transcript (not Tee-Object):
#   "cmd 2>&1 | Tee-Object" attaches a PS pipeline to native process stdout.
#   On Windows, uv/Python detect non-TTY stdout via this pipe and exit after
#   startup. Start-Transcript hooks into the PS console host without a pipe,
#   so the native process keeps its console stdout/stderr and runs stably.
# ---------------------------------------------------------------------------
function Start-DemoService {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Command,
        [hashtable]$EnvVars = @{},
        [string]$LogFile = ""
    )
    Write-Host "  Starting $Name..."
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("Set-Location '$ProjectRoot'")
    $lines.Add("`$host.UI.RawUI.WindowTitle = '$Name'")
    foreach ($key in $EnvVars.Keys) {
        $val = $EnvVars[$key]
        $lines.Add("`$env:$key = '$val'")
    }
    if ($LogFile -ne "") {
        $lines.Add("Start-Transcript -Path '" + $LogFile + "' -Append")
        $lines.Add("Write-Host ('=== " + $Name + " started: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ===')")
        $lines.Add($Command)
        $lines.Add("Write-Host ('=== " + $Name + " exited: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ===')")
        $lines.Add("Stop-Transcript")
    } else {
        $lines.Add($Command)
    }
    $script  = $lines -join "`n"
    $bytes   = [System.Text.Encoding]::Unicode.GetBytes($script)
    $encoded = [Convert]::ToBase64String($bytes)
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encoded
    )
}

# ---------------------------------------------------------------------------
# Wait-ForTcpPort: blocks until a TCP port responds or timeout
# ---------------------------------------------------------------------------
function Wait-ForTcpPort {
    param(
        [Parameter(Mandatory)][int]$Port,
        [string]$HostName = "localhost",
        [int]$TimeoutSeconds = 30
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host "    TCP :$Port" -NoNewline
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect($HostName, $Port)
            $tcp.Close()
            Write-Host (" OK +" + [int]$sw.Elapsed.TotalSeconds + "s")
            return
        } catch {
            Write-Host "." -NoNewline
            Start-Sleep -Milliseconds 500
        }
    }
    $sw.Stop()
    Write-Host (" TIMEOUT after " + [int]$sw.Elapsed.TotalSeconds + "s")
    throw "Timeout: TCP port $Port not reachable after ${TimeoutSeconds}s."
}

# ---------------------------------------------------------------------------
# Wait-ForAllHttpOk: polls a set of URLs under a shared deadline.
#
# Prints "[OK +Xs] <label>" as each URL responds. Prints a "Still waiting"
# progress line every $ProgressIntervalSeconds for any still-pending URLs.
# Returns array of URLs that did NOT respond in time (empty = all OK).
#
# Each HTTP attempt uses TimeoutSec 5 so a non-responding service does not
# stall the other URLs. The while condition is rechecked after every poll
# cycle; the loop exits immediately when all URLs are ready.
# ---------------------------------------------------------------------------
function Wait-ForAllHttpOk {
    param(
        [Parameter(Mandatory)][string[]]$Urls,
        [string[]]$Labels = @(),
        [int]$TimeoutSeconds = 60,
        [int]$ProgressIntervalSeconds = 10
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $ready = @{}
    $lastProgressSec = 0

    $labelOf = @{}
    for ($i = 0; $i -lt $Urls.Count; $i++) {
        $labelOf[$Urls[$i]] = if ($i -lt $Labels.Count) { $Labels[$i] } else { $Urls[$i] }
    }

    while ($ready.Count -lt $Urls.Count -and $sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        foreach ($url in $Urls) {
            if ($ready.ContainsKey($url)) { continue }
            try {
                $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
                if ($r.StatusCode -eq 200) {
                    $ready[$url] = $true
                    $sec = [int]$sw.Elapsed.TotalSeconds
                    Write-Host ("  [OK +" + $sec + "s] " + $labelOf[$url])
                }
            } catch { }
        }

        if ($ready.Count -ge $Urls.Count) { break }

        $nowSec = [int]$sw.Elapsed.TotalSeconds
        if ($nowSec -ge $lastProgressSec + $ProgressIntervalSeconds) {
            $pending = @($Urls | Where-Object { -not $ready.ContainsKey($_) } | ForEach-Object { $labelOf[$_] })
            Write-Host ("  Still waiting after " + $nowSec + "s: " + ($pending -join ", "))
            $lastProgressSec = $nowSec
        }

        Start-Sleep -Milliseconds 200
    }

    $sw.Stop()
    $elapsed = [int]$sw.Elapsed.TotalSeconds
    $failed  = @($Urls | Where-Object { -not $ready.ContainsKey($_) })
    if ($failed.Count -gt 0) {
        Write-Host ("  Timeout nach " + $elapsed + "s. Nicht erreichbar: " + (($failed | ForEach-Object { $labelOf[$_] }) -join ", "))
    }
    return $failed
}

# ---------------------------------------------------------------------------
# Show-ServiceDiagnostics: on timeout, shows TCP port state and log tail
# ---------------------------------------------------------------------------
function Show-ServiceDiagnostics {
    param(
        [string]$Name,
        [int]$Port,
        [string]$LogFile
    )
    $tcpUp    = $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    $tcpState = if ($tcpUp) { "listening" } else { "closed" }
    $tcpColor = if ($tcpUp) { "Yellow" } else { "Red" }
    Write-Host ("  " + $Name + " nicht bereit:") -ForegroundColor Red
    Write-Host ("    TCP :" + $Port + " = " + $tcpState) -ForegroundColor $tcpColor
    if (Test-Path $LogFile) {
        Write-Host ("    Log: " + $LogFile)
        # Skip the Start-Transcript header block (PS version info, base64 command, etc.)
        # and show only lines after the "=== <Name> started: ===" marker.
        $allLines = @(Get-Content $LogFile -ErrorAction SilentlyContinue)
        $markerIdx = -1
        for ($i = 0; $i -lt $allLines.Count; $i++) {
            if ($allLines[$i] -match "^===.*started:") { $markerIdx = $i }
        }
        $tail = if ($markerIdx -ge 0) {
            @($allLines[($markerIdx + 1)..($allLines.Count - 1)] | Select-Object -Last 20)
        } else {
            @($allLines | Select-Object -Last 20)
        }
        if ($tail.Count -gt 0) {
            Write-Host "    Letzte Zeilen:"
            foreach ($line in $tail) { Write-Host ("      " + $line) -ForegroundColor DarkGray }
        } else {
            Write-Host "    (Kein Python-Output nach Start - Prozess noch in Initialisierung)" -ForegroundColor Yellow
        }
    } else {
        Write-Host ("    Log: " + $LogFile + " (nicht gefunden - Prozess vermutlich nicht gestartet)") -ForegroundColor Red
    }
    Write-Host ""
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
# Log directory: create if absent, archive previous run's logs
# ---------------------------------------------------------------------------
$LogDir = Join-Path $ProjectRoot "ops\demo\logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$oldLogs = @(Get-ChildItem -Path (Join-Path $LogDir "*.log") -ErrorAction SilentlyContinue)
if ($oldLogs.Count -gt 0) {
    $archiveTs  = Get-Date -Format "yyyyMMdd_HHmmss"
    $archiveDir = Join-Path $LogDir ("archive_" + $archiveTs)
    New-Item -ItemType Directory -Path $archiveDir | Out-Null
    $oldLogs | ForEach-Object { Move-Item -Path $_.FullName -Destination $archiveDir }
    Write-Host ("  Previous logs archived to: " + $archiveDir)
}
Write-Host ("  Logs: " + $LogDir)

# ---------------------------------------------------------------------------
# Phase 1: MCP servers (ports 8004, 8005, 8006)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Phase 1: MCP servers"
Start-DemoService `
    -Name    "Rail MCP Server (port 8004)" `
    -Command "& '$PythonExe' mcp_servers/rail_server.py" `
    -LogFile (Join-Path $LogDir "rail_mcp.log")
Start-DemoService `
    -Name    "Flight MCP Server (port 8005)" `
    -Command "& '$PythonExe' mcp_servers/flight_server.py" `
    -LogFile (Join-Path $LogDir "flight_mcp.log")
Start-DemoService `
    -Name    "Mobility MCP Server (port 8006)" `
    -Command "& '$PythonExe' mcp_servers/mobility_server.py" `
    -LogFile (Join-Path $LogDir "mobility_mcp.log")

Write-Host ("  Waiting for MCP servers (TCP, " + $McpTcpTimeout + "s each)...")
$phase1Start = Get-Date
Wait-ForTcpPort -Port 8004 -TimeoutSeconds $McpTcpTimeout
Wait-ForTcpPort -Port 8005 -TimeoutSeconds $McpTcpTimeout
Wait-ForTcpPort -Port 8006 -TimeoutSeconds $McpTcpTimeout
Write-Host ("  MCP servers ready after " + [int]((Get-Date) - $phase1Start).TotalSeconds + "s.")

# ---------------------------------------------------------------------------
# Phase 2: Provider agents (ports 10010, 10011, 10012)
# Each agent reads its MCP URL from an env var set in the child window.
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Phase 2: Provider agents"
Start-DemoService `
    -Name    "RailProviderAgent (port 10010)" `
    -Command "& '$PythonExe' -m agents.rail" `
    -EnvVars @{ RAIL_MCP_URL = "http://localhost:8004/sse" } `
    -LogFile (Join-Path $LogDir "rail_provider.log")
Start-DemoService `
    -Name    "FlightProviderAgent (port 10011)" `
    -Command "& '$PythonExe' -m agents.flight" `
    -EnvVars @{ FLIGHT_MCP_URL = "http://localhost:8005/sse" } `
    -LogFile (Join-Path $LogDir "flight_provider.log")
Start-DemoService `
    -Name    "MobilityProviderAgent (port 10012)" `
    -Command "& '$PythonExe' -m agents.mobility" `
    -EnvVars @{ MOBILITY_MCP_URL = "http://localhost:8006/sse" } `
    -LogFile (Join-Path $LogDir "mobility_provider.log")

$providerUrls = @(
    "http://localhost:10010/.well-known/agent-card.json",
    "http://localhost:10011/.well-known/agent-card.json",
    "http://localhost:10012/.well-known/agent-card.json"
)
$providerLabels  = @("RailProviderAgent", "FlightProviderAgent", "MobilityProviderAgent")
$providerLogMap  = @{
    "http://localhost:10010/.well-known/agent-card.json" = @{ Name = "RailProviderAgent";     Port = 10010; Log = "rail_provider.log" }
    "http://localhost:10011/.well-known/agent-card.json" = @{ Name = "FlightProviderAgent";   Port = 10011; Log = "flight_provider.log" }
    "http://localhost:10012/.well-known/agent-card.json" = @{ Name = "MobilityProviderAgent"; Port = 10012; Log = "mobility_provider.log" }
}

Write-Host ("  Waiting for provider agent cards (" + $ProviderTimeout + "s deadline)...")
$phase2Start    = Get-Date
$failedProviders = @(Wait-ForAllHttpOk -Urls $providerUrls -Labels $providerLabels -TimeoutSeconds $ProviderTimeout)
$phase2Elapsed  = [int]((Get-Date) - $phase2Start).TotalSeconds

if ($failedProviders.Count -gt 0) {
    foreach ($url in $failedProviders) {
        $info = $providerLogMap[$url]
        Show-ServiceDiagnostics -Name $info.Name -Port $info.Port -LogFile (Join-Path $LogDir $info.Log)
    }
    if (-not $SlowStartup) {
        Write-Host "  Tipp: Agenten benoetigen manchmal >60s (uv-Cache-Aufbau, Alchemy-Verbindung)." -ForegroundColor Yellow
        Write-Host "  Mit -SlowStartup werden erweiterte Timeouts (300s) verwendet." -ForegroundColor Yellow
    }
    throw ("Provider-Agenten nicht bereit nach " + $ProviderTimeout + "s. Demo-Start abgebrochen.")
}
Write-Host ("  Provider agents ready after " + $phase2Elapsed + "s.")

# ---------------------------------------------------------------------------
# Phase 3a: BusinessTravelAgent (port 10004)
#
# Must start and be confirmed BEFORE OrchestratorAgent:
# agents/orchestrator/agent.py initialize() calls create_from_url("http://localhost:10004")
# at Orch startup. If BTA is not yet serving, _agent_clients stays empty and
# list_agents() returns [] -> delegation fails with "Unknown agent: Business Travel Agent".
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Phase 3a: BusinessTravelAgent (port 10004)"
Start-DemoService `
    -Name    "BusinessTravelAgent (port 10004)" `
    -Command "& '$PythonExe' -m agents.business_travel" `
    -LogFile (Join-Path $LogDir "business_travel_agent.log")

Write-Host ("  Waiting for BusinessTravelAgent (" + $AgentTimeout + "s deadline)...")
$phase3aStart   = Get-Date
$failed3a       = @(Wait-ForAllHttpOk `
    -Urls    @("http://localhost:10004/.well-known/agent-card.json") `
    -Labels  @("BusinessTravelAgent") `
    -TimeoutSeconds $AgentTimeout)
$phase3aElapsed = [int]((Get-Date) - $phase3aStart).TotalSeconds

if ($failed3a.Count -gt 0) {
    Show-ServiceDiagnostics -Name "BusinessTravelAgent" -Port 10004 -LogFile (Join-Path $LogDir "business_travel_agent.log")
    if (-not $SlowStartup) {
        Write-Host "  Tipp: Mit -SlowStartup werden erweiterte Timeouts (180s) verwendet." -ForegroundColor Yellow
    }
    throw ("BusinessTravelAgent nicht bereit nach " + $AgentTimeout + "s.")
}
Write-Host ("  BusinessTravelAgent ready after " + $phase3aElapsed + "s.")

# ---------------------------------------------------------------------------
# Phase 3b: OrchestratorAgent (port 10002) -- starts AFTER BTA confirmed ready
#
# BUSINESS_TRAVEL_AGENT_URL tells __main__.py to use this explicit local URL
# instead of the JSON registry. initialize() then connects to BTA successfully
# because BTA is already serving its agent card.
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Phase 3b: OrchestratorAgent (port 10002)"
Write-Host "  (BusinessTravelAgent bestaetigt auf :10004 - Orchestrator kann sich verbinden)"
Start-DemoService `
    -Name    "OrchestratorAgent (port 10002)" `
    -Command "& '$PythonExe' -m agents.orchestrator" `
    -EnvVars @{ BUSINESS_TRAVEL_AGENT_URL = "http://localhost:10004" } `
    -LogFile (Join-Path $LogDir "orchestrator_agent.log")

Write-Host ("  Waiting for OrchestratorAgent (" + $AgentTimeout + "s deadline)...")
$phase3bStart   = Get-Date
$failed3b       = @(Wait-ForAllHttpOk `
    -Urls    @("http://localhost:10002/.well-known/agent-card.json") `
    -Labels  @("OrchestratorAgent") `
    -TimeoutSeconds $AgentTimeout)
$phase3bElapsed = [int]((Get-Date) - $phase3bStart).TotalSeconds

if ($failed3b.Count -gt 0) {
    Show-ServiceDiagnostics -Name "OrchestratorAgent" -Port 10002 -LogFile (Join-Path $LogDir "orchestrator_agent.log")
    if (-not $SlowStartup) {
        Write-Host "  Tipp: Mit -SlowStartup werden erweiterte Timeouts (180s) verwendet." -ForegroundColor Yellow
    }
    throw ("OrchestratorAgent nicht bereit nach " + $AgentTimeout + "s.")
}
Write-Host ("  OrchestratorAgent ready after " + $phase3bElapsed + "s.")

# ---------------------------------------------------------------------------
# Phase 3c: CustomerAgent (port 10000)
#
# Must start AFTER OrchestratorAgent is confirmed up:
# agents/customer/__main__.py:66 calls ClientFactory.create_from_url(ORCHESTRATOR_URL)
# during build_app() - fails immediately if the Orchestrator is not yet serving.
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Phase 3c: CustomerAgent (nach OrchestratorAgent-Bestaetigung)"
Start-DemoService `
    -Name    "CustomerAgent (port 10000)" `
    -Command "& '$PythonExe' -m agents.customer" `
    -LogFile (Join-Path $LogDir "customer_agent.log")

Write-Host ("  Waiting for CustomerAgent (" + $CustomerTimeout + "s deadline)...")
$phase3cStart   = Get-Date
$failed3c       = @(Wait-ForAllHttpOk `
    -Urls    @("http://localhost:10000/.well-known/agent-card.json") `
    -Labels  @("CustomerAgent") `
    -TimeoutSeconds $CustomerTimeout)
$phase3cElapsed = [int]((Get-Date) - $phase3cStart).TotalSeconds

if ($failed3c.Count -gt 0) {
    $tcpUp = $null -ne (Get-NetTCPConnection -LocalPort 10000 -State Listen -ErrorAction SilentlyContinue)
    if ($tcpUp) {
        Write-Host "  CustomerAgent: Port 10000 lauscht, Agent Card hat nicht im Timeout geantwortet." -ForegroundColor Yellow
    }
    Show-ServiceDiagnostics -Name "CustomerAgent" -Port 10000 -LogFile (Join-Path $LogDir "customer_agent.log")
    Write-Host "  Moegliche Ursache: OrchestratorAgent (10002) war bei CustomerAgent-Start nicht schnell genug bereit."
    Write-Host "  Hinweis: Integrationstest kann ohne CustomerAgent laufen."
    Write-Host ("  Manuell starten: & '" + $PythonExe + "' -m agents.customer")
    throw ("CustomerAgent nicht erreichbar nach " + $CustomerTimeout + "s.")
}
Write-Host ("  CustomerAgent ready after " + $phase3cElapsed + "s.")

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Demo ready."
Write-Host "  Health check:      powershell -ExecutionPolicy Bypass -File ops/demo/check_business_travel_demo.ps1"
Write-Host "  Integration tests:"
Write-Host "    uv run python test/business_travel/integration/verify_business_travel.py"
Write-Host "    uv run python test/business_travel/integration/verify_customer_orchestrator_business_travel.py"
Write-Host "  CLI (BTA direkt):  uv run python app/cmd/cmd.py --agent http://localhost:10004"
Write-Host "  CLI (Orchestrator): uv run python app/cmd/cmd.py --agent http://localhost:10002"
Write-Host "  CLI (Customer):    uv run python app/cmd/cmd.py --agent http://localhost:10000"
