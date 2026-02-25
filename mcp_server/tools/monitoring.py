"""
Tools: 모니터링 API 4종

1. get_queue_depth_monitoring   → GET /api/monitoring/queueDepth?date=YYYYMMDD
2. get_eigw_online_error_list   → GET /api/monitoring/eigw/onlineErrorList
3. get_eai_if_db_remain_cnt     → GET /api/monitoring/eai/ifDbRemainCnt
4. get_mcg_chnl_status_all      → GET /api/monitoring/mcg/chnlStatusAll
"""
from datetime import date
from typing import Optional
from mcp_server.app import mcp
from mcp_server.tools.auth import get_session


def _today() -> str:
    return date.today().strftime("%Y%m%d")


# ─────────────────────────────────────────────────────────────
# 1. MQ 큐 깊이(Queue Depth) 모니터링
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
# 2. EIGW 온라인 에러 목록 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_eigw_online_error_list() -> dict:
    """
    현재 기준 EIGW(Enterprise Internet Gateway) 시스템에서 발생한
    온라인 에러 목록을 조회합니다.
    오류 코드별(F001/F002/F004/F005/기타) 건수와 담당자 정보를 반환합니다.

    Returns:
        total_error_count (int): 전체 오류 건수 합산
        error_type_summary (dict): 오류 코드별 건수
            - F001 (int): F001 오류 건수
            - F002 (int): F002 오류 건수
            - F004 (int): F004 오류 건수
            - F005 (int): F005 오류 건수
            - etc  (int): 기타 오류 건수
        interface_count (int): 오류가 발생한 인터페이스 수
        error_list (list): 인터페이스별 상세 오류 정보
            - sysNm (str): 시스템명 (예: skt-mgwdap01)
            - eaiIfId (str): EAI 인터페이스 ID
            - onlineDealNm (str): 온라인 거래명
            - conf (str): 서비스/구성 코드
            - totCnt (int): 전체 처리 건수
            - normalCnt (int): 정상 처리 건수
            - errorF001~errorEtc (int): 각 오류 유형별 건수
            - time (str): 측정 시각 (HHMM)
            - instCd (str): 기관 코드
            - rcvChrgrOrgNm1 (str): 수신 담당 조직명
            - rcvChrgrNm1 (str): 수신 담당자 이름
            - sndChrgrOrgNm1 (str): 발신 담당 조직명
            - sndChrgrNm1 (str): 발신 담당자 이름
    """
    session = await get_session()

    resp = await session.get("/api/monitoring/eigw/onlineErrorList")
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EIGW 온라인 에러 목록 조회 실패")}

    items: list = body.get("rstData", {}).get("eigwOnlineErrorList", [])

    total_errors = sum(int(i.get("totCnt", 0) or 0) for i in items)

    # 오류 유형별 합산
    error_summary = {
        "F001": sum(int(i.get("errorF001", 0) or 0) for i in items),
        "F002": sum(int(i.get("errorF002", 0) or 0) for i in items),
        "F004": sum(int(i.get("errorF004", 0) or 0) for i in items),
        "F005": sum(int(i.get("errorF005", 0) or 0) for i in items),
        "etc":  sum(int(i.get("errorEtc",  0) or 0) for i in items),
    }

    return {
        "total_error_count": total_errors,
        "error_type_summary": error_summary,
        "interface_count": len(items),
        "error_list": [
            {
                "sysNm":          i.get("sysNm"),
                "eaiIfId":        i.get("eaiIfId"),
                "onlineDealNm":   i.get("onlineDealNm"),
                "conf":           i.get("conf"),
                "totCnt":         i.get("totCnt"),
                "normalCnt":      i.get("normalCnt"),
                "errorF001":      i.get("errorF001"),
                "errorF002":      i.get("errorF002"),
                "errorF004":      i.get("errorF004"),
                "errorF005":      i.get("errorF005"),
                "errorEtc":       i.get("errorEtc"),
                "time":           i.get("time"),
                "instCd":         i.get("instCd"),
                "rcvChrgrOrgNm1": i.get("rcvChrgrOrgNm1"),
                "rcvChrgrNm1":    i.get("rcvChrgrNm1"),
                "sndChrgrOrgNm1": i.get("sndChrgrOrgNm1"),
                "sndChrgrNm1":    i.get("sndChrgrNm1"),
            }
            for i in items
        ],
    }


# ─────────────────────────────────────────────────────────────
# 3. EAI 인터페이스 DB 잔여 카운트 조회
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


