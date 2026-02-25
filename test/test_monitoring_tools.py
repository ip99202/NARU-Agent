"""
모니터링 MCP Tools API 검증 스크립트

11개의 모니터링 API를 직접 호출하여 응답을 검증합니다.
실행: python3 test/test_monitoring_tools.py
"""
import asyncio
import json
import sys
import os

# 프로젝트 루트를 PYTHONPATH에 추가
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import httpx
from datetime import date
from config import NARU_BASE_URL, NARU_USER_ID, NARU_USER_PW

TODAY = date.today().strftime("%Y%m%d")


async def make_session() -> httpx.AsyncClient:
    client = httpx.AsyncClient(base_url=NARU_BASE_URL, timeout=30.0, follow_redirects=True)
    r1 = await client.post("/api/verify-code/pre-login", json={"userId": NARU_USER_ID, "userPw": NARU_USER_PW})
    r1.raise_for_status()
    r2 = await client.post("/api/loginProc", data={"userId": NARU_USER_ID, "userPw": NARU_USER_PW})
    r2.raise_for_status()
    print(f"✅ 로그인 성공 | 쿠키: {list(client.cookies.keys())}\n")
    return client


def pretty(data: dict | list, max_len: int = 800) -> str:
    s = json.dumps(data, ensure_ascii=False, indent=2)
    return s[:max_len] + "\n...(truncated)" if len(s) > max_len else s


def print_result(name: str, body: dict) -> None:
    """응답 결과를 보기 좋게 출력합니다."""
    rst_cd  = body.get("rstCd", "?")
    rst_msg = body.get("rstMsg", "")
    symbol  = "✅" if rst_cd == "S" else "❌"
    print(f"  rstCd: {rst_cd} {symbol}  |  rstMsg: {rst_msg}")

    rst_data = body.get("rstData", {})
    if isinstance(rst_data, dict):
        for key, val in rst_data.items():
            if isinstance(val, list):
                print(f"  [{key}] → {len(val)}건")
                if val:
                    print(f"    첫 번째 항목: {pretty(val[0], 400)}")
            else:
                print(f"  [{key}] → {pretty(val, 200)}")
    else:
        print(f"  rstData: {pretty(rst_data)}")


