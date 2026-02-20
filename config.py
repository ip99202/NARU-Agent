"""
NARU-Agent 설정 모듈
환경 변수에서 API 접속 정보를 로드합니다.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Azure OpenAI ──────────────────────────────────────────
AZURE_OPENAI_API_KEY: str      = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT: str     = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_VERSION: str  = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
AZURE_OPENAI_DEPLOYMENT: str   = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")

# ── NARU API ──────────────────────────────────────────────
NARU_BASE_URL: str = os.environ.get("NARU_BASE_URL", "")
NARU_USER_ID: str  = os.environ.get("NARU_USER_ID", "")
NARU_USER_PW: str  = os.environ.get("NARU_USER_PW", "")
