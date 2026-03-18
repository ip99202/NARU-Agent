"""
Tools: 모니터링 API (MCG)
 1. get_mcg_chnl_status_all              → GET /api/monitoring/mcg/chnlStatusAll
 2. get_mcg_out_tps_status               → GET /api/monitoring/mcg/outTpsStatus
 3. get_mcg_chnl_status_in               → GET /api/monitoring/mcg/chnlStatusIn
 4. get_mcg_chnl_status_out              → GET /api/monitoring/mcg/chnlStatusOut
"""
from datetime import date
from typing import Optional
from mcp_server.app import mcp
from mcp_server.tools.auth import get_session

def _today() -> str:
    return date.today().strftime("%Y%m%d")

# ─────────────────────────────────────────────────────────────
# 1. MCG 전체 채널 상태 조회
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


# ─────────────────────────────────────────────────────────────
# 2. MCG 아웃바운드 TPS 상태 조회
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
    현재 채널 상태(current_channel_status)도 함께 반환되므로
    이력 분석과 현재 상태 확인을 동시에 할 수 있습니다.

    Args:
        query_date:  조회 날짜 (YYYYMMDD, 기본=오늘)
        time:        조회 기준 시각 (HHMM, 예: '2258')
        interval:    조회 구간 (분, 예: '-120' = 조회기준 시각 -120분 ~ 조회기준 시각, 필수값, 항상 음수값)
        op_cd:       업무 코드 필터 (예: '1011')
        chnl_id:     채널 ID 필터 (예: 'EST')
        page_no:     페이지 번호 (기본=1)
        page_count:  페이지 카운트 (기본=1)
        size:        페이지당 건수 (기본=20)

    Returns:
        query_date (str): 조회 날짜
        interval (int): 조회 구간(분)
        item_count (int): tps_detail 반환 항목 수
        tps_detail (list): 시간대별 TPS 이력 목록
            - date (str): 날짜
            - time (str): 측정 시각 (HHMM)
            - server (str): 서버명 (예: MCGP1)
            - opCd (str): 업무 코드
            - chnlNm (str): 채널 이름
            - tps (float): 초당 트랜잭션 수
            - status (str): 상태 (OK=정상 / MID=중간 / 기타=이상)
        current_channel_status (list): 현재 아웃바운드 채널 상태 목록 (페이지 기준)
            - date (str): 날짜
            - time (str): 측정 시각 (HHMM)
            - server (str): 서버명
            - chnlId (str): 채널 ID
            - chnlNm (str): 채널 이름
            - chnlTyp (str): 채널 유형 (OUTBOUND / Ch to Ch)
            - opCd (str): 업무 코드
            - tps (float): 초당 트랜잭션 수
            - chrgrNm (str): 담당자 이름
            - status (str): 상태 (OK=정상 / MID=중간 / 기타=이상)
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
    current: list = body.get("rstData", {}).get("mcgOutTpsStatus", [])

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
        "current_channel_status": [
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
            for c in current
        ],
    }


# ─────────────────────────────────────────────────────────────
# 3. MCG 인바운드 채널 상태 조회
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
# 4. MCG 아웃바운드 채널 상태 조회
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
