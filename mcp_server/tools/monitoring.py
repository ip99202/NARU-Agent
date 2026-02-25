"""
Tools: 모니터링 API 10종

[EAI]
 1. get_queue_depth_monitoring            → GET /api/monitoring/queueDepth
 2. get_eai_if_db_remain_cnt              → GET /api/monitoring/eai/ifDbRemainCnt

[EIGW]
 3. get_eigw_online_error_list            → GET /api/monitoring/eigw/onlineErrorList
 4. get_eigw_online_error_graph           → GET /api/monitoring/eigw/onlineErrorList/graph
 5. get_eigw_online_trms_cnt_list         → GET /api/monitoring/eigw/onlineTrmsCntList
 6. get_eigw_online_elap_list             → GET /api/monitoring/eigw/onlineElapList
 7. get_eigw_file_trms_list               → GET /api/monitoring/eigw/fileTrmsList

[MCG]
 8. get_mcg_chnl_status_all              → GET /api/monitoring/mcg/chnlStatusAll
 9. get_mcg_out_tps_status               → GET /api/monitoring/mcg/outTpsStatus
10. get_mcg_chnl_status_in               → GET /api/monitoring/mcg/chnlStatusIn
11. get_mcg_chnl_status_out              → GET /api/monitoring/mcg/chnlStatusOut
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
            - F001 (int): 연결 오류 (대외기관 접속 불가)
            - F002 (int): 데몬 미기동 (대외기관 데몬 접속 불가)
            - F004 (int): 수신 오류 (응답 전문 수신 대기 중 타임아웃)
            - F005 (int): 송신 오류 ('SKT-> 기관'으로 전송 중 문제)
            - etc  (int): 기타 (HTTP 연동 중 오류 등)
        interface_count (int): 오류가 발생한 인터페이스 수
        error_list (list): 인터페이스별 상세 오류 정보
            - sysNm (str): 시스템명 (예: skt-mgwdap01)
            - eaiIfId (str): EAI 인터페이스 ID
            - onlineDealNm (str): 온라인 거래명
            - conf (str): 서비스/구성 코드
            - totCnt (int): 전체 처리 건수
            - normalCnt (int): 정상 처리 건수
            - errorF001 (int): 연결 오류 (대외기관 접속 불가)
            - errorF002 (int): 데몬 미기동 (대외기관 데몬 접속 불가)
            - errorF004 (int): 수신 오류 (응답 전문 수신 대기 중 타임아웃)
            - errorF005 (int): 송신 오류 ('SKT-> 기관'으로 전송 중 문제)
            - errorEtc  (int): 기타 (HTTP 연동 중 오류 등)
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


# ═════════════════════════════════════════════════════════════
# EIGW 추가 API
# ═════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────
# 5. EIGW 온라인 에러건수 그래프 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_eigw_online_error_graph(
    query_date: Optional[str] = None,
    time: Optional[str] = None,
    interval: int = -60,
    eai_if_id: Optional[str] = None,
    inst_cd: Optional[str] = None,
    input_conf: Optional[str] = None,
) -> dict:
    """
    특정 EIGW 인터페이스의 시간대별 온라인 에러건수 그래프 데이터를 조회합니다.
    지정 시간 기준으로 interval 분 이전까지의 구간에서 발생한 에러 이력을 확인합니다.

    Args:
        query_date:  조회 날짜 (YYYYMMDD, 기본=오늘)
        time:        조회 기준 시각 (HHMM, 예: '2000')
        interval:    조회 구간 (분, 음수=과거 방향, 기본=-60)
        eai_if_id:   EAI 인터페이스 ID (예: 'MVS.EGW_KCTT_CUST_INFO_MFF')
        inst_cd:     기관 코드 필터 (빈 값=전체)
        input_conf:  설정 코드 필터 (빈 값=전체)

    Returns:
        query_date (str): 조회 날짜
        interval (int): 조회 구간(분)
        total_error_count (int): 기간 내 전체 에러 건수 합산
        error_type_summary (dict): F001/F002/F004/F005/etc 유형별 합산
            - F001 (int): 연결 오류 (대외기관 접속 불가)
            - F002 (int): 데몬 미기동 (대외기관 데몬 접속 불가)
            - F004 (int): 수신 오류 (응답 전문 수신 대기 중 타임아웃)
            - F005 (int): 송신 오류 ('SKT-> 기관'으로 전송 중 문제)
            - etc  (int): 기타 (HTTP 연동 중 오류 등)
        item_count (int): 반환된 항목 수
        error_graph_list (list): 시간대별 에러 상세 목록
            - date (str): 날짜 (YYYYMMDD)
            - time (str): 측정 시각 (HHMM)
            - eaiIfId (str): EAI 인터페이스 ID
            - onlineDealNm (str): 온라인 거래명
            - sysNm (str): 시스템명
            - conf (str): 설정 코드
            - instCd (str): 기관 코드
            - totCnt (int): 총 건수
            - normalCnt (int): 정상 처리 건수
            - errorF001 (int): 연결 오류 (대외기관 접속 불가)
            - errorF002 (int): 데몬 미기동 (대외기관 데몬 접속 불가)
            - errorF004 (int): 수신 오류 (응답 전문 수신 대기 중 타임아웃)
            - errorF005 (int): 송신 오류 ('SKT-> 기관'으로 전송 중 문제)
            - errorEtc  (int): 기타 (HTTP 연동 중 오류 등)
            - rcvChrgrOrgNm1/rcvChrgrNm1 (str): 수신 담당 조직/담당자
            - sndChrgrOrgNm1/sndChrgrNm1 (str): 송신 담당 조직/담당자
    """
    session = await get_session()
    target_date = query_date or _today()

    params: dict = {
        "date":      target_date,
        "interval":  interval,
        "eaiIfId":   eai_if_id or "",
        "instCd":    inst_cd or "",
        "inputConf": input_conf or "",
    }
    if time:
        params["time"] = time

    resp = await session.get("/api/monitoring/eigw/onlineErrorList/graph", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EIGW 온라인 에러 그래프 조회 실패")}

    items: list = body.get("rstData", {}).get("eigwOnlineErrorList", [])

    error_summary = {
        "F001": sum(int(i.get("errorF001", 0) or 0) for i in items),
        "F002": sum(int(i.get("errorF002", 0) or 0) for i in items),
        "F004": sum(int(i.get("errorF004", 0) or 0) for i in items),
        "F005": sum(int(i.get("errorF005", 0) or 0) for i in items),
        "etc":  sum(int(i.get("errorEtc",  0) or 0) for i in items),
    }

    return {
        "query_date":         target_date,
        "interval":           interval,
        "total_error_count":  sum(error_summary.values()),
        "error_type_summary": error_summary,
        "item_count":         len(items),
        "error_graph_list": [
            {
                "date":           i.get("date"),
                "time":           i.get("time"),
                "eaiIfId":        i.get("eaiIfId"),
                "onlineDealNm":   i.get("onlineDealNm"),
                "sysNm":          i.get("sysNm"),
                "conf":           i.get("conf"),
                "instCd":         i.get("instCd"),
                "totCnt":         i.get("totCnt"),
                "normalCnt":      i.get("normalCnt"),
                "errorF001":      i.get("errorF001"),
                "errorF002":      i.get("errorF002"),
                "errorF004":      i.get("errorF004"),
                "errorF005":      i.get("errorF005"),
                "errorEtc":       i.get("errorEtc"),
                "rcvChrgrOrgNm1": i.get("rcvChrgrOrgNm1"),
                "rcvChrgrNm1":    i.get("rcvChrgrNm1"),
                "sndChrgrOrgNm1": i.get("sndChrgrOrgNm1"),
                "sndChrgrNm1":    i.get("sndChrgrNm1"),
            }
            for i in items
        ],
    }


# ─────────────────────────────────────────────────────────────
# 6. EIGW 온라인 연동량(트랜잭션 카운트) 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_eigw_online_trms_cnt_list(
    query_date: Optional[str] = None,
    time: Optional[str] = None,
    interval: int = -30,
    eai_if_id: Optional[str] = None,
    inst_cd: Optional[str] = None,
    input_conf: Optional[str] = None,
) -> dict:
    """
    특정 EIGW 인터페이스의 온라인 연동량(트랜잭션 건수)을 조회합니다.
    지정 시간 기준으로 interval 분 이전까지의 구간에서 정상/에러 처리 건수를 반환합니다.

    Args:
        query_date:  조회 날짜 (YYYYMMDD, 기본=오늘)
        time:        조회 기준 시각 (HHMM, 예: '2222')
        interval:    조회 구간 (분, 음수=과거 방향, 기본=-30)
        eai_if_id:   EAI 인터페이스 ID (예: 'ORD.EGW_KAIT_MLINE_INFO_RGST_MAU')
        inst_cd:     기관 코드 필터 (빈 값=전체)
        input_conf:  설정 코드 필터 (빈 값=전체)

    Returns:
        query_date (str): 조회 날짜
        interval (int): 조회 구간(분)
        total_cnt (int): 전체 트랜잭션 건수 합산
        normal_cnt (int): 전체 정상 처리 건수 합산
        fail_total_cnt (int): 전체 실패 건수 합산
        item_count (int): 반환된 항목 수
        trms_cnt_list (list): 트랜잭션 카운트 목록
            - time (str): 측정 시각 (HHMM)
            - eaiIfId (str): EAI 인터페이스 ID
            - onlineDealNm (str): 온라인 거래명
            - sysNm (str): 시스템명
            - conf (str): 설정 코드
            - instCd (str): 기관 코드
            - mntgYn (str): 모니터링 여부 (Y/N)
            - totCnt (int): 총 트랜잭션 건수
            - normalCnt (int): 정상 처리 건수
            - failTotCnt (int): 총 실패 건수
            - errorF001 (int): 연결 오류 (대외기관 접속 불가)
            - errorF002 (int): 데몬 미기동 (대외기관 데몬 접속 불가)
            - errorF004 (int): 수신 오류 (응답 전문 수신 대기 중 타임아웃)
            - errorF005 (int): 송신 오류 ('SKT-> 기관'으로 전송 중 문제)
            - errorEtc  (int): 기타 (HTTP 연동 중 오류 등)
            - rcvChrgrOrgNm1/rcvChrgrNm1 (str): 수신 담당 조직/담당자
            - sndChrgrOrgNm1/sndChrgrNm1 (str): 송신 담당 조직/담당자
    """
    session = await get_session()
    target_date = query_date or _today()

    params: dict = {
        "date":      target_date,
        "interval":  interval,
        "eaiIfId":   eai_if_id or "",
        "instCd":    inst_cd or "",
        "inputConf": input_conf or "",
    }
    if time:
        params["time"] = time

    resp = await session.get("/api/monitoring/eigw/onlineTrmsCntList", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EIGW 온라인 연동량 조회 실패")}

    items: list = body.get("rstData", {}).get("eigwOnlineTrmsCntList", [])

    return {
        "query_date":     target_date,
        "interval":       interval,
        "total_cnt":      sum(int(i.get("totCnt",     0) or 0) for i in items),
        "normal_cnt":     sum(int(i.get("normalCnt",  0) or 0) for i in items),
        "fail_total_cnt": sum(int(i.get("failTotCnt", 0) or 0) for i in items),
        "item_count":     len(items),
        "trms_cnt_list": [
            {
                "time":           i.get("time"),
                "eaiIfId":        i.get("eaiIfId"),
                "onlineDealNm":   i.get("onlineDealNm"),
                "sysNm":          i.get("sysNm"),
                "conf":           i.get("conf"),
                "instCd":         i.get("instCd"),
                "mntgYn":         i.get("mntgYn"),
                "totCnt":         i.get("totCnt"),
                "normalCnt":      i.get("normalCnt"),
                "failTotCnt":     i.get("failTotCnt"),
                "errorF001":      i.get("errorF001"),
                "errorF002":      i.get("errorF002"),
                "errorF004":      i.get("errorF004"),
                "errorF005":      i.get("errorF005"),
                "errorEtc":       i.get("errorEtc"),
                "rcvChrgrOrgNm1": i.get("rcvChrgrOrgNm1"),
                "rcvChrgrNm1":    i.get("rcvChrgrNm1"),
                "sndChrgrOrgNm1": i.get("sndChrgrOrgNm1"),
                "sndChrgrNm1":    i.get("sndChrgrNm1"),
            }
            for i in items
        ],
    }


# ─────────────────────────────────────────────────────────────
# 7. EIGW 온라인 응답속도(경과 시간) 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_eigw_online_elap_list(
    query_date: Optional[str] = None,
    time: Optional[str] = None,
    interval: int = -60,
    eai_if_id: Optional[str] = None,
    inst_cd: Optional[str] = None,
    input_conf: Optional[str] = None,
    order_by_rle: str = "ELAP",
    page_no: int = 1,
    page_count: int = 1,
    size: int = 20,
) -> dict:
    """
    EIGW 온라인 인터페이스의 응답속도(경과 시간) 통계를 조회합니다.
    평균/최소/최대 응답 시간과 성공·실패 건수를 페이지 단위로 반환합니다.

    Args:
        query_date:   조회 날짜 (YYYYMMDD, 기본=오늘)
        time:         조회 기준 시각 (HHMM, 빈 값=제한 없음)
        interval:     조회 구간 (분, 음수=과거 방향, 기본=-60)
        eai_if_id:    EAI 인터페이스 ID
        inst_cd:      기관 코드 필터 (빈 값=전체)
        input_conf:   설정 코드 필터 (빈 값=전체)
        order_by_rle: 정렬 기준 (기본='ELAP' — 경과 시간 내림차순)
        page_no:      페이지 번호 (기본=1)
        page_count:   페이지 수 (기본=1)
        size:         페이지당 건수 (기본=20)

    Returns:
        query_date (str): 조회 날짜
        interval (int): 조회 구간(분)
        item_count (int): 반환된 항목 수
        elap_list (list): 응답속도 상세 목록
            - date (str): 날짜
            - time (str): 측정 시각 (HHMM)
            - eaiIfId (str): EAI 인터페이스 ID
            - onlineDealNm (str): 온라인 거래명
            - sysNm (str): 시스템명
            - conf (str): 설정 코드
            - instCd (str): 기관 코드
            - aggreMthd (str): 집계 방식 (예: MAU)
            - pgmTyp (str): 프로그램 유형 (CLIENT/SERVER)
            - srGb (str): 서비스 그룹
            - totCnt (int): 총 트랜잭션 건수
            - normalCnt (int): 정상 처리 건수
            - failTotCnt (int): 총 실패 건수
            - elapTotCnt (int): 경과 시간 집계 건수
            - elapCnt (int): 경과 시간 측정 건수
            - elapMin (float): 최소 응답 시간(초)
            - elapMax (float): 최대 응답 시간(초)
            - elapAvg (float): 평균 응답 시간(초)
            - elapTotAvg (float): 전체 평균 응답 시간(초)
            - errorF001 (int): 연결 오류 (대외기관 접속 불가)
            - errorF002 (int): 데몬 미기동 (대외기관 데몬 접속 불가)
            - errorF004 (int): 수신 오류 (응답 전문 수신 대기 중 타임아웃)
            - errorF005 (int): 송신 오류 ('SKT-> 기관'으로 전송 중 문제)
            - errorEtc  (int): 기타 (HTTP 연동 중 오류 등)
    """
    session = await get_session()
    target_date = query_date or _today()

    params: dict = {
        "date":       target_date,
        "interval":   interval,
        "eaiIfId":    eai_if_id or "",
        "instCd":     inst_cd or "",
        "inputConf":  input_conf or "",
        "orderByRle": order_by_rle,
        "pageNo":     page_no,
        "pageCount":  page_count,
        "size":       size,
    }
    if time:
        params["time"] = time

    resp = await session.get("/api/monitoring/eigw/onlineElapList", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EIGW 온라인 응답속도 조회 실패")}

    items: list = body.get("rstData", {}).get("eigwElapDetail", [])

    return {
        "query_date": target_date,
        "interval":   interval,
        "item_count": len(items),
        "elap_list": [
            {
                "date":        i.get("date"),
                "time":        i.get("time"),
                "eaiIfId":     i.get("eaiIfId"),
                "onlineDealNm": i.get("onlineDealNm"),
                "sysNm":       i.get("sysNm"),
                "conf":        i.get("conf"),
                "instCd":      i.get("instCd"),
                "aggreMthd":   i.get("aggreMthd"),
                "pgmTyp":      i.get("pgmTyp"),
                "srGb":        i.get("srGb"),
                "totCnt":      i.get("totCnt"),
                "normalCnt":   i.get("normalCnt"),
                "failTotCnt":  i.get("failTotCnt"),
                "elapTotCnt":  i.get("elapTotCnt"),
                "elapCnt":     i.get("elapCnt"),
                "elapMin":     i.get("elapMin"),
                "elapMax":     i.get("elapMax"),
                "elapAvg":     i.get("elapAvg"),
                "elapTotAvg":  i.get("elapTotAvg"),
                "errorF001":   i.get("errorF001"),
                "errorF002":   i.get("errorF002"),
                "errorF004":   i.get("errorF004"),
                "errorF005":   i.get("errorF005"),
                "errorEtc":    i.get("errorEtc"),
            }
            for i in items
        ],
    }


# ─────────────────────────────────────────────────────────────
# 8. EIGW 파일 연동량 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_eigw_file_trms_list(
    query_date: Optional[str] = None,
    time: Optional[str] = None,
    interval: int = -30,
    eai_if_id: Optional[str] = None,
    inst_cd: Optional[str] = None,
    file_nm: Optional[str] = None,
    input_conf: Optional[str] = None,
    st_cd_list: str = "SUCC,FAIL,REPROC",
    is_using_time_condition: bool = False,
    page_no: int = 1,
    size: int = 20,
) -> dict:
    """
    EIGW 파일 연동 트랜잭션 목록을 조회합니다.
    성공(SUCC)/실패(FAIL)/재처리(REPROC) 상태별 파일 트랜잭션 이력을 반환합니다.

    판단 기준:
        - stCd==0          → 실패
        - stCd==1, failCnt>0 → 재처리 완료
        - stCd==1, failCnt==0 → 성공
        - stCd==2          → 수동처리 완료

    Args:
        query_date:             조회 날짜 (YYYYMMDD, 기본=오늘)
        time:                   조회 기준 시각 (HHMM, 예: '2230')
        interval:               조회 구간 (분, 음수=과거 방향, 기본=-30)
        eai_if_id:              EAI 인터페이스 ID 필터
        inst_cd:                기관 코드 필터
        file_nm:                파일 이름 필터
        input_conf:             설정 코드 필터
        st_cd_list:             상태 코드 필터 (기본='SUCC,FAIL,REPROC')
        is_using_time_condition: 시간 조건 사용 여부 (기본=False)
        page_no:                페이지 번호 (기본=1)
        size:                   페이지당 건수 (기본=20)

    Returns:
        query_date (str): 조회 날짜
        page_set (dict): 페이지네이션 정보
            - size / pageNo / totalRowCount / pageCount / offset
        item_count (int): 현재 페이지 항목 수
        file_trms_list (list): 파일 트랜잭션 목록
            - date (str): 날짜
            - time (str): 트랜잭션 발생 시각
            - fileNm (str): 파일 이름
            - instCd (str): 기관 코드
            - instNm (str): 기관 이름
            - fileSz (int): 파일 크기(바이트)
            - firstTrmsDtm (str): 최초 트랜잭션 일시
            - reProcTm (str): 재처리 시간
            - manualProcTm (str): 수동 처리 시간
            - finalStCd (str): 최종 상태 코드
            - failCnt (int): 실패 건수
            - opCl (str): 운영 분류
            - sendRcvCl (str): 송/수신 분류 (S=송신, R=수신)
            - display_status (str): 표시용 상태 (성공/실패/재처리 완료/수동처리 완료/N/A)
    """
    session = await get_session()
    target_date = query_date or _today()

    params: dict = {
        "date":                 target_date,
        "interval":             interval,
        "eaiIfId":              eai_if_id or "",
        "instCd":               inst_cd or "",
        "fileNm":               file_nm or "",
        "inputConf":            input_conf or "",
        "stCdList":             st_cd_list,
        "isUsingtimeCondition": str(is_using_time_condition).lower(),
        "pageNo":               page_no,
        "pageCount":            0,
        "size":                 size,
    }
    if time:
        params["time"] = time

    resp = await session.get("/api/monitoring/eigw/fileTrmsList", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EIGW 파일 연동량 조회 실패")}

    rst_data = body.get("rstData", {})
    items: list = rst_data.get("eigwFileTrmsList", [])

    def _display_st(st_cd, fail_cnt) -> str:
        st  = str(st_cd) if st_cd is not None else ""
        cnt = int(fail_cnt or 0)
        if st == "0":                return "실패"
        elif st == "1" and cnt > 0: return "재처리 완료"
        elif st == "1" and cnt == 0: return "성공"
        elif st == "2":              return "수동처리 완료"
        else:                        return "N/A"

    return {
        "query_date": target_date,
        "page_set":   rst_data.get("pageSet"),
        "item_count": len(items),
        "file_trms_list": [
            {
                "date":         i.get("date"),
                "time":         i.get("time"),
                "fileNm":       i.get("fileNm"),
                "instCd":       i.get("instCd"),
                "instNm":       i.get("instNm"),
                "fileSz":       i.get("fileSz"),
                "firstTrmsDtm": i.get("firstTrmsDtm"),
                "reProcTm":     i.get("reProcTm"),
                "manualProcTm": i.get("manualProcTm"),
                "finalStCd":    i.get("finalStCd"),
                "failCnt":      i.get("failCnt"),
                "opCl":         i.get("opCl"),
                "sendRcvCl":    i.get("sendRcvCl"),
                "display_status": _display_st(i.get("finalStCd"), i.get("failCnt")),
            }
            for i in items
        ],
    }


# ═════════════════════════════════════════════════════════════
# MCG 추가 API
# ═════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────
# 9. MCG 아웃바운드 TPS 상태 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_mcg_out_tps_status(
    query_date: Optional[str] = None,
    time: Optional[str] = None,
    interval: int = -120,
    op_cd: Optional[str] = None,
    chnl_id: Optional[str] = None,
    page_no: int = 1,
    page_count: int = 1,
    size: int = 20,
) -> dict:
    """
    MCG 아웃바운드 채널별 TPS(Transactions Per Second) 이력을 조회합니다.
    특정 채널 또는 업무 코드 기준으로 시간대별 TPS 트렌드를 확인합니다.

    Args:
        query_date:  조회 날짜 (YYYYMMDD, 기본=오늘)
        time:        조회 기준 시각 (HHMM, 예: '2258')
        interval:    조회 구간 (분, 음수=과거 방향, 기본=-120)
        op_cd:       업무 코드 필터 (예: '1011')
        chnl_id:     채널 ID 필터 (예: 'EST')
        page_no:     페이지 번호 (기본=1)
        page_count:  페이지 카운트 (기본=1)
        size:        페이지당 건수 (기본=20)

    Returns:
        query_date (str): 조회 날짜
        interval (int): 조회 구간(분)
        item_count (int): 반환된 항목 수
        tps_detail (list): TPS 상세 목록
            - date (str): 날짜
            - time (str): 측정 시각 (HHMM)
            - server (str): 서버명 (예: MCGP1)
            - opCd (str): 업무 코드
            - chnlNm (str): 채널 이름
            - tps (float): 초당 트랜잭션 수
            - status (str): 상태 (OK / MID / 기타)
    """
    session = await get_session()
    target_date = query_date or _today()

    params: dict = {
        "date":      target_date,
        "interval":  interval,
        "pageNo":    page_no,
        "pageCount": page_count,
        "size":      size,
    }
    if time:    params["time"]   = time
    if op_cd:   params["opCd"]   = op_cd
    if chnl_id: params["chnlId"] = chnl_id

    resp = await session.get("/api/monitoring/mcg/outTpsStatus", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "MCG 아웃바운드 TPS 조회 실패")}

    items: list = body.get("rstData", {}).get("mcgOutTpsDetail", [])

    return {
        "query_date": target_date,
        "interval":   interval,
        "item_count": len(items),
        "tps_detail": [
            {
                "date":   i.get("date"),
                "time":   i.get("time"),
                "server": i.get("server"),
                "opCd":   i.get("opCd"),
                "chnlNm": i.get("chnlNm"),
                "tps":    i.get("tps"),
                "status": i.get("status"),
            }
            for i in items
        ],
    }


# ─────────────────────────────────────────────────────────────
# 10. MCG 인바운드 채널 상태 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_mcg_chnl_status_in(
    page_no: int = 1,
    size: int = 9999,
) -> dict:
    """
    MCG 인바운드 채널의 현재 상태(카운트 합계 및 OK/MID/이상)를 조회합니다.
    모든 채널을 한 번에 조회하는 것이 일반적입니다 (size=9999 기본값).

    Args:
        page_no: 페이지 번호 (기본=1)
        size:    페이지당 건수 (기본=9999, 전체 조회)

    Returns:
        total_count (int): 전체 채널 수
        abnormal_count (int): 비정상(status != OK) 채널 수
        page_set (dict): 페이지네이션 정보 (size, pageNo, totalRowCount, pageCount, offset)
        channel_list (list): 인바운드 채널 상태 목록
            - server (str): 서버명 (예: MCGP1, MCGP2)
            - user (str): 채널 사용자 ID
            - cntSum (float): 카운트 합계
            - status (str): 상태 (OK=정상 / MID=중간 / 그 외=이상)
    """
    session = await get_session()

    params = {"pageNo": page_no, "pageCount": 0, "size": size}

    resp = await session.get("/api/monitoring/mcg/chnlStatusIn", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "MCG 인바운드 채널 상태 조회 실패")}

    rst_data = body.get("rstData", {})
    items: list = rst_data.get("mcgInChnlStatus", [])
    abnormal = [c for c in items if c.get("status") not in ("OK", "MID")]

    return {
        "total_count":    len(items),
        "abnormal_count": len(abnormal),
        "page_set": rst_data.get("pageSet"),
        "channel_list": [
            {
                "server": c.get("server"),
                "user":   c.get("user"),
                "cntSum": c.get("cntSum"),
                "status": c.get("status"),
            }
            for c in items
        ],
    }


# ─────────────────────────────────────────────────────────────
# 11. MCG 아웃바운드 채널 상태 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_mcg_chnl_status_out(
    page_no: int = 1,
    size: int = 9999,
    outbound_yn: str = "Y",
    all_server_yn: str = "Y",
    use_yn: str = "Y",
) -> dict:
    """
    MCG 아웃바운드 채널의 현재 TPS 및 상태를 조회합니다.
    채널 유형(OUTBOUND / Ch to Ch), 담당자, TPS, 상태를 반환합니다.

    Args:
        page_no:       페이지 번호 (기본=1)
        size:          페이지당 건수 (기본=9999, 전체 조회)
        outbound_yn:   아웃바운드 채널만 조회 Y/N (기본=Y)
        all_server_yn: 모든 서버 포함 Y/N (기본=Y)
        use_yn:        사용 중인 채널만 조회 Y/N (기본=Y)

    Returns:
        total_count (int): 전체 채널 수
        abnormal_count (int): 비정상(status != OK) 채널 수
        channel_list (list): 아웃바운드 채널 상태 목록
            - date (str): 날짜
            - time (str): 기준 시각 (HHMM)
            - server (str): 서버명 (예: MCGP1, MCGP2)
            - chnlId (str): 채널 ID
            - chnlNm (str): 채널 이름
            - chnlTyp (str): 채널 유형 (OUTBOUND / Ch to Ch)
            - opCd (str): 업무 코드
            - tps (float): 초당 트랜잭션 수
            - chrgrNm (str): 담당자 이름
            - status (str): 상태 (OK=정상 / MID=중간 / 그 외=이상)
    """
    session = await get_session()

    params = {
        "pageNo":      page_no,
        "pageCount":   0,
        "size":        size,
        "outboundYn":  outbound_yn,
        "allServerYn": all_server_yn,
        "useYn":       use_yn,
    }

    resp = await session.get("/api/monitoring/mcg/chnlStatusOut", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "MCG 아웃바운드 채널 상태 조회 실패")}

    items: list = body.get("rstData", {}).get("mcgOutTpsStatus", [])
    abnormal = [c for c in items if c.get("status") not in ("OK", "MID")]

    return {
        "total_count":    len(items),
        "abnormal_count": len(abnormal),
        "channel_list": [
            {
                "date":    c.get("date"),
                "time":    c.get("time"),
                "server":  c.get("server"),
                "chnlId":  c.get("chnlId"),
                "chnlNm":  c.get("chnlNm"),
                "chnlTyp": c.get("chnlTyp"),
                "opCd":    c.get("opCd"),
                "tps":     c.get("tps"),
                "chrgrNm": c.get("chrgrNm"),
                "status":  c.get("status"),
            }
            for c in items
        ],
    }
