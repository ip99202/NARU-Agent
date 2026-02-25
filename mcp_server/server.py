"""
NARU MCP Server 메인

FastMCP를 사용하여 NARU API를 MCP Tool로 래핑합니다.
"""
import sys
import os

# 서브프로세스로 실행될 때도 프로젝트 루트를 PYTHONPATH에 추가
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

# app.py의 mcp 싱글턴 임포트
from mcp_server.app import mcp  # noqa: E402

# 모든 Tool 등록 (임포트하면 @mcp.tool() 데코레이터가 자동으로 mcp에 등록됨)
import mcp_server.tools.institution   # noqa: F401, E402
import mcp_server.tools.eigw          # noqa: F401, E402
import mcp_server.tools.faq           # noqa: F401, E402
import mcp_server.tools.monitoring    # noqa: F401, E402
import mcp_server.tools.statistic_eai  # noqa: F401, E402
import mcp_server.tools.statistic_eigw # noqa: F401, E402
import mcp_server.tools.statistic_mcg  # noqa: F401, E402

if __name__ == "__main__":
    mcp.run(transport="stdio")
