"""
Tool: search_institution_code

실제 확인된 API:
  GET /api/bizcomm/inst_cd  → 기관코드 키워드 검색 (instNm 파라미터)
"""
from typing import Optional
from mcp_server.app import mcp
from mcp_server.tools.auth import get_session


@mcp.tool()
async def search_institution_code(instNm: str, size: int = 10) -> dict:
    """
    기관명(한글 또는 영문) 키워드로 기관코드를 조회합니다.
    예: "하나카드" → instCd: "HNCD"

    Args:
        instNm: 기관명 키워드 (예: "하나카드", "SKCC")
        size:   최대 반환 건수 (기본 10)
    """
    session = await get_session()
    params = {
        "pageNo": 1,
        "pageCount": 0,
        "size": size,
        "instCd": "",
        "instNm": instNm,
    }
    resp = await session.get("/api/bizcomm/inst_cd", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "기관코드 조회 실패")}

    rst_data = body.get("rstData", {})
    items = rst_data.get("instCdLst", [])
    total = rst_data.get("pageSet", {}).get("totalRowCount", 0)

    return {
        "keyword": instNm,
        "total": total,
        "results": [
            {"instCd": i.get("instCd"), "instNm": i.get("instNm")}
            for i in items
        ],
    }
