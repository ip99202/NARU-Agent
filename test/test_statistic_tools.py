"""
통계 MCP Tools API 검증 스크립트

EAI·EIGW·MCG 통계 API 11종을 직접 호출하여 응답을 검증합니다.
실행: python3 test/test_statistic_tools.py
"""
import asyncio
import json
import sys
import os

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import httpx
from datetime import date
from config import NARU_BASE_URL, NARU_USER_ID, NARU_USER_PW

from datetime import timedelta
TODAY      = date.today().strftime("%Y%m%d")
YESTERDAY  = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
THIS_MONTH = date.today().strftime("%Y%m")
THIS_YEAR  = date.today().strftime("%Y")

# 테스트용 기준값 (요청서에서 확인된 실제 값)
SAMPLE_IF_KEYWORD  = "EGW.MVNO_KAIT_MYDATA_MAU"
SAMPLE_INST_CD     = "HNCD"
SAMPLE_DEAL_KW     = "멤버십정보변경"
SAMPLE_DEAL_CD     = "ZMBRSM0100010_TR05"
SAMPLE_CHNL_KW     = "멤버십"


async def make_session() -> httpx.AsyncClient:
    client = httpx.AsyncClient(base_url=NARU_BASE_URL, timeout=30.0, follow_redirects=True)
    await client.post("/api/verify-code/pre-login", json={"userId": NARU_USER_ID, "userPw": NARU_USER_PW})
    await client.post("/api/loginProc", data={"userId": NARU_USER_ID, "userPw": NARU_USER_PW})
    print(f"✅ 로그인 성공 | 쿠키: {list(client.cookies.keys())}\n")
    return client


def pretty(data, max_len: int = 500) -> str:
    s = json.dumps(data, ensure_ascii=False, indent=2)
    return s[:max_len] + "\n...(truncated)" if len(s) > max_len else s


def check(body: dict, list_key: str) -> tuple[bool, str]:
    """응답에서 리스트 키를 확인하고 건수를 반환합니다."""
    rst_data = body.get("rstData", {})
    lst = rst_data.get(list_key, [])
    ok = body.get("rstCd") == "S" and isinstance(lst, list)
    return ok, f"{list_key}: {len(lst)}건"


