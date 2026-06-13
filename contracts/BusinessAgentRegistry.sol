// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @title BusinessAgentRegistry
/// @notice A small ERC-8004-inspired registry for demo agents.
/// @dev This contract is intentionally simple and didactic. It stores agent
/// metadata and indexes agents by capability, but it does not implement the
/// full ERC-8004 standard.
contract BusinessAgentRegistry {
    struct Agent {
        uint256 agentId;
        string agentURI;
        address owner;
        bool active;
    }

    event AgentRegistered(uint256 indexed agentId, string agentURI, address indexed owner);
    event AgentUpdated(uint256 indexed agentId, string agentURI, bool active);

    uint256 private nextAgentId = 1;

    mapping(uint256 => Agent) private agents;
    mapping(uint256 => string[]) private agentCapabilities;
    mapping(string => uint256[]) private agentsByCapability;

    /// @notice Register a new agent with a URI and a list of capabilities.
    /// @dev Capabilities are simple strings such as "business_travel".
    function register(
        string calldata agentURI,
        string[] calldata capabilities
    ) external returns (uint256 agentId) {
        agentId = nextAgentId;
        nextAgentId += 1;

        agents[agentId] = Agent({
            agentId: agentId,
            agentURI: agentURI,
            owner: msg.sender,
            active: true
        });

        for (uint256 i = 0; i < capabilities.length; i++) {
            agentCapabilities[agentId].push(capabilities[i]);
            agentsByCapability[capabilities[i]].push(agentId);
        }

        emit AgentRegistered(agentId, agentURI, msg.sender);
    }

    /// @notice Update the URI or active flag of an existing agent.
    /// @dev Inactive agents remain readable, but only the owner can update them.
    function updateAgent(
        uint256 agentId,
        string calldata agentURI,
        bool active
    ) external {
        Agent storage agent = agents[agentId];

        require(agent.owner != address(0), "Agent does not exist");
        require(msg.sender == agent.owner, "Only owner can update agent");

        agent.agentURI = agentURI;
        agent.active = active;

        emit AgentUpdated(agentId, agentURI, active);
    }

    /// @notice Read one registered agent.
    function getAgent(uint256 agentId) external view returns (Agent memory) {
        return agents[agentId];
    }

    /// @notice Find agent ids that declared a capability during registration.
    function getAgentsByCapability(
        string calldata capability
    ) external view returns (uint256[] memory) {
        return agentsByCapability[capability];
    }

    /// @notice Read the capabilities originally registered for an agent.
    function getAgentCapabilities(
        uint256 agentId
    ) external view returns (string[] memory) {
        return agentCapabilities[agentId];
    }
}
