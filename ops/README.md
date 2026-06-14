# ops/ — Betriebsskripte

Dieses Verzeichnis enthält Skripte für Deployment, Registry-Verwaltung, Demo-Start und Buchungsoperationen.

```
ops/
  deploy/    # Sepolia Deployment-Skripte (deploy_*.js)
  registry/  # Registry-Verwaltung (register_*.js, discover_*.js)
  booking/   # Buchungsoperationen (create_test_booking.js, check_and_complete_booking.py, ...)
  demo/      # Demo-Start und Health-Check
  deployments/
    sepolia.json          # Deployment-Adressen (BusinessAgentRegistry, Policy, Booking)
    sepolia_bookings.json # Protokoll erstellter Test-Buchungen
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
- Alle Python-Abhängigkeiten: `uv sync`

### 1. Alte Prozesse stoppen

Falls ein vorheriger Demo-Run noch läuft:

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
```

Oder mit dem `-StopExistingPython`-Parameter (siehe unten).

### 2. Demo starten

```powershell
powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1
```

Das Skript:
1. Prüft, ob Ports 8004–10012 bereits belegt sind (Warnung, kein Abbruch)
2. Startet MCP-Server (8004, 8005, 8006) in separaten Fenstern
3. Wartet, bis die MCP-Server TCP antworten
4. Startet Provider-Agenten (10010, 10011, 10012) — **mit korrekten Env-Variablen**
5. Wartet, bis die Agent Cards erreichbar sind
6. Startet BusinessTravelAgent (10004), OrchestratorAgent (10002), CustomerAgent (10000)
7. Wartet, bis alle Agent Cards antworten

Mit automatischem Stopp vorhandener Python-Prozesse:

```powershell
powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1 -StopExistingPython
```

### 3. Health Check

```powershell
powershell -ExecutionPolicy Bypass -File ops/demo/check_business_travel_demo.ps1
```

Prüft TCP-Ports 8004/8005/8006 und HTTP-Agent-Cards für alle 6 Agenten.
Gibt `[OK]` / `[FAIL]` pro Service aus. Erst wenn alle grün sind: Integration Test starten.

### 4. Integration Test

```powershell
uv run python test/business_travel/integration/verify_business_travel.py
```

Führt drei Phasen durch:
1. Registry Discovery (Sepolia, read-only via ALCHEMY_RPC_URL)
2. BusinessTravelAgent-Initialisierung (prüft Registry-Endpunkte)
3. A2A-Aufrufe zu Provider-Agenten + SmartContractClient Policy-Entscheidung

### 5. CLI

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
