# ops/ — Betriebsskripte

Dieses Verzeichnis enthält Skripte für Deployment, Registry-Verwaltung, Demo-Start und Buchungsoperationen.

```
ops/
  deploy/       # Sepolia Deployment-Skripte (deploy_*.js)
  registry/     # Registry-Verwaltung und Diagnostik
    register_business_agents.js          # Registriert BusinessTravelAgent in der Registry
    register_business_provider_agents.js # Registriert Rail/Flight/Mobility-Provider
    discover_business_agents.js          # Diagnostik: zeigt alle Capabilities in der Registry
    discover_business_provider_agents.js # Diagnostik: prüft A2A-URIs der Provider-Agenten
  booking/      # Buchungsoperationen
    check_and_complete_booking.py  # Legacy: prüft createBooking-Tx und ruft completeBooking
                                   # Offizieller Pfad: submit_verified_booking_for_decision
                                   #   -> BusinessTravelBooking.createVerifiedBooking (policyVerified=true)
  demo/         # Demo-Start und Health-Check
  deployments/
    sepolia.json  # Deployment-Adressen (BusinessAgentRegistry, Policy, Booking)
```

---

## Lokaler Demo-Start

### Voraussetzungen

- `.env` im Projektroot mit:
  ```
  ALCHEMY_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/<key>
  WALLET_PRIVATE_KEY=<hex>
  WALLET_ADDRESS=<0x...>
  ```
