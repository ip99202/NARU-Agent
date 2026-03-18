from langchain_openai import AzureChatOpenAI

from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_DEPLOYMENT,
)


def main() -> None:
    llm = AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT,
        api_version=AZURE_OPENAI_API_VERSION,
        # gpt-5 계열은 temperature=0 미지원 → 기본값 사용
    )

    print(f"Using deployment: {AZURE_OPENAI_DEPLOYMENT}")
    resp = llm.invoke("너 모델 이름이랑 버전을 한 줄로 말해줘.")
    print("Response:")
    print(resp)


if __name__ == "__main__":
    main()

