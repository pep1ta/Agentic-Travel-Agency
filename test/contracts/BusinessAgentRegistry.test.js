import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { network } from "hardhat";

async function deployRegistry() {
  const { viem } = await network.create();
  return await viem.deployContract("BusinessAgentRegistry");
}

describe("BusinessAgentRegistry", () => {
  it("registers an agent", async () => {
    const registry = await deployRegistry();

    await registry.write.register([
      "http://localhost:10004/.well-known/agent-card.json",
      ["business_travel"],
    ]);

    const agent = await registry.read.getAgent([1n]);

    assert.equal(agent.agentId, 1n);
  });

  it("stores agentURI, owner, and active flag", async () => {
    const { viem } = await network.create();
    const [owner] = await viem.getWalletClients();
    const registry = await viem.deployContract("BusinessAgentRegistry");

    await registry.write.register([
      "http://localhost:10004/.well-known/agent-card.json",
      ["business_travel"],
    ]);

    const agent = await registry.read.getAgent([1n]);

    assert.equal(agent.agentId, 1n);
    assert.equal(agent.agentURI, "http://localhost:10004/.well-known/agent-card.json");
    assert.equal(agent.owner.toLowerCase(), owner.account.address.toLowerCase());
    assert.equal(agent.active, true);
  });

  it("finds an agent by capability", async () => {
    const registry = await deployRegistry();

    await registry.write.register([
      "http://localhost:10004/.well-known/agent-card.json",
      ["business_travel", "policy_explanation"],
    ]);

    const agentIds = await registry.read.getAgentsByCapability(["business_travel"]);

    assert.deepEqual(agentIds, [1n]);
  });

  it("finds multiple agents with the same capability", async () => {
    const registry = await deployRegistry();

    await registry.write.register([
      "http://localhost:10004/.well-known/agent-card.json",
      ["business_travel"],
    ]);
    await registry.write.register([
      "http://localhost:10005/.well-known/agent-card.json",
      ["business_travel", "rail_search"],
    ]);

    const agentIds = await registry.read.getAgentsByCapability(["business_travel"]);

    assert.deepEqual(agentIds, [1n, 2n]);
  });

  it("reads agent capabilities", async () => {
    const registry = await deployRegistry();

    await registry.write.register([
      "http://localhost:10004/.well-known/agent-card.json",
      ["business_travel", "policy_explanation"],
    ]);

    const capabilities = await registry.read.getAgentCapabilities([1n]);

    assert.deepEqual(capabilities, ["business_travel", "policy_explanation"]);
  });

  it("allows only the owner to update an agent", async () => {
    const { viem } = await network.create();
    const [, otherUser] = await viem.getWalletClients();
    const registry = await viem.deployContract("BusinessAgentRegistry");

    await registry.write.register([
      "http://localhost:10004/.well-known/agent-card.json",
      ["business_travel"],
    ]);

    await assert.rejects(
      registry.write.updateAgent(
        [1n, "http://localhost:10099/.well-known/agent-card.json", false],
        { account: otherUser.account }
      )
    );
  });

  it("updates agentURI and active flag", async () => {
    const registry = await deployRegistry();

    await registry.write.register([
      "http://localhost:10004/.well-known/agent-card.json",
      ["business_travel"],
    ]);

    await registry.write.updateAgent([
      1n,
      "http://localhost:10044/.well-known/agent-card.json",
      false,
    ]);

    const agent = await registry.read.getAgent([1n]);

    assert.equal(agent.agentURI, "http://localhost:10044/.well-known/agent-card.json");
    assert.equal(agent.active, false);
  });
});
