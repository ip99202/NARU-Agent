"""
MCP Tools API 검증 스크립트

각 Tool이 호출하는 실제 NARU API를 직접 테스트합니다.
실행: python3 test_tools.py
"""
import asyncio
import json
import httpx
from datetime import date
from config import NARU_BASE_URL, NARU_USER_ID, NARU_USER_PW

TODAY = date.today().strftime("%Y%m%d")
THIS_MONTH = date.today().strftime("%Y%m")


async def make_session() -> httpx.AsyncClient:
    client = httpx.AsyncClient(base_url=NARU_BASE_URL, timeout=30.0, follow_redirects=True)
    await client.post("/api/verify-code/pre-login", json={"userId": NARU_USER_ID, "userPw": NARU_USER_PW})
    await client.post("/api/loginProc", data={"userId": NARU_USER_ID, "userPw": NARU_USER_PW})
    print(f"✅ 로그인 성공 | 쿠키: {list(client.cookies.keys())}\n")
    return client


def pretty(data: dict, max_len: int = 600) -> str:
    s = json.dumps(data, ensure_ascii=False, indent=2)
    return s[:max_len] + "\n...(truncated)" if len(s) > max_len else s


async def run_tests():
    session = await make_session()

    tests = [
        {
            "name": "① 기관 그룹 목록 조회 (institution)",
            "method": "GET",
            "url": "/api/bizcomm/cccd/orgcd/list/group",
            "params": {},
        },
        {
            "name": "② 인터페이스 메타 검색 (allmeta, 전체 10건)",
            "method": "GET",
            "url": "/api/bizcomm/allmeta",
            "params": {"pageNo": 1, "pageCount": 0, "size": 5, "srchKeyword": "", "useYn": "Y"},
        },
        {
            "name": "③ EIGW 시간대별 통계 (오늘)",
            "method": "GET",
            "url": "/api/statistic/hourly/eigw",
            "params": {"statDate": TODAY, "srchType": ""},
        },
        {
            "name": "④ EIGW 월간 요약",
            "method": "GET",
            "url": "/api/statistic/monthly/summary",
            "params": {"statDate": THIS_MONTH},
        },
        {
            "name": "⑤ EIGW 월간 오류 통계",
            "method": "GET",
            "url": "/api/statistic/monthly/eigwError",
            "params": {"statDate": THIS_MONTH, "pageNo": 1, "size": 5, "pageCount": 0},
        },
        {
            "name": "⑥ 큐 적체량 (오늘)",
            "method": "GET",
            "url": "/api/monitoring/queueDepth",
            "params": {"date": TODAY},
        },
    ]

    for t in tests:
        print(f"{'─'*60}")
        print(f"{t['name']}")
        print(f"  GET {NARU_BASE_URL}{t['url']}")
        try:
            resp = await session.get(t["url"], params=t["params"])
            body = resp.json()
            rst_cd = body.get("rstCd", "?")
            symbol = "✅" if rst_cd == "S" else "❌"
            print(f"  Status: {resp.status_code} | rstCd: {rst_cd} {symbol}")
            print(f"  Response:\n{pretty(body)}")
        except Exception as e:
            print(f"  ❌ 오류: {e}")
        print()

    await session.aclose()


if __name__ == "__main__":
    asyncio.run(run_tests())
