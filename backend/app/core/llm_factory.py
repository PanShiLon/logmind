from langchain_openai import ChatOpenAI
from .settings import LLMConfig

_PROVIDER_DEFAULTS = {
    "openai": "https://api.openai.com/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}


def create_llm(config: LLMConfig, streaming: bool = False) -> ChatOpenAI:
    base_url = config.base_url or _PROVIDER_DEFAULTS.get(config.provider)
    if not base_url:
        raise ValueError(f"未知 provider: {config.provider}，请在配置中指定 base_url")

    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=base_url,
        streaming=streaming,
        temperature=0.1,
    )
