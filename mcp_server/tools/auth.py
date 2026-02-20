"""
NARU API 세션 관리 모듈

로그인 흐름 (2단계):
  1. POST /api/verify-code/pre-login  (JSON)    → 사전 검증
  2. POST /api/loginProc              (FormData) → JSESSIONID 쿠키 발급

이후 모든 API 호출 시 httpx.AsyncClient가 JSESSIONID를 자동으로 포함.
세션 만료(401) 시 자동 재로그인.
"""
import httpx
from config import NARU_BASE_URL, NARU_USER_ID, NARU_USER_PW

_session: httpx.AsyncClient | None = None


async def login() -> httpx.AsyncClient:
    """2단계 NARU 로그인 후 인증된 세션 클라이언트를 반환합니다."""
    client = httpx.AsyncClient(
        base_url=NARU_BASE_URL,
        timeout=30.0,
        follow_redirects=True,
    )

    # Step 1: pre-login (JSON)
    step1 = await client.post(
        "/api/verify-code/pre-login",
        json={"userId": NARU_USER_ID, "userPw": NARU_USER_PW},
    )
    step1.raise_for_status()
    body1 = step1.json()
    if body1.get("rstCd") != "S":
        raise RuntimeError(f"pre-login 실패: {body1}")
    print(f"[Auth] Step 1 pre-login 성공 | rstCd={body1['rstCd']}")

    # Step 2: loginProc (FormData) → JSESSIONID 발급
    step2 = await client.post(
        "/api/loginProc",
        data={"userId": NARU_USER_ID, "userPw": NARU_USER_PW},
    )
    step2.raise_for_status()
    cookies = dict(client.cookies)
    if not cookies:
        raise RuntimeError("loginProc 후 쿠키가 없습니다. 로그인 실패.")
    print(f"[Auth] Step 2 loginProc 성공 | 쿠키: {list(cookies.keys())}")

    return client


async def get_session() -> httpx.AsyncClient:
    """
    인증된 세션을 반환합니다.
    세션이 없거나 만료(401)된 경우 자동으로 재로그인합니다.
    """
    global _session

    if _session is None:
        _session = await login()
        return _session

    # 세션 유효성 확인
    try:
        probe = await _session.get("/api/bizcomm/chrgr/my", timeout=5.0)
        if probe.status_code == 401:
            print("[Auth] 세션 만료 감지 → 재로그인")
            await _session.aclose()
            _session = await login()
    except httpx.RequestError:
        print("[Auth] 세션 확인 실패 → 재로그인")
        _session = await login()

    return _session


async def close_session() -> None:
    """세션 종료 (앱 종료 시 호출)."""
    global _session
    if _session:
        await _session.aclose()
        _session = None
        print("[Auth] 세션 종료")
