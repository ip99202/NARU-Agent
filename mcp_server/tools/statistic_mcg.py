"""
Tools: MCG 채널·거래 조회 + MCG 통계 3종

1. get_mcg_channel_list        → GET /api/mcg/chnl          (채널 목록 조회)
2. get_mcg_deal_list           → GET /api/mcg/deal           (거래코드 목록 조회)
3. get_statistic_hourly_mcg    → GET /api/statistic/hourly/mcg  (시간별, statDate=YYYYMMDD)
4. get_statistic_daily_mcg     → GET /api/statistic/daily/mcg   (일별,   statDate=YYYYMM)
5. get_statistic_monthly_mcg   → GET /api/statistic/monthly/mcg (월별,   statDate=YYYY)
"""
from datetime import date
from typing import Optional
from mcp_server.app import mcp
from mcp_server.tools.auth import get_session


def _today() -> str:
    return date.today().strftime("%Y%m%d")

def _this_month() -> str:
    return date.today().strftime("%Y%m")

def _this_year() -> str:
    return date.today().strftime("%Y")


# ─────────────────────────────────────────────────────────────
# 1. MCG 채널 목록 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_mcg_channel_list(
    chnl_nm: Optional[str] = None,
    chnl_id: Optional[str] = None,
    chnl_typ: Optional[str] = None,
    inst_cd: Optional[str] = None,
    use_yn: str = "Y",
    page_no: int = 1,
    size: int = 10,
) -> dict:
    """
    MCG(Multi-Channel Gateway) 채널 목록을 조회합니다.
    채널명, 채널 ID, 유형(INBOUND/OUTBOUND) 등으로 검색할 수 있습니다.

    Args:
        chnl_nm:  채널 이름 검색 키워드 (예: 멤버십)
        chnl_id:  채널 ID 필터 (예: TMS)
        chnl_typ: 채널 유형 필터 (INBOUND/OUTBOUND/Ch to Ch)
        inst_cd:  기관 코드 필터
        use_yn:   사용 여부 Y/N (기본=Y, 사용 중인 채널만)
        page_no:  페이지 번호 (기본=1)
        size:     페이지당 건수 (기본=10)

    Returns:
        total_row_count (int): 검색된 총 채널 수
        channel_list (list): 채널 목록
            - chnlId (str): 채널 고유 ID
            - chnlNm (str): 채널 이름
            - chnlTyp (str): 채널 유형 (INBOUND / OUTBOUND / Ch to Ch)
            - chnlGrp (str): 채널 그룹 (예: SS(SWING))
            - lnkMthd (str): 연동 방식 (예: TP)
            - dvlpLang (str): 개발 언어 (예: JAVA)
            - opCd (str): 운영 코드
            - mcgInstCd (str): MCG 기관 코드
            - mcgInstNm (str): MCG 기관 이름
            - useYn (str): 사용 여부
            - mapperCnt (int): 매퍼 수
            - chnlRmk (str): 비고 (담당자 정보 등)
            - tcpGwNm (str): TCP 게이트웨이 이름 (없으면 빈 문자열)
            - creDt (int): 생성 시간 (Unix Timestamp ms)
            - chgDt (int): 변경 시간 (Unix Timestamp ms)
        page_set (dict): 페이지네이션 정보
    """
    session = await get_session()
    params = {
        "pageNo":    page_no,
        "pageCount": 0,
        "size":      size,
        "useYn":     use_yn,
        "opCd":      "",
        "instCd":    inst_cd or "",
        "mcgInstCd": "",
        "chnlTyp":   chnl_typ or "",
        "chnlGrp":   "",
        "lnkMthd":   "",
        "chnlId":    chnl_id or "",
        "chnlNm":    chnl_nm or "",
        "containerNum": "",
        "tcpgwNm":   "",
        "dvlpLang":  "",
        "chnlRmk":   "",
    }
    resp = await session.get("/api/mcg/chnl", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "MCG 채널 목록 조회 실패")}

    rst = body.get("rstData", {})
    items: list = rst.get("searchList", [])

    return {
        "total_row_count": rst.get("pageSet", {}).get("totalRowCount", len(items)),
        "channel_list": [
            {
                "chnlId":     i.get("chnlId"),
                "chnlNm":     i.get("chnlNm"),
                "chnlTyp":    i.get("chnlTyp"),
                "chnlGrp":    i.get("chnlGrp"),
                "lnkMthd":    i.get("lnkMthd"),
                "dvlpLang":   i.get("dvlpLang"),
                "opCd":       i.get("opCd"),
                "mcgInstCd":  i.get("mcgInstCd"),
                "mcgInstNm":  i.get("mcgInstNm"),
                "useYn":      i.get("useYn"),
                "mapperCnt":  i.get("mapperCnt"),
                "chnlRmk":    i.get("chnlRmk"),
                "tcpGwNm":    i.get("tcpGwNm"),
                "creDt":      i.get("creDt"),
                "chgDt":      i.get("chgDt"),
            }
            for i in items
        ],
        "page_set": rst.get("pageSet", {}),
    }


