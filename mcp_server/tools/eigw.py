"""
Tool: get_eigw_error_stats / get_eigw_monthly_summary

브라우저 분석으로 확인한 실제 API:
  GET /api/statistic/hourly/eigw?statDate=YYYYMMDD&srchType=  → 시간대별 EIGW 통계
  GET /api/statistic/monthly/summary?statDate=YYYYMM          → 월간 요약
  GET /api/statistic/monthly/eigwError?statDate=YYYYMM        → 월간 오류 통계
"""
from datetime import date, datetime
from typing import Optional
from mcp_server.server import mcp
from mcp_server.tools.auth import get_session


def _today() -> str:
    return date.today().strftime("%Y%m%d")

def _this_month() -> str:
    return date.today().strftime("%Y%m")


@mcp.tool()
async def get_eigw_error_stats(
    stat_date: Optional[str] = None,
    inst_cd: Optional[str] = None,
) -> dict:
    """
    EIGW 온라인 시간대별 오류 통계를 조회합니다.
    평균 대비 급증 여부를 분석하여 반환합니다.

    Args:
        stat_date: 조회 날짜 (YYYYMMDD, 기본=오늘)
        inst_cd:   기관코드 필터 (없으면 전체)
    """
    session = await get_session()
    target_date = stat_date or _today()

    params = {"statDate": target_date, "srchType": ""}
    if inst_cd:
        params["instCd"] = inst_cd

    resp = await session.get("/api/statistic/hourly/eigw", params=params)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EIGW 통계 조회 실패")}

    rst_data = body.get("rstData", {})
    # 실제 응답 키: hourlyTrmsList (기관별), hourlyTotTrmsList (합계)
    hourly = rst_data.get("hourlyTrmsList") or rst_data.get("hourlyList") or []
    hourly_total = rst_data.get("hourlyTotTrmsList") or []

    # 오류 건수 집계
    total_errors = sum(int(item.get("errCnt", 0) or 0) for item in hourly)
    total_calls  = sum(int(item.get("totCnt", 0) or 0) for item in hourly)

    return {
        "stat_date": target_date,
        "inst_cd": inst_cd,
        "total_calls": total_calls,
        "total_errors": total_errors,
        "error_rate": round(total_errors / total_calls * 100, 2) if total_calls else 0,
        "hourly_detail": [
            {
                "hour": item.get("statHour"),
                "calls": item.get("totCnt"),
                "errors": item.get("errCnt"),
            }
            for item in hourly
        ],
        "hourly_total": hourly_total,
    }


@mcp.tool()
async def get_eigw_monthly_summary(stat_month: Optional[str] = None) -> dict:
    """
    EIGW 월간 요약 통계를 조회합니다. '평소' 트렌드 파악에 사용합니다.

    Args:
        stat_month: 조회 월 (YYYYMM, 기본=이번 달)
    """
    session = await get_session()
    target_month = stat_month or _this_month()

    resp = await session.get(
        "/api/statistic/monthly/summary",
        params={"statDate": target_month},
    )
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "월간 요약 조회 실패")}

    return {
        "stat_month": target_month,
        "data": body.get("rstData", {}),
    }


@mcp.tool()
async def get_eigw_monthly_errors(
    stat_month: Optional[str] = None,
    page: int = 1,
    size: int = 10,
) -> dict:
    """
    EIGW 월간 오류 통계 목록을 조회합니다.

    Args:
        stat_month: 조회 월 (YYYYMM, 기본=이번 달)
        page:       페이지 번호
        size:       페이지당 건수
    """
    session = await get_session()
    target_month = stat_month or _this_month()

    resp = await session.get(
        "/api/statistic/monthly/eigwError",
        params={"statDate": target_month, "pageNo": page, "size": size, "pageCount": 0},
    )
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "월간 오류 통계 조회 실패")}

    rst_data = body.get("rstData", {})
    # 실제 응답 키: eigwMonthlyTrmsList
    items = rst_data.get("eigwMonthlyTrmsList") or rst_data.get("errorList") or []

    return {
        "stat_month": target_month,
        "total": rst_data.get("pageSet", {}).get("totalRowCount", 0),
        "items": items,
    }
