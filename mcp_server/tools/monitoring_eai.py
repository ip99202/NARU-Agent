"""
Tools: 모니터링 API (EAI)
 1. get_queue_depth_monitoring            → GET /api/monitoring/queueDepth
 2. get_eai_if_db_remain_cnt              → GET /api/monitoring/eai/ifDbRemainCnt
"""
from datetime import date
from typing import Optional
from mcp_server.app import mcp
from mcp_server.tools.auth import get_session

def _today() -> str:
    return date.today().strftime("%Y%m%d")

# ─────────────────────────────────────────────────────────────
# 1. MQ 큐 적체량 모니터링
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_queue_depth_monitoring(
    query_date: Optional[str] = None,
) -> dict:
    """
    특정 날짜의 EAI MQ 큐 적체량 현황을 조회합니다.
    depthCnt가 높은 큐를 찾아 시스템 부하 상태를 파악합니다.

    Args:
        query_date: 조회 날짜 (YYYYMMDD, 기본=오늘)

    Returns:
        query_date (str): 조회 날짜
        total_queues (int): 전체 큐 수
        over_threshold_count (int): depthCnt > 0 인 적체 큐 수
        top_queues (list): depthCnt 내림차순 상위 20개 큐 목록
            - queueNm (str): 큐 이름
            - queueManager (str): MQ 매니저 이름
            - depthCnt (int): 현재 큐 메시지 적체 수
            - inQ (int): 인바운드 메시지 수
            - outQ (int): 아웃바운드 메시지 수
            - time (str): 측정 시각 (HHMM)
            - ifNm (str): 인터페이스 이름
            - domainNm (str): 도메인 이름
        over_threshold (list): depthCnt > 0 인 큐 전체 목록 (top_queues와 동일 구조)
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
        return {"error": body.get("rstMsg", "큐 깊이 조회 실패")}

    queues: list = body.get("rstData", {}).get("queueDepthList", [])

    # depthCnt 기준 내림차순 정렬하여 상위 적체 큐 파악
    sorted_queues = sorted(
        queues,
        key=lambda q: int(q.get("depthCnt", 0) or 0),
        reverse=True,
    )
    over_threshold_raw = [q for q in sorted_queues if int(q.get("depthCnt", 0) or 0) > 0]

    def _parse_queue(q: dict) -> dict:
        return {
            "queueNm":      q.get("queueNm"),
            "queueManager": q.get("queueManager"),
            "depthCnt":     q.get("depthCnt"),
            "inQ":          q.get("inQ"),
            "outQ":         q.get("outQ"),
            "time":         q.get("time"),
            "ifNm":         q.get("ifNm"),
            "domainNm":     q.get("domainNm"),
        }

    return {
        "query_date": target_date,
        "total_queues": len(queues),
        "over_threshold_count": len(over_threshold_raw),
        "top_queues": [_parse_queue(q) for q in sorted_queues[:20]],
        "over_threshold": [_parse_queue(q) for q in over_threshold_raw],
    }



# ─────────────────────────────────────────────────────────────
# 2. EAI 인터페이스 DB 잔여 카운트 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_eai_if_db_remain_cnt() -> dict:
    """
    현재 기준 EAI 인터페이스별 DB 잔여 건수(미처리 메시지)를 조회합니다.
    송신(send)/수신(rcv) 유형별로 적체된 레코드 수를 반환합니다.

    Returns:
        total_remain (int): 전체 DB 잔여 건수 합산
        send_total_remain (int): 송신(send) 유형 잔여 건수 합산
        rcv_total_remain (int): 수신(rcv) 유형 잔여 건수 합산
        send_count (int): 송신 인터페이스 수
        rcv_count (int): 수신 인터페이스 수
        db_remain_list (list): 인터페이스별 DB 잔여 상세 정보
            - date (str): 데이터 기준 날짜 (YYYYMMDD)
            - time (str): 측정 시각 (HHMM)
            - type (str): 인터페이스 유형 ('send' 또는 'rcv')
            - tgtTbl (str): 대상 테이블명
            - remain (int): 총 잔여 건수
            - one/two/three/four (int): 시간대·중요도별 잔여 건수
    """
    session = await get_session()

    resp = await session.get("/api/monitoring/eai/ifDbRemainCnt")
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EAI DB 잔여 카운트 조회 실패")}

    items: list = body.get("rstData", {}).get("eaiIfDbRemainList", [])

    send_items = [i for i in items if i.get("type") == "send"]
    rcv_items  = [i for i in items if i.get("type") == "rcv"]

    total_remain      = sum(int(i.get("remain", 0) or 0) for i in items)
    send_total_remain = sum(int(i.get("remain", 0) or 0) for i in send_items)
    rcv_total_remain  = sum(int(i.get("remain", 0) or 0) for i in rcv_items)

    return {
        "total_remain": total_remain,
        "send_total_remain": send_total_remain,
        "rcv_total_remain": rcv_total_remain,
        "send_count": len(send_items),
        "rcv_count": len(rcv_items),
        "db_remain_list": [
            {
                "date":   i.get("date"),
                "time":   i.get("time"),
                "type":   i.get("type"),
                "tgtTbl": i.get("tgtTbl"),
                "remain": i.get("remain"),
                "one":    i.get("one"),
                "two":    i.get("two"),
                "three":  i.get("three"),
                "four":   i.get("four"),
            }
            for i in items
        ],
    }


