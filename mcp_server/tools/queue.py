"""
Tool: get_queue_depth / get_queue_depth_detail

브라우저 분석으로 확인한 실제 API:
  GET /api/monitoring/queueDepth?date=YYYYMMDD                         → 전체 큐 적체량
  GET /api/monitoring/queueDepth/queueNm?time=HHMM&date=YYYYMMDD&...  → 특정 큐 상세
"""
from datetime import date, datetime
from typing import Optional
from mcp_server.app import mcp
from mcp_server.tools.auth import get_session


def _today() -> str:
    return date.today().strftime("%Y%m%d")

def _now_hhmm() -> str:
    return datetime.now().strftime("%H%M")


@mcp.tool()
async def get_queue_depth(query_date: Optional[str] = None) -> dict:
    """
    MQ 큐 전체 적체량 현황을 조회합니다. 시스템 부하 상태를 파악합니다.

    Args:
        query_date: 조회 날짜 (YYYYMMDD, 기본=오늘)
    """
    session = await get_session()
    target_date = query_date or _today()

    resp = await session.get(
        "/api/monitoring/queueDepth",
        params={"date": target_date},
    )
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "큐 적체량 조회 실패")}

    rst_data = body.get("rstData", {})
    # 실제 응답 키: queueDepthList
    queues = rst_data.get("queueDepthList", [])

    # 적체량(depthCnt)이 0보다 큰 큐
    over_threshold = [
        q for q in queues
        if int(q.get("depthCnt", 0) or 0) > 0
    ]

    return {
        "query_date": target_date,
        "total_queues": len(queues),
        "over_threshold_count": len(over_threshold),
        "queues": [
            {
                "queueNm":      q.get("queueNm"),
                "queueManager": q.get("queueManager"),
                "depthCnt":     q.get("depthCnt"),
                "inQ":          q.get("inQ"),
                "outQ":         q.get("outQ"),
                "time":         q.get("time"),
            }
            for q in queues
        ],
        "over_threshold": [
            {
                "queueNm":  q.get("queueNm"),
                "manager":  q.get("queueManager"),
                "depthCnt": q.get("depthCnt"),
            }
            for q in over_threshold
        ],
    }


@mcp.tool()
async def get_queue_depth_detail(
    queue_nm: str,
    queue_manager: str,
    query_date: Optional[str] = None,
    time: Optional[str] = None,
) -> dict:
    """
    특정 MQ 큐의 시간대별 상세 적체량을 조회합니다.

    Args:
        queue_nm:      큐 이름 (예: "QL.EIGW.REQ")
        queue_manager: MQ 매니저 이름
        query_date:    조회 날짜 (YYYYMMDD, 기본=오늘)
        time:          조회 시각 (HHMM, 기본=현재)
    """
    session = await get_session()
    params = {
        "date": query_date or _today(),
        "time": time or _now_hhmm(),
        "queueNm": queue_nm,
        "queueManager": queue_manager,
    }
    resp = await session.get("/api/monitoring/queueDepth/queueNm", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "큐 상세 조회 실패")}

    return {
        "queue_nm": queue_nm,
        "queue_manager": queue_manager,
        "data": body.get("rstData", {}),
    }
