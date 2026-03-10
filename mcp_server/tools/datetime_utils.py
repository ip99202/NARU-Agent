"""
Tool: 날짜 범위 계산 유틸리티

get_date_range: 연도/월/요일/주차/상대표현 등을 입력받아 정확한 날짜 목록을 반환합니다.
  - LLM이 직접 요일·날짜 계산을 하지 않도록, 반드시 이 Tool을 먼저 호출하여 날짜를 확보하세요.
"""
import calendar
from datetime import date, timedelta
from typing import Optional
from mcp_server.app import mcp


# 요일 문자열 → weekday() 인덱스 (Monday=0, Sunday=6)
_WEEKDAY_MAP = {
    "mon": 0, "monday":    0, "월": 0,
    "tue": 1, "tuesday":   1, "화": 1,
    "wed": 2, "wednesday": 2, "수": 2,
    "thu": 3, "thursday":  3, "목": 3,
    "fri": 4, "friday":    4, "금": 4,
    "sat": 5, "saturday":  5, "토": 5,
    "sun": 6, "sunday":    6, "일": 6,
}


def _today() -> date:
    return date.today()


def _dates_in_month(year: int, month: int) -> list[date]:
    """해당 월의 모든 날짜 반환"""
    _, last_day = calendar.monthrange(year, month)
    return [date(year, month, d) for d in range(1, last_day + 1)]


def _weekday_dates_in_month(year: int, month: int, weekday_idx: int) -> list[date]:
    """해당 월에서 특정 요일에 해당하는 모든 날짜 반환"""
    return [d for d in _dates_in_month(year, month) if d.weekday() == weekday_idx]


def _week_of_month(d: date) -> int:
    """해당 날짜가 그 달의 몇 번째 주인지 반환 (1-indexed, 월요일 기준 주 시작)"""
    first_day = date(d.year, d.month, 1)
    # 첫 주의 월요일부터 카운트
    adjusted = d.day + first_day.weekday()  # 첫 날이 무슨 요일인지에 따라 오프셋
    return (adjusted - 1) // 7 + 1


