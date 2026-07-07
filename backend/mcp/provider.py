from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger(__name__)

class MCPProvider:
    """
    Lightweight abstraction for Model Context Protocol (MCP).
    Currently acts as a placeholder to allow future integration with full MCP servers.
    """
    def __init__(self):
        self._tools = {}
        self._resources = {}
        
    def register_tool(self, name: str, description: str, handler: callable):
        """Register a tool available to the agents."""
        self._tools[name] = {
            "description": description,
            "handler": handler
        }
        logger.info(f"MCP Tool registered: {name}")
        
    def execute_tool(self, name: str, args: Dict[str, Any]) -> Any:
        """Execute a registered tool."""
        if name not in self._tools:
            raise ValueError(f"Tool {name} not found.")
        return self._tools[name]["handler"](**args)
        
    def get_available_tools(self) -> List[Dict[str, str]]:
        """List available tools."""
        return [{"name": k, "description": v["description"]} for k, v in self._tools.items()]

# Global MCP provider instance
mcp_provider = MCPProvider()
