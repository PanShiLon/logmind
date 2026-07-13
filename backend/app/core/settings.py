from pathlib import Path
from typing import Optional, List
import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str = "kimi"
    api_key: str
    model: str = "moonshot-v1-8k"
    base_url: str = "https://api.moonshot.cn/v1"


class SSHServerConfig(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str
    password: Optional[str] = None
    private_key_path: Optional[str] = None
    log_paths: List[str] = Field(default_factory=list)


class DatasourceConfig(BaseModel):
    type: str = "ssh"
    # DuckDB
    db_path: Optional[str] = None
    # Elasticsearch
    hosts: Optional[List[str]] = None
    username: Optional[str] = None
    password: Optional[str] = None
    default_index: Optional[str] = "app-logs-*"
    verify_certs: bool = True
    # Loki
    loki_url: Optional[str] = None            # 例：http://localhost:3100
    loki_selector: Optional[str] = None       # 例：{container_name=~".+"}，默认匹配全部容器


class CollectorConfig(BaseModel):
    enabled: bool = False
    interval_seconds: int = 30
    servers: List[SSHServerConfig] = Field(default_factory=list)


class HttpTesterConfig(BaseModel):
    """HTTP 请求测试器：平台内直接发请求。仅面向本地开发，注意 SSRF 风险。"""
    enabled: bool = True
    # 为空 = 只走内置元数据地址黑名单（宽松，本地默认）；
    # 填了 = 只放行列表内 host（严格，仅放行验收目标域名）
    allow_hosts: List[str] = Field(default_factory=list)


class Settings(BaseModel):
    llm: LLMConfig
    datasource: DatasourceConfig = Field(default_factory=DatasourceConfig)
    servers: List[SSHServerConfig] = Field(default_factory=list)
    collector: Optional[CollectorConfig] = None
    http_tester: HttpTesterConfig = Field(default_factory=HttpTesterConfig)


_settings: Optional[Settings] = None

CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
# HTTP 测试器白名单/开关的运行时状态，与 config.yaml 同目录。
# 单独存 JSON 而非回写 config.yaml，是为了保住 config.yaml 里大段注释掉的数据源示例。
HTTP_TESTER_STATE_PATH = Path(__file__).parent.parent.parent / "http_tester_state.json"


def _apply_http_tester_sidecar(settings: Settings) -> None:
    """若存在 sidecar 状态文件，用它覆盖 http_tester 配置（UI 开关写这里）。"""
    if not HTTP_TESTER_STATE_PATH.exists():
        return
    try:
        import json
        with open(HTTP_TESTER_STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f) or {}
        settings.http_tester = HttpTesterConfig(**{**settings.http_tester.model_dump(), **state})
    except Exception:
        # sidecar 坏了不影响主配置加载，回退到 config.yaml 里的值
        pass


def load_settings(path: Optional[Path] = None) -> Settings:
    global _settings
    config_file = path or CONFIG_PATH
    if not config_file.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {config_file}\n"
            f"请复制 config.example.yaml 为 config.yaml 并填入配置"
        )
    with open(config_file, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    _settings = Settings(**raw)
    _apply_http_tester_sidecar(_settings)
    return _settings


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reload_settings() -> Settings:
    global _settings
    _settings = None
    return get_settings()
