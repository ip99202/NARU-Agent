"""
NARU-Agent 설정 모듈
환경 변수에서 API 접속 정보를 로드합니다.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Anthropic
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

# NARU API
NARU_BASE_URL: str = os.environ.get("NARU_BASE_URL", "http://150.206.10.180:8080")
NARU_USER_ID: str  = os.environ.get("NARU_USER_ID", "P185933")
NARU_USER_PW: str  = os.environ.get("NARU_USER_PW", "skccskcc!!")
