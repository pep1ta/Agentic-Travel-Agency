# Enterprise Policy Platform — Architecture Diagram

```mermaid
flowchart TD
    user[Enterprise User]
    customer[Enterprise Entry Agent\nCustomerAgent :10000]
    orchestrator[OrchestratorAgent :10002]
    business[BusinessTravelAgent :10004]

    registry_chain[BusinessAgentRegistry\nSepolia on-chain]

    rail_agent[RailProviderAgent :10010]
    flight_agent[FlightProviderAgent :10011]
    mobility_agent[MobilityProviderAgent :10012]

    rail_mcp[Rail MCP Server :8004]
    flight_mcp[Flight MCP Server :8005]
    mobility_mcp[Mobility MCP Server :8006]

    scc[SmartContractClient\neth_call — read-only]
    policy[BusinessTravelPolicy.sol\nSepolia Testnet]

    booking_client[BookingClient]
    booking_contract[BusinessTravelBooking.sol\nSepolia Testnet]

    approval[Booking requires explicit user approval]

    subgraph offchain[Off-chain: Agent Coordination]
        user
        customer
        orchestrator
        business
        rail_agent
        flight_agent
        mobility_agent
        rail_mcp
        flight_mcp
        mobility_mcp
        scc
        booking_client
    end

    subgraph onchain[On-chain: Sepolia Testnet]
        registry_chain
        policy
        booking_contract
    end

    user -->|Enterprise request| customer
    customer -->|A2A JSON-RPC| orchestrator
    orchestrator -->|Delegates business travel task| business

    business -->|Discover provider agents| registry_chain
    registry_chain -->|Agent IDs and A2A URIs| business

    business -->|A2A: search rail options| rail_agent
    rail_agent -->|MCP tool call| rail_mcp
    rail_mcp -->|Rail offers| rail_agent
    rail_agent -->|Rail offers| business

    business -->|If no rail <= 8h: A2A search flights| flight_agent
    flight_agent -->|MCP tool call| flight_mcp
    flight_mcp -->|Flight offers| flight_agent
    flight_agent -->|Flight offers| business

    business -->|If no rail <= 8h: A2A get transfers| mobility_agent
    mobility_agent -->|MCP tool call| mobility_mcp
    mobility_mcp -->|Transfer data| mobility_agent
    mobility_agent -->|Transfer data| business

    business -->|Offer bundle| scc
    scc -->|eth_call selectPolicyCompliantOffer| policy
    policy -->|selected_index and decision| scc
    scc -->|Policy decision| business

    business -->|Decision result| orchestrator
    orchestrator -->|Response| customer
    customer -->|Policy decision to user| user

    user -->|Approves booking| booking_client
    booking_client -->|createVerifiedBooking tx| booking_contract
    booking_contract -->|Re-runs policy on-chain| policy
    booking_contract -->|policyVerified=true, offerHash| booking_client
    booking_client -->|tx hash and Etherscan link| user

    business -.->|No automatic booking| approval
```

Der Prototyp trennt Informationsbeschaffung, Koordination und finale Entscheidung in drei Schichten.

**Koordinationsschicht (Off-chain):** Der `BusinessTravelAgent` entdeckt Provider-Agenten zur Laufzeit aus dem `BusinessAgentRegistry` auf Sepolia. Er ruft `RailProviderAgent`, `FlightProviderAgent` und `MobilityProviderAgent` via A2A auf, die wiederum ihre jeweiligen MCP-Server nutzen. Das kombinierte Angebot (`flight_with_transfers`) entsteht durch Zusammenfuehren eines Flugangebots mit Transferdaten — der Agent entscheidet nur, ob Flight/Mobility-Anreicherung noetig ist, nicht welches Angebot gewinnt.

**Policy-Schicht (On-chain, read-only):** Der `SmartContractClient` ruft `BusinessTravelPolicy.selectPolicyCompliantOffer` via `eth_call` auf — keine Transaktion, keine Gaskosten. Der Solidity-Contract prueft Bahnpraeferenz, Budget, Reiseklasse, Provider-Reputation, Transferpflicht und gibt `NO_SELECTION` (`type(uint256).max`) zurueck, wenn kein Angebot policy-konform ist. LLM und Agent koennen das Ergebnis erklaeren, aber nicht veraendern.

**Buchungsschicht (On-chain, Transaktion):** Erst nach expliziter Nutzerfreigabe ruft der `BookingClient` `BusinessTravelBooking.createVerifiedBooking` auf. Der Booking-Contract fuehrt `selectPolicyCompliantOffer` erneut on-chain aus und vergleicht das Ergebnis mit dem uebergebenen `selected_index` — eine Manipulation zwischen Policy-Aufruf und Buchung wuerde zur Reversion fuehren. Gespeichert werden `policyVerified=true` und ein `offerHash` als kryptografischer Fingerabdruck des verifizierten Angebots. Es handelt sich um eine Sepolia-Simulation — keine echte Reisebuchung, keine echte Zahlung.

**A2A Multi-Turn:** Fehlende Angaben (z.B. Startpunkt) werden kontrolliert nachgefragt. Der A2A-Kontext bleibt erhalten; Folgeantworten werden als fehlende Slots interpretiert. Die Policy-Entscheidung wird dadurch nicht veraendert.
