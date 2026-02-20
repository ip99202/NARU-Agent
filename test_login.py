"""
NARU 로그인 테스트 스크립트 (2단계 로그인)

실행: python3 test_login.py
"""
import asyncio
import json
import httpx
from config import NARU_BASE_URL, NARU_USER_ID, NARU_USER_PW


async def test_login():
    print("=" * 60)
    print("NARU API 로그인 테스트 (2단계)")
    print("=" * 60)
    print(f"  Base URL : {NARU_BASE_URL}")
    print(f"  ID       : {NARU_USER_ID}")
    print()

    async with httpx.AsyncClient(
        base_url=NARU_BASE_URL,
        timeout=30.0,
        follow_redirects=True,
    ) as client:

        # ── Step 1: pre-login ──────────────────────────────────────
        print("[ Step 1 ] POST /api/verify-code/pre-login (JSON)")
        try:
            resp1 = await client.post(
                "/api/verify-code/pre-login",
                json={"userId": NARU_USER_ID, "userPw": NARU_USER_PW},
            )
            body1 = resp1.json()
            print(f"  Status : {resp1.status_code}")
            print(f"  Body   : {json.dumps(body1, ensure_ascii=False)}")

            if body1.get("rstCd") != "S":
                print("  ❌ pre-login 실패. 중단.")
                return
            print("  ✅ pre-login 성공\n")

        except Exception as e:
            print(f"  ❌ 오류: {e}")
            return

        # ── Step 2: loginProc ──────────────────────────────────────
        print("[ Step 2 ] POST /api/loginProc (FormData)")
        try:
            resp2 = await client.post(
                "/api/loginProc",
                data={"userId": NARU_USER_ID, "userPw": NARU_USER_PW},
            )
            print(f"  Status : {resp2.status_code}")
            print(f"  쿠키   : {dict(client.cookies)}")

            try:
                print(f"  Body   : {json.dumps(resp2.json(), ensure_ascii=False)}")
            except Exception:
                print(f"  Body   : {resp2.text[:300]}")

            if client.cookies:
                print(f"\n  ✅ 로그인 완전 성공! JSESSIONID 획득")
                print(f"     쿠키 목록: {list(client.cookies.keys())}")
            else:
                print("\n  ⚠️  쿠키 없음. 로그인은 됐으나 세션 방식 재확인 필요.")

        except Exception as e:
            print(f"  ❌ 오류: {e}")
            return

        # ── Step 3: 인증 후 API 호출 테스트 ──────────────────────
        print("\n[ Step 3 ] GET /api/bizcomm/chrgr/my (내 정보 조회)")
        try:
            resp3 = await client.get("/api/bizcomm/chrgr/my")
            print(f"  Status : {resp3.status_code}")
            try:
                body3 = resp3.json()
                print(f"  Body   : {json.dumps(body3, indent=2, ensure_ascii=False)[:500]}")
            except Exception:
                print(f"  Body   : {resp3.text[:300]}")

            if resp3.status_code == 200:
                print("  ✅ 인증 세션으로 API 호출 성공!")
            else:
                print("  ❌ 인증 실패 또는 권한 없음")
        except Exception as e:
            print(f"  ❌ 오류: {e}")


if __name__ == "__main__":
    asyncio.run(test_login())
