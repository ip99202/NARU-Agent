"""
Tool: search_institution_code / search_interface_list

브라우저 분석으로 확인한 실제 API:
  GET /api/bizcomm/cccd/orgcd/list/group  → 기관 그룹 목록
  GET /api/bizcomm/allmeta                → 인터페이스 메타 검색 (기관코드, 키워드 등 필터)
"""
from typing import Optional
from mcp_server.server import mcp
from mcp_server.tools.auth import get_session


@mcp.tool()
async def search_institution_code(instNm: str) -> dict:
    """
    기관명(한글 또는 코드)으로 인터페이스 목록에서 사용되는 기관 코드(reqInstCd)를 조회합니다.
    예: "하나카드" → reqInstCd 값 반환

    Args:
        instNm: 기관명 키워드 (예: "하나카드", "SKCC")
    """
    session = await get_session()
    # 기관 코드 그룹 목록 전체 조회 후 키워드로 필터링
    resp = await session.get("/api/bizcomm/cccd/orgcd/list/group")
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "기관 목록 조회 실패")}

    groups = body.get("rstData", {})
    results = []

    # 실제 응답: rstData.ccCdLst 배열
    data_list = groups.get("ccCdLst", []) if isinstance(groups, dict) else []

    keyword = instNm.lower()
    for item in data_list:
        name = str(item.get("orgNm", "")).lower()
        code = str(item.get("orgCd", ""))
        if keyword in name or keyword in code.lower():
            results.append({"instCd": code, "instNm": item.get("orgNm")})

    return {
        "keyword": instNm,
        "count": len(results),
        "results": results[:10],  # 최대 10건
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
