# utilities/mcp/mcp_discovery.py

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class MCPDiscovery:
    """Loads MCP server configurations from a JSON config file."""

    def __init__(self, config_file: str = None):
        if config_file:
            self.config_file = config_file
        else:
            self.config_file = os.path.join(os.path.dirname(__file__), "mcp_config.json")

        self._config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        try:
            with open(self.config_file, "r") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise ValueError("MCP config must be a JSON object")

            return data

        except FileNotFoundError:
            logger.warning(f"MCP config file not found: {self.config_file}")
            return {}

    def list_servers(self) -> dict[str, Any]:
        return self._config.get("mcpServers", {})
