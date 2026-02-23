"""
Tool: search_institution_code / search_interface_list

실제 확인된 API:
  GET /api/bizcomm/inst_cd  → 기관코드 키워드 검색 (instNm 파라미터)
  GET /api/bizcomm/allmeta  → 인터페이스 메타 검색 (기관코드, 키워드 등 필터)
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


@mcp.tool()
async def search_interface_list(
    instCd: Optional[str] = None,
    keyword: Optional[str] = None,
    ifTypCd: Optional[str] = None,
    page: int = 1,
    size: int = 10,
) -> dict:
    """
    인터페이스 목록(EAI/EIGW/MCG 통합)을 조회합니다.

    Args:
        instCd:  기관코드 필터 (예: "HNCD")
        keyword: 인터페이스명 키워드 검색
        ifTypCd: 인터페이스 유형 필터 (EAI, EIGW, MCG 등)
        page:    페이지 번호 (기본 1)
        size:    페이지당 건수 (기본 10)
    """
    session = await get_session()
    params = {
        "pageNo": page,
        "pageCount": 0,
        "size": size,
        "srchType": "",
        "srchKeyword": keyword or "",
        "ifTypCd": ifTypCd or "",
        "reqInstCd": instCd or "",
        "useYn": "Y",
    }
    resp = await session.get("/api/bizcomm/allmeta", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "인터페이스 목록 조회 실패")}

    rst_data = body.get("rstData", {})
    page_set = rst_data.get("pageSet", {})
    items = rst_data.get("allMetaList", [])

    return {
        "total": page_set.get("totalRowCount", 0),
        "page": page,
        "size": size,
        "items": [
            {
                "ifId": i.get("eaiIfId") or i.get("eigwIfId") or i.get("mcgIfId"),
                "ifNm": i.get("eaiIfNmKor") or i.get("ifNmKor"),
                "ifTyp": i.get("ifTypNm"),
                "instCd": i.get("reqInstCd") or i.get("eigwInstCd"),
                "sndSys": i.get("sndSysId"),
                "rcvSys": i.get("rcvSysId"),
            }
            for i in items
        ],
    }