# ─────────────────────────────────────────────────────────────
# 2. MCG 거래코드 목록 조회
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_mcg_deal_list(
    deal_nm: Optional[str] = None,
    deal_cd: Optional[str] = None,
    op_cd: Optional[str] = None,
    use_yn: str = "Y",
    page_no: int = 1,
    size: int = 10,
) -> dict:
    """
    MCG 거래코드 목록을 조회합니다.
    통계 조회에 필요한 inputKeyword(거래코드)를 확인할 때 사용합니다.

    Args:
        deal_nm:  거래 이름 검색 키워드 (예: 멤버십정보변경)
        deal_cd:  거래 코드 필터 (예: ZMBRSM0100010_TR05)
        op_cd:    운영 코드 필터
        use_yn:   사용 여부 Y/N (기본=Y)
        page_no:  페이지 번호 (기본=1)
        size:     페이지당 건수 (기본=10)

    Returns:
        total_row_count (int): 검색된 총 거래코드 수
        deal_list (list): 거래코드 목록
            - dealCd (str): 거래 코드
            - dealNm (str): 거래 이름
            - chnlId (str): 채널 ID
            - chnlTyp (str): 채널 유형
            - opCd (str): 운영 코드
            - mcgInstCd (str): MCG 기관 코드
            - mcgInstNm (str): MCG 기관 이름
            - useYn (str): 사용 여부
            - dealTimeout (str): 거래 타임아웃(초)
            - prd1SvrIp (str): 운영 서버 IP
            - prd1SvrPort (str): 운영 서버 포트
            - reqChrgrNm (str): 요청 담당자 이름
            - reqChrgrOrgNm (str): 요청 담당자 소속 조직
            - rpsChrgrNm (str): 응답 담당자 이름
            - rpsChrgrOrgNm (str): 응답 담당자 소속 조직
            - creDt (int): 생성 시간 (Unix Timestamp ms)
            - chgDt (int): 변경 시간 (Unix Timestamp ms)
        page_set (dict): 페이지네이션 정보
    """
    session = await get_session()
    params = {
        "pageNo":    page_no,
        "pageCount": 0,
        "size":      size,
        "useYn":     use_yn,
        "opCd":      op_cd or "",
        "dealCd":    deal_cd or "",
        "dealNm":    deal_nm or "",
    }
    resp = await session.get("/api/mcg/deal", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "MCG 거래코드 목록 조회 실패")}

    rst = body.get("rstData", {})
    items: list = rst.get("searchList", [])

    return {
        "total_row_count": rst.get("pageSet", {}).get("totalRowCount", len(items)),
        "deal_list": [
            {
                "dealCd":        i.get("dealCd"),
                "dealNm":        i.get("dealNm"),
                "chnlId":        i.get("chnlId"),
                "chnlTyp":       i.get("chnlTyp"),
                "opCd":          i.get("opCd"),
                "mcgInstCd":     i.get("mcgInstCd"),
                "mcgInstNm":     i.get("mcgInstNm"),
                "useYn":         i.get("useYn"),
                "dealTimeout":   i.get("dealTimeout"),
                "prd1SvrIp":     i.get("prd1SvrIp"),
                "prd1SvrPort":   i.get("prd1SvrPort"),
                "reqChrgrNm":    i.get("reqChrgrNm"),
                "reqChrgrOrgNm": i.get("reqChrgrOrgNm"),
                "rpsChrgrNm":    i.get("rpsChrgrNm"),
                "rpsChrgrOrgNm": i.get("rpsChrgrOrgNm"),
                "creDt":         i.get("creDt"),
                "chgDt":         i.get("chgDt"),
            }
            for i in items
        ],
        "page_set": rst.get("pageSet", {}),
    }