- `uv` installiert (`pip install uv` oder über `winget`)
- Alle Python-Abhängigkeiten: `uv sync` (erstellt `.venv\`)

### 1. Alte Prozesse stoppen

Falls ein vorheriger Demo-Run noch läuft:

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
```

Oder mit dem `-StopExistingPython`-Parameter (siehe unten).

### 2. Demo starten

```powershell
powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1 -StopExistingPython
```

Das Skript:
1. Prüft, ob `.venv\Scripts\python.exe` vorhanden ist (Fehler wenn nicht)
2. Prüft, ob Ports 8004–10012 bereits belegt sind (Warnung, kein Abbruch)
3. Startet MCP-Server (8004, 8005, 8006) direkt mit `.venv\Scripts\python.exe`
4. Wartet, bis die MCP-Server TCP antworten (≤30s)
5. Startet Provider-Agenten (10010, 10011, 10012) mit korrekten Env-Variablen
6. Wartet, bis die Agent Cards antworten (≤60s)
7. Startet **BusinessTravelAgent (10004)** und wartet auf Agent Card (≤60s)
8. Startet **OrchestratorAgent (10002)** *erst nach BTA-Bestätigung* mit `BUSINESS_TRAVEL_AGENT_URL=http://localhost:10004`, wartet (≤60s)
9. Startet **CustomerAgent (10000)** *erst nach Orch-Bestätigung*, wartet (≤90s)

> **Warum sequenziell?** `OrchestratorAgent.initialize()` ruft `create_from_url("http://localhost:10004")` beim Start auf. Wenn BusinessTravelAgent noch nicht bereit ist, schlägt die Verbindung lautlos fehl — `_agent_clients` bleibt leer — und alle Delegationen scheitern mit `"Unknown agent: Business Travel Agent. Available: []"`. Durch sequenziellen Start ist BTA garantiert bereit, bevor Orch initialisiert.

Typische Gesamtdauer: **~60–90 Sekunden** (keine `uv run`-Overhead pro Service).

**Auf langsamen Maschinen oder bei erstem Start nach langer Pause:**

```powershell
powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1 -StopExistingPython -SlowStartup
```

Mit `-SlowStartup` gelten erweiterte Timeouts: Provider 360s, BTA/Orch 180s, Customer 180s.

### 3. Health Check

```powershell
powershell -ExecutionPolicy Bypass -File ops/demo/check_business_travel_demo.ps1
```

Prüft TCP-Ports 8004/8005/8006 und HTTP-Agent-Cards für alle 9 Services.
Gibt `[OK]` / `[FAIL]` pro Service aus. Bei `[FAIL]` werden Log-Pfad und letzte Log-Zeilen angezeigt.

### 4. Integration Tests

```powershell
# Provider-Kette (Registry, BTA intern, SmartContractClient)
uv run python test/business_travel/integration/verify_business_travel.py

# Vollkette Customer -> Orchestrator -> BusinessTravelAgent
uv run python test/business_travel/integration/verify_customer_orchestrator_business_travel.py
```

`verify_business_travel.py` prüft:
1. Registry Discovery (Sepolia, read-only via ALCHEMY_RPC_URL)
2. BusinessTravelAgent-Initialisierung (prüft Registry-Endpunkte)
3. A2A-Aufrufe zu Provider-Agenten + SmartContractClient Policy-Entscheidung

`verify_customer_orchestrator_business_travel.py` prüft:
1. OrchestratorAgent (10002) und CustomerAgent (10000) sind erreichbar
2. OrchestratorAgent delegiert Business-Travel-Anfragen korrekt an BusinessTravelAgent
3. CustomerAgent leitet korrekt durch die vollständige Kette

### 5. Registry Diagnostik (read-only, kein Wallet nötig)

```powershell
# Alle registrierten Capabilities anzeigen (business_travel, rail, flight, mobility)
node ops/registry/discover_business_agents.js

# A2A-URIs der Provider-Agenten prüfen (erwartet localhost:10010/10011/10012)
node ops/registry/discover_business_provider_agents.js
```

Beide Skripte lesen nur aus der Sepolia-Chain — keine Transaktion, kein privater Schlüssel.  
`discover_business_provider_agents.js` zeigt zusätzlich den URI-Status (`OK` / `MISMATCH` / `NEEDS-UPDATE`).  
Falls Provider-Agenten fehlen oder falsche URIs haben: `node ops/registry/register_business_provider_agents.js`.

### 7. CLI

```powershell
uv run python app/cmd/cmd.py --agent http://localhost:10000
```

---

## Typische Fehler

| Fehlermeldung | Ursache | Lösung |
|---|---|---|
| `RAIL_MCP_URL is not set` | `RailProviderAgent` wurde gestartet, aber `RAIL_MCP_URL` fehlte im Fenster | Altes `start_business_travel_demo.ps1` mit falschen Quotes. Neu starten mit aktuellem Skript. |
| `http://localhost:8004/sse : Die Benennung ... wurde nicht als Name eines Cmdlet erkannt` | URL wurde von PowerShell als Command interpretiert | Quoting-Bug im alten Startskript. Behoben durch `-EncodedCommand`. |
| `AgentCardResolutionError ... localhost:10011` | FlightProviderAgent läuft nicht oder Port 10011 nicht erreichbar | Agent starten oder Health Check ausführen |
| `TaskGroup` / SSE-Fehler im Provider-Agenten | MCP-Server dahinter läuft nicht | Rail/Flight/Mobility MCP-Server prüfen (Ports 8004/8005/8006) |
| `ALCHEMY_RPC_URL is not set` | `.env` fehlt oder URL ist leer | `.env` im Projektroot anlegen |
| `Kein Agent für Capability 'rail' im Registry registriert` | BusinessAgentRegistry auf Sepolia hat keine Provider-Agenten registriert | `node ops/registry/register_business_provider_agents.js` |

---

## Technisches: Warum `.venv\Scripts\python.exe` statt `uv run`?

`uv run python -m agents.rail` überprüft vor jedem Start die gesamte Umgebung gegen die
Lockfile und löst Abhängigkeiten neu auf — auf Windows triggert das Windows-Defender-Scans
aller betroffenen Dateien. Das kostet pro Service 5–60 Sekunden extra, bei 9 Services parallel
kann das zu 300+ Sekunden Startup-Verzögerung führen.

`.venv\Scripts\python.exe -m agents.rail` startet den Python-Interpreter direkt aus der
bereits synchronisierten virtuellen Umgebung — ohne uv-Overhead. Die Pakete sind bereits
installiert (aus `uv sync`), kein Re-Check nötig. Typische Startup-Zeit: 10–25 Sekunden.

## Technisches: Warum `-EncodedCommand`?

`Start-Process powershell -ArgumentList @("-Command", <string>)` leitet den String an
`powershell.exe` via Windows-`CreateProcess`-API weiter. Die Win32-Argument-Parsing zerstört
dabei doppelte Anführungszeichen in URLs wie `"http://localhost:8004/sse"` — die URL wird zu
einem eigenständigen Token und PowerShell versucht, sie als Command auszuführen.

Die Lösung: `-EncodedCommand` nimmt einen Base64-codierten UTF-16LE-String, der keine
Argument-Parsing-Ebene durchläuft. Env-Var-Werte werden außerdem mit einfachen Anführungszeichen
gesetzt (`$env:RAIL_MCP_URL = 'http://localhost:8004/sse'`), sodass auch in der generierten
Script-Datei keine problematischen Zeichen entstehen.

---

## Weitere Befehle

```powershell
# Alle Python-Prozesse stoppen
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Hardhat-Tests
npx hardhat test

# Unit-Tests (kein Blockchain-Zugang nötig)
uv run python test/business_travel/unit/verify_business_travel_unit.py

# Provider-Agenten-Tests (kein Blockchain-Zugang nötig)
uv run python test/providers/verify_provider_agents.py
```