# ─────────────────────────────────────────────────────────────
# 4. MCG 전체 채널 상태 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_mcg_chnl_status_all(
    page_no: int = 1,
    size: int = 10,
    outbound_yn: str = "Y",
    all_server_yn: str = "Y",
    use_yn: str = "Y",
) -> dict:
    """
    MCG(Multi-Channel Gateway)의 전체 채널 상태(아웃바운드 TPS, SWG, 인바운드)를 조회합니다.
    FOK(Fail OK) 상태인 채널을 식별하여 이상 여부를 파악합니다.

    Args:
        page_no:       페이지 번호 (기본=1)
        size:          한 페이지당 건수 (기본=10)
        outbound_yn:   아웃바운드 포함 여부 Y/N (기본=Y)
        all_server_yn: 모든 서버 포함 여부 Y/N (기본=Y)
        use_yn:        사용 중인 채널만 조회 Y/N (기본=Y)

    Returns:
        outbound_channel_count (int): 아웃바운드 채널 수 (현재 페이지)
        swg_count (int): SWG(소프트웨어 게이트웨이) 수
        inbound_channel_count (int): 인바운드 채널 수 (현재 페이지)
        fok_summary (dict): FOK(이상) 채널 수 요약
            - outbound_fok (int): 아웃바운드 FOK 채널 수
            - swg_fok (int): SWG FOK 수
            - inbound_fok (int): 인바운드 FOK 채널 수
        outbound_tps_status (list): 아웃바운드 채널 TPS 상태
            - server (str): 서버명 (예: MCGD)
            - chnlId (str): 채널 ID
            - chnlNm (str): 채널 이름
            - chnlTyp (str): 채널 유형 (OUTBOUND / Ch to Ch)
            - opCd (str): 운영 코드
            - tps (float): 초당 트랜잭션 수
            - status (str): 상태 ('OK' 정상 / 'FOK' 이상)
            - chrgrNm (str): 담당자 이름
            - time (str): 측정 시각 (HHMM)
        swg_status (list): SWG 연결 상태
            - server (str): 서버명
            - dgwName (str): 게이트웨이 이름
            - ip (str): IP 주소
            - port (str): 포트 번호
            - status (str): 상태 ('OK' / 'FOK')
            - time (str): 측정 시각 (HHMM)
        inbound_channel_status (list): 인바운드 채널 상태
            - server (str): 서버명
            - user (str): 사용자 ID
            - cntSum (float): 누적 카운트 합계
            - status (str): 상태 ('OK' / 'FOK')
        pagination (dict): 각 섹션별 페이지네이션 정보
            - page_set_out: 아웃바운드 페이지 정보 (size, pageNo, totalRowCount, pageCount)
            - page_set_swg: SWG 페이지 정보
            - page_set_in: 인바운드 페이지 정보
    """
    session = await get_session()

    params = {
        "pageNo":       page_no,
        "pageCount":    0,
        "size":         size,
        "outboundYn":   outbound_yn,
        "allServerYn":  all_server_yn,
        "useYn":        use_yn,
    }

    resp = await session.get("/api/monitoring/mcg/chnlStatusAll", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "MCG 채널 상태 조회 실패")}

    rst_data = body.get("rstData", {})
    out_tps: list  = rst_data.get("mcgOutTpsStatus", [])
    swg: list      = rst_data.get("mcgSwgStatus", [])
    in_chnl: list  = rst_data.get("mcgInChnlStatus", [])

    # FOK(이상) 채널 분류
    fok_out = [c for c in out_tps if c.get("status") == "FOK"]
    fok_swg = [c for c in swg     if c.get("status") == "FOK"]
    fok_in  = [c for c in in_chnl if c.get("status") == "FOK"]

    return {
        "outbound_channel_count": len(out_tps),
        "swg_count":              len(swg),
        "inbound_channel_count":  len(in_chnl),
        "fok_summary": {
            "outbound_fok": len(fok_out),
            "swg_fok":      len(fok_swg),
            "inbound_fok":  len(fok_in),
        },
        "outbound_tps_status": [
            {
                "server":   c.get("server"),
                "chnlId":   c.get("chnlId"),
                "chnlNm":   c.get("chnlNm"),
                "chnlTyp":  c.get("chnlTyp"),
                "opCd":     c.get("opCd"),
                "tps":      c.get("tps"),
                "status":   c.get("status"),
                "chrgrNm":  c.get("chrgrNm"),
                "time":     c.get("time"),
            }
            for c in out_tps
        ],
        "swg_status": [
            {
                "server":   c.get("server"),
                "dgwName":  c.get("dgwName"),
                "ip":       c.get("ip"),
                "port":     c.get("port"),
                "status":   c.get("status"),
                "time":     c.get("time"),
            }
            for c in swg
        ],
        "inbound_channel_status": [
            {
                "server": c.get("server"),
                "user":   c.get("user"),
                "cntSum": c.get("cntSum"),
                "status": c.get("status"),
            }
            for c in in_chnl
        ],
        "pagination": {
            "page_set_out": rst_data.get("pageSetOut"),
            "page_set_swg": rst_data.get("pageSetSwg"),
            "page_set_in":  rst_data.get("pageSetIn"),
        },
    }