async def run_tests():
    session = await make_session()

    tests = [
        # ── EAI 통계 ──────────────────────────────────────────────
        {
            "name":     "① EAI 시간별 통계 (yesterday, keyword 필터)",
            "url":      "/api/statistic/hourly/eai",
            "params":   {"pageNo": 1, "size": 10, "statDate": YESTERDAY,
                         "inputKeyword": SAMPLE_IF_KEYWORD, "mqMngrNm": "", "ifTypCd": ""},
            "list_key": "hourlyTrmsList",
        },
        {
            "name":     "② EAI 일별 통계 (this_month, keyword 필터)",
            "url":      "/api/statistic/daily/eai",
            "params":   {"pageNo": 1, "size": 10, "statDate": THIS_MONTH,
                         "inputKeyword": SAMPLE_IF_KEYWORD, "mqMngrNm": "", "ifTypCd": ""},
            "list_key": "dailyTrmsList",
        },
        {
            "name":     "③ EAI 월별 통계 (this_year, keyword 필터)",
            "url":      "/api/statistic/monthly/eai",
            "params":   {"pageNo": 1, "size": 10, "statDate": THIS_YEAR,
                         "inputKeyword": SAMPLE_IF_KEYWORD, "mqMngrNm": "", "ifTypCd": ""},
            "list_key": "monthlyTrmsList",
        },
        # ── EIGW 통계 ─────────────────────────────────────────────
        {
            "name":     "④ EIGW 시간별 통계 (yesterday, instCd=HNCD)",
            "url":      "/api/statistic/hourly/eigw",
            "params":   {"size": 10, "statDate": YESTERDAY, "inputKeyword": "",
                         "mqMngrNm": "", "instCd": SAMPLE_INST_CD, "instCdGrpYn": "N"},
            "list_key": "hourlyTrmsList",
        },
        {
            "name":     "⑤ EIGW 일별 통계 (this_month, instCd=HNCD)",
            "url":      "/api/statistic/daily/eigw",
            "params":   {"size": 10, "statDate": THIS_MONTH, "inputKeyword": "",
                         "mqMngrNm": "", "instCd": SAMPLE_INST_CD, "instCdGrpYn": "N"},
            "list_key": "dailyTrmsList",
        },
        {
            "name":     "⑥ EIGW 월별 통계 (this_year, instCd=HNCD)",
            "url":      "/api/statistic/monthly/eigw",
            "params":   {"size": 10, "statDate": THIS_YEAR, "inputKeyword": "",
                         "mqMngrNm": "", "instCd": SAMPLE_INST_CD, "instCdGrpYn": "N"},
            "list_key": "monthlyTrmsList",
        },
        # ── MCG 채널·거래 ──────────────────────────────────────────
        {
            "name":     "⑦ MCG 채널 목록 (chnlNm=멤버십)",
            "url":      "/api/mcg/chnl",
            "params":   {"pageNo": 1, "pageCount": 0, "size": 5,
                         "chnlNm": SAMPLE_CHNL_KW, "useYn": "Y",
                         "opCd": "", "instCd": "", "mcgInstCd": "", "chnlTyp": "",
                         "chnlGrp": "", "lnkMthd": "", "chnlId": "",
                         "containerNum": "", "tcpgwNm": "", "dvlpLang": "", "chnlRmk": ""},
            "list_key": "searchList",
        },
        {
            "name":     "⑧ MCG 거래코드 목록 (dealNm=멤버십정보변경)",
            "url":      "/api/mcg/deal",
            "params":   {"pageNo": 1, "pageCount": 0, "size": 5,
                         "dealNm": SAMPLE_DEAL_KW, "useYn": "Y",
                         "opCd": "", "dealCd": ""},
            "list_key": "searchList",
        },
        # ── MCG 통계 ───────────────────────────────────────────────
        {
            "name":     "⑨ MCG 시간별 통계 (yesterday, keyword=dealCd)",
            "url":      "/api/statistic/hourly/mcg",
            "params":   {"pageNo": 1, "size": 10, "statDate": YESTERDAY,
                         "inputKeyword": SAMPLE_DEAL_CD, "inputOpCd": ""},
            "list_key": "hourlyTrmsList",
        },
        {
            "name":     "⑩ MCG 일별 통계 (this_month, keyword=dealCd)",
            "url":      "/api/statistic/daily/mcg",
            "params":   {"pageNo": 1, "size": 10, "statDate": THIS_MONTH,
                         "inputKeyword": SAMPLE_DEAL_CD, "inputOpCd": ""},
            "list_key": "dailyTrmsList",
        },
        {
            "name":     "⑪ MCG 월별 통계 (this_year, keyword=dealCd)",
            "url":      "/api/statistic/monthly/mcg",
            "params":   {"pageNo": 1, "size": 10, "statDate": THIS_YEAR,
                         "inputKeyword": SAMPLE_DEAL_CD, "inputOpCd": ""},
            "list_key": "monthlyTrmsList",
        },
    ]

    passed = 0
    failed = 0

    for t in tests:
        print("─" * 65)
        print(f"🔍 {t['name']}")
        print(f"   GET {t['url']} | statDate={t['params'].get('statDate', '-')}")
        try:
            resp = await session.get(t["url"], params=t["params"])
            body = resp.json()

            rst_cd  = body.get("rstCd", "?")
            rst_msg = body.get("rstMsg", "")
            symbol  = "✅" if rst_cd == "S" else "❌"
            print(f"   HTTP {resp.status_code} | rstCd: {rst_cd} {symbol} | {rst_msg}")

            ok, detail = check(body, t["list_key"])
            if ok:
                print(f"   ✅ {detail}")
                # 첫 번째 항목 미리보기
                items = body.get("rstData", {}).get(t["list_key"], [])
                if items:
                    import re
                    _TIMESERIES = re.compile(r'^(t\d+|d\d+|m\d+)$')
                    preview = {k: v for k, v in items[0].items()
                               if not _TIMESERIES.match(k)}
                    print(f"   첫 항목(시계열 제외): {pretty(preview, 300)}")
                passed += 1
            else:
                print(f"   ❌ 검증 실패: {detail}")
                print(f"   응답: {pretty(body)}")
                failed += 1

        except Exception as e:
            print(f"   ❌ 예외: {e}")
            failed += 1
        print()

    print("─" * 65)
    print(f"📊 결과: {passed}개 통과 / {failed}개 실패 (총 {passed+failed}개)")
    print("─" * 65)

    await session.aclose()


if __name__ == "__main__":
    asyncio.run(run_tests())
