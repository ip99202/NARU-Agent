"""
NARU-Agent 설정 모듈
환경 변수에서 API 접속 정보를 로드합니다.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 어느 디렉토리에서 실행하든 프로젝트 루트의 .env를 찾습니다
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)

# ── Azure OpenAI ──────────────────────────────────────────
AZURE_OPENAI_API_KEY: str      = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT: str     = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_VERSION: str  = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
AZURE_OPENAI_DEPLOYMENT: str   = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")

# ── NARU API ──────────────────────────────────────────────
# 계정 정보(ID/PW)는 Chainlit UI에서 런타임에 입력받으므로 여기서 로드하지 않습니다.
NARU_BASE_URL: str = os.environ.get("NARU_BASE_URL", "")
