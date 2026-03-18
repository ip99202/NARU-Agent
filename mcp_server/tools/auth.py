"""
NARU API 세션 관리 모듈

로그인 흐름 (2단계):
  1. POST /api/verify-code/pre-login  (JSON)    → 사전 검증
  2. POST /api/loginProc              (FormData) → JSESSIONID 쿠키 발급

이후 모든 API 호출 시 httpx.AsyncClient가 JSESSIONID를 자동으로 포함.

자격증명 전달 방식:
  - app.py가 MultiServerMCPClient에 NARU_USER_ID / NARU_USER_PW 환경변수를 주입
  - MCP 서버 서브프로세스는 os.environ에서 읽어 자동 로그인
  - 세션 만료(401) 수신 시 refresh_session() 호출로 재로그인
  - get_session()은 probe 없이 즉시 반환 (툴 호출마다 불필요한 HTTP 요청 방지)
"""
import os
import httpx
from config import NARU_BASE_URL

# 전역 세션 (MCP Server 서브프로세스 수명주기 동안 유지)
_session: httpx.AsyncClient | None = None


async def login(user_id: str, user_pw: str) -> httpx.AsyncClient:
    """2단계 NARU 로그인 후 인증된 세션 클라이언트를 반환합니다.

    Args:
        user_id: NARU 포털 로그인 ID
        user_pw: NARU 포털 로그인 비밀번호

    Returns:
        인증된 httpx.AsyncClient (JSESSIONID 쿠키 포함)

    Raises:
        RuntimeError: pre-login 실패 또는 쿠키 미발급 시
    """
    client = httpx.AsyncClient(
        base_url=NARU_BASE_URL,
        timeout=30.0,
        follow_redirects=True,
        verify=False,
    )

    # Step 1: pre-login (JSON)
    step1 = await client.post(
        "/api/verify-code/pre-login",
        json={"userId": user_id, "userPw": user_pw},
    )
    step1.raise_for_status()
    body1 = step1.json()
    if body1.get("rstCd") != "S":
        await client.aclose()
        raise RuntimeError(f"pre-login 실패: {body1}")
    print(f"[Auth] Step 1 pre-login 성공 | rstCd={body1['rstCd']}")

    # Step 2: loginProc (FormData) → JSESSIONID 발급
    step2 = await client.post(
        "/api/loginProc",
        data={"userId": user_id, "userPw": user_pw},
    )
    step2.raise_for_status()
    cookies = dict(client.cookies)
    if not cookies:
        await client.aclose()
        raise RuntimeError("loginProc 후 쿠키가 없습니다. 로그인 실패.")
    print(f"[Auth] Step 2 loginProc 성공 | 쿠키: {list(cookies.keys())}")

    return client


async def is_session_valid() -> bool:
    """현재 세션이 유효한지 확인합니다. 로그인 시도는 하지 않습니다.

    Returns:
        True: 세션 유효 / False: 세션 없음 또는 만료
    """
    global _session
    if _session is None:
        return False
    try:
        probe = await _session.get("/api/bizcomm/chrgr/my", timeout=5.0)
        return probe.status_code != 401
    except httpx.RequestError:
        return False


async def get_session() -> httpx.AsyncClient:
    """인증된 세션을 반환합니다.

    세션이 없으면 환경변수(NARU_USER_ID, NARU_USER_PW)로 자동 로그인합니다.
    환경변수는 app.py가 MultiServerMCPClient 실행 시 주입합니다.
    세션이 있으면 probe 없이 즉시 반환합니다.
    세션 만료(401) 수신 시 refresh_session()을 호출하세요.

    Returns:
        인증된 httpx.AsyncClient

    Raises:
        RuntimeError: 환경변수 미설정 또는 로그인 실패 시
    """
    global _session

    user_id = os.environ.get("NARU_USER_ID", "")
    user_pw = os.environ.get("NARU_USER_PW", "")

    if not user_id or not user_pw:
        raise RuntimeError(
            "NARU 자격증명 환경변수(NARU_USER_ID, NARU_USER_PW)가 설정되지 않았습니다."
        )

    if _session is None:
        _session = await login(user_id, user_pw)

    return _session


async def refresh_session() -> httpx.AsyncClient:
    """세션 만료(401) 수신 시 호출 — 기존 세션을 닫고 재로그인 후 반환합니다.

    Returns:
        새로 인증된 httpx.AsyncClient

    Raises:
        RuntimeError: 환경변수 미설정 또는 로그인 실패 시
    """
    global _session

    user_id = os.environ.get("NARU_USER_ID", "")
    user_pw = os.environ.get("NARU_USER_PW", "")

    if not user_id or not user_pw:
        raise RuntimeError(
            "NARU 자격증명 환경변수(NARU_USER_ID, NARU_USER_PW)가 설정되지 않았습니다."
        )

    if _session:
        await _session.aclose()
    print("[Auth] 세션 만료 → 재로그인")
    _session = await login(user_id, user_pw)
    return _session


async def close_session() -> None:
    """세션 종료 (앱 종료 시 호출)."""
    global _session
    if _session:
        await _session.aclose()
        _session = None
        print("[Auth] 세션 종료")