async def run_tests():
    session = await make_session()

    tests = [
        # ① 큐 깊이 모니터링
        {
            "name": "① MQ 큐 깊이(Queue Depth) 모니터링",
            "url":  "/api/monitoring/queueDepth",
            "params": {"date": TODAY},
            "validate": lambda body: (
                "queueDepthList" in body.get("rstData", {}),
                f"queueDepthList 확인: {len(body.get('rstData', {}).get('queueDepthList', []))}건"
            ),
        },
        # ② EIGW 온라인 에러 목록
        {
            "name": "② EIGW 온라인 에러 목록",
            "url":  "/api/monitoring/eigw/onlineErrorList",
            "params": {},
            "validate": lambda body: (
                "eigwOnlineErrorList" in body.get("rstData", {}),
                f"eigwOnlineErrorList 확인: {len(body.get('rstData', {}).get('eigwOnlineErrorList', []))}건"
            ),
        },
        # ③ EAI IF DB 잔여 카운트
        {
            "name": "③ EAI 인터페이스 DB 잔여 카운트",
            "url":  "/api/monitoring/eai/ifDbRemainCnt",
            "params": {},
            "validate": lambda body: (
                "eaiIfDbRemainList" in body.get("rstData", {}),
                f"eaiIfDbRemainList 확인: {len(body.get('rstData', {}).get('eaiIfDbRemainList', []))}건"
            ),
        },
        # ④ MCG 전체 채널 상태
        {
            "name": "④ MCG 전체 채널 상태 조회",
            "url":  "/api/monitoring/mcg/chnlStatusAll",
            "params": {
                "pageNo": 1, "pageCount": 0, "size": 10,
                "outboundYn": "Y", "allServerYn": "Y", "useYn": "Y",
            },
            "validate": lambda body: (
                "mcgOutTpsStatus" in body.get("rstData", {}),
                f"mcgOutTpsStatus({len(body.get('rstData',{}).get('mcgOutTpsStatus',[]))}건) "
                f"mcgSwgStatus({len(body.get('rstData',{}).get('mcgSwgStatus',[]))}건) "
                f"mcgInChnlStatus({len(body.get('rstData',{}).get('mcgInChnlStatus',[]))}건)"
            ),
        },

        # ─── 신규 추가 API ─────────────────────────────────────────
        # ⑤ EIGW 온라인 에러건수 그래프
        {
            "name": "⑤ EIGW 온라인 에러건수 그래프",
            "url":  "/api/monitoring/eigw/onlineErrorList/graph",
            "params": {
                "date": TODAY,
                "interval": -60,
                "eaiIfId": "",
                "instCd": "",
                "inputConf": "",
            },
            "validate": lambda body: (
                "eigwOnlineErrorList" in body.get("rstData", {}),
                f"eigwOnlineErrorList 확인: {len(body.get('rstData', {}).get('eigwOnlineErrorList', []))}건"
            ),
        },
        # ⑥ EIGW 온라인 연동량(트랜잭션 카운트)
        {
            "name": "⑥ EIGW 온라인 연동량(트랜잭션 카운트)",
            "url":  "/api/monitoring/eigw/onlineTrmsCntList",
            "params": {
                "date": TODAY,
                "interval": -30,
                "eaiIfId": "",
                "instCd": "",
                "inputConf": "",
            },
            "validate": lambda body: (
                "eigwOnlineTrmsCntList" in body.get("rstData", {}),
                f"eigwOnlineTrmsCntList 확인: {len(body.get('rstData', {}).get('eigwOnlineTrmsCntList', []))}건"
            ),
        },
        # ⑦ EIGW 온라인 응답속도(경과 시간)
        {
            "name": "⑦ EIGW 온라인 응답속도(경과 시간)",
            "url":  "/api/monitoring/eigw/onlineElapList",
            "params": {
                "date": TODAY,
                "interval": -60,
                "eaiIfId": "",
                "instCd": "",
                "inputConf": "",
                "orderByRle": "ELAP",
                "pageNo": 1,
                "pageCount": 1,
                "size": 5,
            },
            "validate": lambda body: (
                "eigwElapDetail" in body.get("rstData", {}),
                f"eigwElapDetail 확인: {len(body.get('rstData', {}).get('eigwElapDetail', []))}건"
            ),
        },
        # ⑧ EIGW 파일 연동량
        {
            "name": "⑧ EIGW 파일 연동량",
            "url":  "/api/monitoring/eigw/fileTrmsList",
            "params": {
                "date": TODAY,
                "interval": -30,
                "eaiIfId": "",
                "instCd": "",
                "fileNm": "",
                "inputConf": "",
                "stCdList": "SUCC,FAIL,REPROC",
                "isUsingtimeCondition": "false",
                "pageNo": 1,
                "pageCount": 0,
                "size": 10,
            },
            "validate": lambda body: (
                "eigwFileTrmsList" in body.get("rstData", {}),
                f"eigwFileTrmsList({len(body.get('rstData',{}).get('eigwFileTrmsList',[]))}건) "
                f"pageSet({body.get('rstData',{}).get('pageSet',{})})"
            ),
        },
        # ⑨ MCG 아웃바운드 TPS 이력
        {
            "name": "⑨ MCG 아웃바운드 TPS 이력",
            "url":  "/api/monitoring/mcg/outTpsStatus",
            "params": {
                "date": TODAY,
                "interval": -120,
                "pageNo": 1,
                "pageCount": 1,
                "size": 5,
            },
            "validate": lambda body: (
                "mcgOutTpsDetail" in body.get("rstData", {}),
                f"mcgOutTpsDetail 확인: {len(body.get('rstData', {}).get('mcgOutTpsDetail', []))}건"
            ),
        },
        # ⑩ MCG 인바운드 채널 상태
        {
            "name": "⑩ MCG 인바운드 채널 상태",
            "url":  "/api/monitoring/mcg/chnlStatusIn",
            "params": {
                "pageNo": 1,
                "pageCount": 0,
                "size": 9999,
            },
            "validate": lambda body: (
                "mcgInChnlStatus" in body.get("rstData", {}),
                f"mcgInChnlStatus({len(body.get('rstData',{}).get('mcgInChnlStatus',[]))}건) "
                f"pageSet({body.get('rstData',{}).get('pageSet',{})})"
            ),
        },
        # ⑪ MCG 아웃바운드 채널 상태
        {
            "name": "⑪ MCG 아웃바운드 채널 상태",
            "url":  "/api/monitoring/mcg/chnlStatusOut",
            "params": {
                "pageNo": 1,
                "pageCount": 0,
                "size": 9999,
                "outboundYn": "Y",
                "allServerYn": "Y",
                "useYn": "Y",
            },
            "validate": lambda body: (
                "mcgOutTpsStatus" in body.get("rstData", {}),
                f"mcgOutTpsStatus({len(body.get('rstData',{}).get('mcgOutTpsStatus',[]))}건) "
                f"pageSet({body.get('rstData',{}).get('pageSet',{})})"
            ),
        },
    ]

    passed = 0
    failed = 0

    for t in tests:
        sep = "─" * 65
        print(sep)
        print(f"🔍 {t['name']}")
        print(f"   GET {NARU_BASE_URL.rstrip('/')}{t['url']}")
        if t["params"]:
            print(f"   params: {t['params']}")
        try:
            resp = await session.get(t["url"], params=t["params"])
            body = resp.json()

            print(f"   HTTP: {resp.status_code}")
            print_result(t["name"], body)

            # 도메인 검증
            ok, detail = t["validate"](body)
            if ok and body.get("rstCd") == "S":
                print(f"  ✅ 검증 통과: {detail}")
                passed += 1
            else:
                print(f"  ❌ 검증 실패: {detail}")
                failed += 1

        except Exception as e:
            print(f"  ❌ 예외 발생: {e}")
            failed += 1
        print()

    print("─" * 65)
    print(f"📊 테스트 결과: {passed}개 통과 / {failed}개 실패 (총 {passed+failed}개)")
    print("─" * 65)

    await session.aclose()


if __name__ == "__main__":
    asyncio.run(run_tests())
