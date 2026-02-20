"""
NARU MCP Server 메인

FastMCP를 사용하여 NARU API를 MCP Tool로 래핑합니다.
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("NARU MCP Server")

# 모든 Tool 등록
from mcp_server.tools import institution  # noqa: F401, E402
from mcp_server.tools import eigw         # noqa: F401, E402
from mcp_server.tools import queue        # noqa: F401, E402
from mcp_server.tools import faq          # noqa: F401, E402

if __name__ == "__main__":
    mcp.run(transport="stdio")
