# Thesis Mapping: Business Travel Prototype

Dieses Dokument ordnet den Business-Travel-Prototyp der Masterarbeit zu. Es beschreibt nicht im Detail, wie der Code funktioniert, sondern welche wissenschaftliche und konzeptionelle Aussage durch die einzelnen Komponenten demonstriert wird.

## 1. Zweck des Prototyps

Der Prototyp demonstriert kontrollierte Agentenautonomie in einem Geschaeftsreise-Szenario.

Agenten duerfen:

- Informationen beschaffen,
- mehrere Werkzeuge und Dienste koordinieren,
- fehlende Angaben in einer Anfrage erfragen,
- das Ergebnis fuer den Nutzer erklaeren.

Die finale regelgebundene Auswahl wird jedoch nicht durch einen Agenten oder ein LLM getroffen. Sie erfolgt in V1 durch den `SmartContractClient` und wird in V2 zusaetzlich durch einen Solidity Smart Contract abgebildet.

## 2. Bezug zur Forschungsfrage

Der Prototyp adressiert allgemein folgende Forschungsfragen:

- Wie koennen autonome Agenten in einem vordefinierten Handlungsrahmen agieren?
- Wie kann ein Smart Contract als Sicherheits- und Governance-Anker dienen?
- Wie kann die finale Entscheidung von probabilistischen LLM- oder Agentenkomponenten getrennt werden?

Die zentrale Idee ist die Trennung von drei Verantwortlichkeiten:

- Agenten koordinieren und bereiten Informationen vor.
- LLMs koennen Sprachverstaendnis, Delegation und Erklaerung unterstuetzen.
- Die finale Policy-Entscheidung erfolgt deterministisch durch Policy-Logik.

## 3. Beitrag der einzelnen Komponenten

### CustomerAgent

Der `CustomerAgent` bildet die Nutzerschnittstelle. Er nimmt die Anfrage des Nutzers entgegen und gibt sie in den A2A-Kommunikationsfluss weiter.

### OrchestratorAgent

Der `OrchestratorAgent` demonstriert Delegation. Er erkennt, dass eine Geschaeftsreise-Anfrage vorliegt, und leitet sie an den passenden Fachagenten weiter.

### BusinessTravelAgent

Der `BusinessTravelAgent` demonstriert Koordination und kontrollierte Tool-Nutzung. Er strukturiert die Anfrage, nutzt MCP-Server, vervollstaendigt fehlende Angaben und bereitet Reiseoptionen vor.

Er trifft nicht die finale Policy-Entscheidung.

### Rail / Flight / Mobility MCP Server

Die MCP-Server stehen fuer externe Informationsquellen in Mock-Form:

- Bahnangebote,
- Flugangebote,
- Flughafentransfers.

Sie liefern Daten, entscheiden aber nicht, welche Option ausgewaehlt wird.

### SmartContractClient

Der `SmartContractClient` bildet in V1 die Policy-Entscheidung ab. Er simuliert einen Smart Contract in Python und wendet die Business-Travel-Regeln deterministisch an.

### BusinessTravelPolicy.sol

Der Solidity Contract `contracts/BusinessTravelPolicy.sol` zeigt in V2, dass dieselbe Policy auch als Smart-Contract-Logik formulierbar ist. Die Logik wird lokal mit Hardhat getestet.

### A2A Multi-Turn

A2A Multi-Turn zeigt, wie fehlende Angaben kontrolliert nachgefragt werden koennen. Wenn zum Beispiel der Startpunkt fehlt, bleibt der Kontext erhalten und die Folgeantwort wird als fehlender Slot interpretiert.

## 4. V1, V2 und V3

### V1

V1 ist der lauffaehige Python-Prototyp:

- A2A/MCP-Agentenfluss,
- Python `SmartContractClient` als Mock,
- deterministische Policy-Auswahl,
- keine echte Blockchain-Anbindung.

### V2

V2 ergaenzt die Solidity-Abbildung der Policy:

- `contracts/BusinessTravelPolicy.sol`,
- Hardhat Tests,
- Nachweis, dass die Policy on-chain abbildbar ist.

V2 verbindet den laufenden Python-Agentenfluss noch nicht mit dem Solidity Contract.

### V3

V3 ergaenzt A2A Multi-Turn Slot Filling:

- Start und Ziel werden fachlich sauberer behandelt.
- Der Agent kann fehlende Angaben erfragen.
- Folgeantworten werden im bestehenden A2A-Kontext interpretiert.
- Die finale Policy-Entscheidung bleibt weiterhin ausserhalb des Agenten.

## 5. Demonstrierte Szenarien

### Scenario A: Dortmund -> Muenchen

- Eine gueltige Bahnoption unter oder gleich 8 Stunden existiert.
- Bahn wird durch die Policy bevorzugt.
- `rail-1` wird ausgewaehlt.

Dieses Szenario zeigt, dass Policy-aware enrichment unnoetige Tool-Nutzung reduzieren kann: Flight und Mobility werden nicht einbezogen, wenn die Bahnoption bereits policy-relevant gueltig ist.

### Scenario B: Dortmund -> Wien

- Es existiert keine gueltige Bahnoption unter oder gleich 8 Stunden.
- Flight und Mobility werden einbezogen.
- Eine `flight_with_transfers`-Option wird gebaut.
- `flight-1-with-transfers` wird ausgewaehlt.

Dieses Szenario zeigt policy-abhaengige Tool-Koordination: Zusaetzliche Informationen werden nur dann beschafft, wenn die Policy dies erforderlich macht.

### Scenario C: Fehlender Startpunkt

- Der Nutzer nennt Ziel und Termin, aber keinen Startpunkt.
- Der Agent fragt ueber A2A Multi-Turn nach dem fehlenden Startpunkt.
- Die Folgeantwort vervollstaendigt die Anfrage.
- Danach laeuft die normale Policy-Auswahl.

Dieses Szenario zeigt, dass Agenten Rueckfragen stellen duerfen, ohne dadurch die finale Policy-Entscheidung selbst zu treffen.

## 6. Was der Prototyp zeigt

Der Prototyp zeigt, dass Agentenautonomie nicht verhindert, sondern kanalisiert werden kann.

Kernaussagen:

- Agenten koennen Tools und Informationsfluesse koordinieren.
- Policy-aware enrichment reduziert unnoetige Tool-Nutzung.
- `SmartContractClient` bzw. Smart Contract setzen harte Regeln durch.
- LLM und Agent koennen erklaeren, treffen aber nicht die finale Auswahl.
- Buchung und Zahlung bleiben genehmigungspflichtig und werden nicht ausgefuehrt.

## 7. Bewusste Grenzen

Der Prototyp enthaelt bewusst nicht:

- echte Reise-APIs,
- echte Blockchain-Anbindung im laufenden Python-Flow,
- Testnet-Deployment,
- echte Zahlung,
- ERC-8004,
- ERC-8183,
- produktive rechtliche Durchsetzung,
- ein vollstaendiges Travel-Management-System.

Diese Grenzen halten den Fokus auf der Architekturfrage: Wie koennen autonome Agenten innerhalb eines expliziten Governance-Rahmens handeln?

## 8. Bedeutung fuer die Masterarbeit

Der Prototyp dient als Demonstrator dafuer, wie autonome Agenten in einem Multiagentensystem durch ein explizites, auditierbares und technisch durchsetzbares Regelwerk begrenzt werden koennen.

Die thesis-relevante Trennung lautet:

- Sprachverarbeitung, Koordination und Erklaerung liegen bei Agenten und LLM-gestuetzter Orchestrierung.
- Die policy-relevante Entscheidung liegt bei deterministischer Policy-Logik.
- Erklaerung und Entscheidung werden bewusst getrennt.

Damit eignet sich der Prototyp zur Diskussion von Governance, Nachvollziehbarkeit und Sicherheitsgrenzen in agentischen Systemen.
