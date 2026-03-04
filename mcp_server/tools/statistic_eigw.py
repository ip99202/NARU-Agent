"""
Tools: EIGW 통계 3종

1. get_statistic_hourly_eigw   → GET /api/statistic/hourly/eigw   (시간별, statDate=YYYYMMDD)
2. get_statistic_daily_eigw    → GET /api/statistic/daily/eigw    (일별,  statDate=YYYYMM)
3. get_statistic_monthly_eigw  → GET /api/statistic/monthly/eigw  (월별,  statDate=YYYY)

공통 필터: inputKeyword(인터페이스 ID), mqMngrNm, instCd(기관코드), instCdGrpYn(그룹화여부)


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
# 1. EIGW 시간별 통계
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_statistic_hourly_eigw(
    stat_date: Optional[str] = None,
    inst_cd: Optional[str] = None,
    input_keyword: Optional[str] = None,
    mq_mngr_nm: Optional[str] = None,
    inst_cd_grp_yn: str = "N",
    page_no: int = 1,
    size: int = 10,
) -> dict:
    """
    특정 날짜의 EIGW 기관별·인터페이스별 시간대(0~23시)별 트랜잭션 통계를 조회합니다.
    기관(instCd) 또는 인터페이스(inputKeyword)로 필터링하여 시간대별 트래픽을 분석합니다.

    Args:
        stat_date:      조회 날짜 (YYYYMMDD, 기본=오늘)
        inst_cd:        기관 코드 필터 (예: HNCD, 없으면 전체)
        input_keyword:  인터페이스 ID 또는 키워드 필터 (없으면 전체)
        mq_mngr_nm:     큐매니저 이름 필터
        inst_cd_grp_yn: 기관 코드 그룹화 여부 Y/N (기본=N)
        page_no:        페이지 번호 (기본=1)
        size:           페이지당 건수 (기본=10)

    Returns:
        stat_date (str): 조회 날짜 (YYYYMMDD)
        total_row_count (int): 전체 인터페이스 수
        hourly_list (list): 인터페이스별 시간대별 통계 목록
            - ifId (str): 인터페이스 ID
            - ifNm (str): 인터페이스 이름
            - instCd (str): 기관 코드
            - instNm (str): 기관 이름
            - conf (str): 구성 코드
            - totCnt (int): 해당 날짜 총 트랜잭션 수
            - statDate (str): 통계 날짜
            - hourly (dict): t0~t23 시간대별 트랜잭션 수
        hourly_total (list): 위 목록의 시간대별 합계 (동일 구조)
        page_set (dict): 페이지네이션 정보
    """
    session = await get_session()
    params = {
        "pageNo":        page_no,
        "size":          size,
        "statDate":      stat_date or _today(),
        "inputKeyword":  input_keyword or "",
        "mqMngrNm":      mq_mngr_nm or "",
        "instCdGrpYn":   inst_cd_grp_yn,
    }
    if inst_cd:
        params["instCd"] = inst_cd

    resp = await session.get("/api/statistic/hourly/eigw", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EIGW 시간별 통계 조회 실패")}

    rst = body.get("rstData", {})
    items: list = rst.get("hourlyTrmsList", [])
    total: list = rst.get("hourlyTotTrmsList", [])

    def _parse(item: dict) -> dict:
        return {
            "ifId":     item.get("ifId"),
            "ifNm":     item.get("ifNm"),
            "instCd":   item.get("instCd"),
            "instNm":   item.get("instNm"),
            "conf":     item.get("conf"),
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
# 2. EIGW 일별 통계
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_statistic_daily_eigw(
    stat_date: Optional[str] = None,
    inst_cd: Optional[str] = None,
    input_keyword: Optional[str] = None,
    mq_mngr_nm: Optional[str] = None,
    inst_cd_grp_yn: str = "N",
    page_no: int = 1,
    size: int = 10,
) -> dict:
    """
    특정 월의 EIGW 기관별·인터페이스별 일자(1~31일)별 트랜잭션 통계를 조회합니다.
    월 단위 기관별 트래픽 비교 및 이상 일자 탐지에 사용합니다.

    Args:
        stat_date:      조회 연월 (YYYYMM, 기본=이번 달)
        inst_cd:        기관 코드 필터 (예: HNCD)
        input_keyword:  인터페이스 ID 또는 키워드 필터
        mq_mngr_nm:     큐매니저 이름 필터
        inst_cd_grp_yn: 기관 코드 그룹화 여부 Y/N (기본=N)
        page_no:        페이지 번호
        size:           페이지당 건수

    Returns:
        stat_date (str): 조회 연월 (YYYYMM)
        total_row_count (int): 전체 인터페이스 수
        daily_list (list): 인터페이스별 일별 통계 목록
            - ifId (str): 인터페이스 ID
            - ifNm (str): 인터페이스 이름
            - instCd (str): 기관 코드
            - instNm (str): 기관 이름
            - conf (str): 구성 코드
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
        "mqMngrNm":     mq_mngr_nm or "",
        "instCdGrpYn":  inst_cd_grp_yn,
    }
    if inst_cd:
        params["instCd"] = inst_cd

    resp = await session.get("/api/statistic/daily/eigw", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EIGW 일별 통계 조회 실패")}

    rst = body.get("rstData", {})
    items: list = rst.get("dailyTrmsList", [])
    total: list = rst.get("dailyTotTrmsList", [])

    def _parse(item: dict) -> dict:
        return {
            "ifId":     item.get("ifId"),
            "ifNm":     item.get("ifNm"),
            "instCd":   item.get("instCd"),
            "instNm":   item.get("instNm"),
            "conf":     item.get("conf"),
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
# 3. EIGW 월별 통계
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_statistic_monthly_eigw(
    stat_date: Optional[str] = None,
    inst_cd: Optional[str] = None,
    input_keyword: Optional[str] = None,
    mq_mngr_nm: Optional[str] = None,
    inst_cd_grp_yn: str = "N",
    page_no: int = 1,
    size: int = 10,
) -> dict:
    """
    특정 연도의 EIGW 기관별·인터페이스별 월(1~12월)별 트랜잭션 통계를 조회합니다.
    연간 기관별 트래픽 추이 및 계절성 분석에 사용합니다.

    Args:
        stat_date:      조회 연도 (YYYY, 기본=올해)
        inst_cd:        기관 코드 필터 (예: HNCD)
        input_keyword:  인터페이스 ID 또는 키워드 필터
        mq_mngr_nm:     큐매니저 이름 필터
        inst_cd_grp_yn: 기관 코드 그룹화 여부 Y/N (기본=N)
        page_no:        페이지 번호
        size:           페이지당 건수

    Returns:
        stat_date (str): 조회 연도 (YYYY)
        total_row_count (int): 전체 인터페이스 수
        monthly_list (list): 인터페이스별 월별 통계 목록
            - ifId (str): 인터페이스 ID
            - instCd (str): 기관 코드
            - instNm (str): 기관 이름
            - conf (str): 구성 코드
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
        "mqMngrNm":     mq_mngr_nm or "",
        "instCdGrpYn":  inst_cd_grp_yn,
    }
    if inst_cd:
        params["instCd"] = inst_cd

    resp = await session.get("/api/statistic/monthly/eigw", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EIGW 월별 통계 조회 실패")}

    rst = body.get("rstData", {})
    items: list = rst.get("monthlyTrmsList", [])
    total: list = rst.get("monthlyTotTrmsList", [])

    def _parse(item: dict) -> dict:
        return {
            "ifId":     item.get("ifId"),
            "instCd":   item.get("instCd"),
            "instNm":   item.get("instNm"),
            "conf":     item.get("conf"),
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
