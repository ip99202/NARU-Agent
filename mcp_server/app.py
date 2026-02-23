"""
FastMCP 앱 싱글턴 — 모든 Tool이 이 객체에 등록됩니다.
server.py와 tool 파일 간의 순환 임포트를 방지하기 위해 분리합니다.
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("NARU MCP Server")