# ─────────────────────────────────────────────────────────────
# 3. MCG 시간별 통계
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_statistic_hourly_mcg(
    stat_date: Optional[str] = None,
    input_keyword: Optional[str] = None,
    input_op_cd: Optional[str] = None,
    page_no: int = 1,
    size: int = 10,
) -> dict:
    """
    특정 날짜의 MCG 거래코드별 시간대(0~23시)별 트랜잭션 통계를 조회합니다.
    inputKeyword에 거래코드(dealCd)를 입력하여 특정 거래의 시간대별 트래픽을 분석합니다.

    Args:
        stat_date:     조회 날짜 (YYYYMMDD, 기본=오늘)
        input_keyword: 거래 코드 필터 (예: ZMBRSM0100010_TR05)
        input_op_cd:   운영 코드 필터
        page_no:       페이지 번호
        size:          페이지당 건수

    Returns:
        stat_date (str): 조회 날짜 (YYYYMMDD)
        total_row_count (int): 전체 거래 수
        hourly_list (list): 거래별 시간대별 통계 목록
            - tx (str): 거래 코드 (dealCd)
            - dealNm (str): 거래 이름
            - opCd (str): 운영 코드
            - opNm (str): 운영 이름
            - totCnt (int): 해당 날짜 총 트랜잭션 수
            - statDate (str): 통계 날짜
            - hourly (dict): t0~t23 시간대별 트랜잭션 수
        hourly_total (list): 위 목록의 시간대별 합계 (동일 구조)
        page_set (dict): 페이지네이션 정보
    """
    session = await get_session()
    params = {
        "pageNo":     page_no,
        "size":       size,
        "statDate":   stat_date or _today(),
        "inputKeyword": input_keyword or "",
        "inputOpCd":  input_op_cd or "",
    }
    resp = await session.get("/api/statistic/hourly/mcg", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "MCG 시간별 통계 조회 실패")}

    rst = body.get("rstData", {})
    items: list = rst.get("hourlyTrmsList", [])
    total: list = rst.get("hourlyTotTrmsList", [])

    def _parse(item: dict) -> dict:
        return {
            "tx":       item.get("tx"),
            "dealNm":   item.get("dealNm"),
            "opCd":     item.get("opCd"),
            "opNm":     item.get("opNm"),
            "totCnt":   item.get("totCnt"),
            "statDate": item.get("statDate"),
            "hourly":   {f"t{h}": item.get(f"t{h}", 0) for h in range(24)},
        }

    return {
        "stat_date":       params["statDate"],
        "total_row_count": rst.get("pageSet", {}).get("totalRowCount", len(items)),
        "hourly_list":     [_parse(i) for i in items],
        "hourly_total":    [_parse(i) for i in total],
        "page_set":        rst.get("pageSet", {}),
    }


