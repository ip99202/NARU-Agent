"""
Tool: get_faq_list

자주 묻는 질문(FAQ) 게시판 키워드 검색.
"""
from typing import Optional
from mcp_server.app import mcp
from mcp_server.tools.auth import get_session


@mcp.tool()
async def get_faq_list(keyword: str = "", page: int = 1, size: int = 5) -> dict:
    """
    FAQ 게시판에서 키워드로 관련 정보를 검색합니다.

    Args:
        keyword: 검색 키워드 (예: "인터페이스 신청", "오류 코드")
        page:    페이지 번호
        size:    페이지당 건수
    """
    session = await get_session()
    params = {
        "pageNo": page,
        "pageCount": 0,
        "size": size,
        "srchKeyword": keyword,
    }
    resp = await session.get("/api/bizcomm/board/faq", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "FAQ 조회 실패"), "items": []}

    rst_data = body.get("rstData", {})
    items = rst_data.get("faqList") or rst_data.get("boardList") or []

    return {
        "keyword": keyword,
        "total": rst_data.get("pageSet", {}).get("totalRowCount", 0),
        "items": [
            {
                "title": i.get("boardTitle") or i.get("title"),
                "content": (i.get("boardContent") or i.get("content") or "")[:300],
                "created_at": i.get("creDt"),
            }
            for i in items
        ],
    }