@mcp.tool()
def get_date_range(
    year: Optional[int] = None,
    month: Optional[int] = None,
    weekday: Optional[str] = None,
    week_of_month: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    relative: Optional[str] = None,
) -> dict:
    """
    날짜·요일·주차 계산 전용 툴입니다.
    
    LLM이 직접 달력 계산(요일, 주차, 상대 날짜 등)을 하면 오류가 발생할 수 있습니다.
    "몇 월 매주 월요일", "이번 달 첫 번째 금요일", "지난 주", "지난 달" 같은
    날짜 표현이 포함된 질문에서는 반드시 이 툴을 먼저 호출하여 정확한 날짜를 확보하세요.

    Args:
        year:         연도 (예: 2026). 기본=올해.
        month:        월 (1~12). 지정 시 해당 월 내에서 필터링.
        weekday:      요일 필터. 영문(mon/tue/wed/thu/fri/sat/sun) 또는 한글(월/화/수/목/금/토/일).
                      지정 시 해당 요일에 해당하는 날짜만 반환합니다.
        week_of_month: 월 기준 N번째 주 필터 (1~5).
                      weekday와 함께 사용하면 "N번째 주 ~요일"을 정확히 계산합니다.
                      예) week_of_month=1, weekday="fri" → 해당 월 첫 번째 금요일
        date_from:    조회 시작일 (YYYYMMDD). relative보다 우선하여 사용됩니다.
        date_to:      조회 종료일 (YYYYMMDD). date_from과 함께 사용합니다.
        relative:     상대 날짜 표현. 지원 값:
                      - "today"       → 오늘
                      - "yesterday"   → 어제
                      - "this_week"   → 이번 주 (월~일)
                      - "last_week"   → 지난 주 (월~일)
                      - "this_month"  → 이번 달 전체
                      - "last_month"  → 지난 달 전체
                      - "last_7days"  → 오늘 포함 최근 7일
                      - "last_30days" → 오늘 포함 최근 30일

    Returns:
        today (str):        오늘 날짜 (YYYYMMDD) — 참고용
        dates (list[str]):  계산된 날짜 목록 (YYYYMMDD 형식, 오름차순)
        date_from (str):    반환 날짜 중 가장 이른 날 (YYYYMMDD)
        date_to (str):      반환 날짜 중 가장 늦은 날 (YYYYMMDD)
        count (int):        반환된 날짜 수
        description (str):  계산 결과 요약 (한국어)

    사용 예시:
        # 2026년 2월 매주 월요일
        get_date_range(year=2026, month=2, weekday="mon")
        → {"dates": ["20260202", "20260209", "20260216", "20260223"], ...}

        # 이번 달 첫 번째 금요일
        get_date_range(month=<이번 달>, weekday="fri", week_of_month=1)

        # 지난 주 전체
        get_date_range(relative="last_week")

        # 3월 3주차 모든 날짜
        get_date_range(year=2026, month=3, week_of_month=3)
    """
    today = _today()
    target_year  = year  if year  is not None else today.year
    target_month = month if month is not None else None

    # ── 1. relative 처리 ──────────────────────────────────────
    if relative and not date_from:
        r = relative.lower().strip()
        if r == "today":
            result_dates = [today]
        elif r == "yesterday":
            result_dates = [today - timedelta(days=1)]
        elif r == "this_week":
            monday = today - timedelta(days=today.weekday())
            result_dates = [monday + timedelta(days=i) for i in range(7)]
        elif r == "last_week":
            monday = today - timedelta(days=today.weekday() + 7)
            result_dates = [monday + timedelta(days=i) for i in range(7)]
        elif r == "this_month":
            result_dates = _dates_in_month(today.year, today.month)
        elif r == "last_month":
            first_of_this = today.replace(day=1)
            last_month_last = first_of_this - timedelta(days=1)
            result_dates = _dates_in_month(last_month_last.year, last_month_last.month)
        elif r == "last_7days":
            result_dates = [today - timedelta(days=i) for i in range(6, -1, -1)]
        elif r == "last_30days":
            result_dates = [today - timedelta(days=i) for i in range(29, -1, -1)]
        else:
            return {"error": f"지원하지 않는 relative 값: '{relative}'. "
                             "지원 값: today, yesterday, this_week, last_week, "
                             "this_month, last_month, last_7days, last_30days"}

    # ── 2. date_from / date_to 직접 지정 ─────────────────────
    elif date_from:
        try:
            df = date(int(date_from[:4]), int(date_from[4:6]), int(date_from[6:8]))
            dt = date(int(date_to[:4]),   int(date_to[4:6]),   int(date_to[6:8])) \
                 if date_to else df
        except (ValueError, IndexError):
            return {"error": f"날짜 형식 오류. YYYYMMDD 형식을 사용하세요. 입력: date_from={date_from}, date_to={date_to}"}
        result_dates = []
        cur = df
        while cur <= dt:
            result_dates.append(cur)
            cur += timedelta(days=1)

    # ── 3. year + month + weekday + week_of_month 조합 ────────
    else:
        if target_month is None:
            target_month = today.month  # month 미지정 시 이번 달

        pool = _dates_in_month(target_year, target_month)

        # weekday 필터
        if weekday:
            wd_key = weekday.lower().strip()
            if wd_key not in _WEEKDAY_MAP:
                return {"error": f"지원하지 않는 요일 값: '{weekday}'. "
                                 "영문(mon/tue/wed/thu/fri/sat/sun) 또는 한글(월/화/수/목/금/토/일)을 사용하세요."}
            wd_idx = _WEEKDAY_MAP[wd_key]
            pool = [d for d in pool if d.weekday() == wd_idx]

        # week_of_month 필터
        if week_of_month is not None:
            pool = [d for d in pool if _week_of_month(d) == week_of_month]

        result_dates = pool

    # ── 결과 포맷 ─────────────────────────────────────────────
    result_dates = sorted(set(result_dates))
    date_strs = [d.strftime("%Y%m%d") for d in result_dates]

    # 설명 문자열 생성
    weekday_names = {0:"월",1:"화",2:"수",3:"목",4:"금",5:"토",6:"일"}
    if date_strs:
        desc_parts = []
        if relative:
            desc_parts.append(f"relative='{relative}'")
        if date_from:
            desc_parts.append(f"{date_from}~{date_to or date_from}")
        if year or month:
            ym = f"{target_year}년"
            if month:
                ym += f" {target_month}월"
            desc_parts.append(ym)
        if weekday:
            desc_parts.append(f"매주 {weekday_names.get(_WEEKDAY_MAP.get(weekday.lower().strip(), -1), weekday)}요일")
        if week_of_month:
            desc_parts.append(f"{week_of_month}번째 주")
        description = ", ".join(desc_parts) + f" → {len(date_strs)}개 날짜"
        # 요일 정보 포함
        date_with_weekday = [f"{d.strftime('%Y%m%d')}({weekday_names[d.weekday()]})" for d in result_dates]
        description += f": {', '.join(date_with_weekday)}"
    else:
        description = "조건에 맞는 날짜가 없습니다."

    return {
        "today":       today.strftime("%Y%m%d"),
        "dates":       date_strs,
        "date_from":   date_strs[0]  if date_strs else None,
        "date_to":     date_strs[-1] if date_strs else None,
        "count":       len(date_strs),
        "description": description,
    }