# ─────────────────────────────────────────────────────────────
# 4. MCG 일별 통계
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_statistic_daily_mcg(
    stat_date: Optional[str] = None,
    input_keyword: Optional[str] = None,
    input_op_cd: Optional[str] = None,
    page_no: int = 1,
    size: int = 10,
) -> dict:
    """
    특정 월의 MCG 거래코드별 일자(1~31일)별 트랜잭션 통계를 조회합니다.
    월 단위 거래별 트래픽 추이를 분석합니다.

    Args:
        stat_date:     조회 연월 (YYYYMM, 기본=이번 달)
        input_keyword: 거래 코드 필터 (예: ZMBRSM0100010_TR05)
        input_op_cd:   운영 코드 필터
        page_no:       페이지 번호
        size:          페이지당 건수

    Returns:
        stat_date (str): 조회 연월 (YYYYMM)
        total_row_count (int): 전체 거래 수
        daily_list (list): 거래별 일별 통계 목록
            - tx (str): 거래 코드 (dealCd)
            - dealNm (str): 거래 이름
            - opCd (str): 운영 코드
            - opNm (str): 운영 이름
            - totCnt (int): 해당 월 총 트랜잭션 수
            - statDate (str): 통계 연월
            - daily (dict): d1~d31 일자별 트랜잭션 수
        daily_total (list): 위 목록의 일자별 합계 (동일 구조)
        page_set (dict): 페이지네이션 정보
    """
    session = await get_session()
    params = {
        "pageNo":       page_no,
        "size":         size,
        "statDate":     stat_date or _this_month(),
        "inputKeyword": input_keyword or "",
        "inputOpCd":    input_op_cd or "",
    }
    resp = await session.get("/api/statistic/daily/mcg", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "MCG 일별 통계 조회 실패")}

    rst = body.get("rstData", {})
    items: list = rst.get("dailyTrmsList", [])
    total: list = rst.get("dailyTotTrmsList", [])

    def _parse(item: dict) -> dict:
        return {
            "tx":       item.get("tx"),
            "dealNm":   item.get("dealNm"),
            "opCd":     item.get("opCd"),
            "opNm":     item.get("opNm"),
            "totCnt":   item.get("totCnt"),
            "statDate": item.get("statDate"),
            "daily":    {f"d{d}": item.get(f"d{d}", 0) for d in range(1, 32)},
        }

    return {
        "stat_date":       params["statDate"],
        "total_row_count": rst.get("pageSet", {}).get("totalRowCount", len(items)),
        "daily_list":      [_parse(i) for i in items],
        "daily_total":     [_parse(i) for i in total],
        "page_set":        rst.get("pageSet", {}),
    }


# ─────────────────────────────────────────────────────────────
# 5. MCG 월별 통계
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_statistic_monthly_mcg(
    stat_date: Optional[str] = None,
    input_keyword: Optional[str] = None,
    input_op_cd: Optional[str] = None,
    page_no: int = 1,
    size: int = 10,
) -> dict:
    """
    특정 연도의 MCG 거래코드별 월(1~12월)별 트랜잭션 통계를 조회합니다.
    연간 거래별 트래픽 추이 및 계절성 분석에 사용합니다.

    Args:
        stat_date:     조회 연도 (YYYY, 기본=올해)
        input_keyword: 거래 코드 필터 (예: ZMBRSM0100010_TR05)
        input_op_cd:   운영 코드 필터
        page_no:       페이지 번호
        size:          페이지당 건수

    Returns:
        stat_date (str): 조회 연도 (YYYY)
        total_row_count (int): 전체 거래 수
        monthly_list (list): 거래별 월별 통계 목록
            - tx (str): 거래 코드 (dealCd)
            - dealNm (str): 거래 이름
            - opCd (str): 운영 코드
            - opNm (str): 운영 이름
            - totCnt (int): 해당 연도 총 트랜잭션 수
            - statDate (str): 통계 연도
            - monthly (dict): m1~m12 월별 트랜잭션 수
        monthly_total (list): 위 목록의 월별 합계 (동일 구조)
        page_set (dict): 페이지네이션 정보
    """
    session = await get_session()
    params = {
        "pageNo":       page_no,
        "size":         size,
        "statDate":     stat_date or _this_year(),
        "inputKeyword": input_keyword or "",
        "inputOpCd":    input_op_cd or "",
    }
    resp = await session.get("/api/statistic/monthly/mcg", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "MCG 월별 통계 조회 실패")}

    rst = body.get("rstData", {})
    items: list = rst.get("monthlyTrmsList", [])
    total: list = rst.get("monthlyTotTrmsList", [])

    def _parse(item: dict) -> dict:
        return {
            "tx":       item.get("tx"),
            "dealNm":   item.get("dealNm"),
            "opCd":     item.get("opCd"),
            "opNm":     item.get("opNm"),
            "totCnt":   item.get("totCnt"),
            "statDate": item.get("statDate"),
            "monthly":  {f"m{m}": item.get(f"m{m}", 0) for m in range(1, 13)},
        }

    return {
        "stat_date":       params["statDate"],
        "total_row_count": rst.get("pageSet", {}).get("totalRowCount", len(items)),
        "monthly_list":    [_parse(i) for i in items],
        "monthly_total":   [_parse(i) for i in total],
        "page_set":        rst.get("pageSet", {}),
    }
