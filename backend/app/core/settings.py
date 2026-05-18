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


class CollectorConfig(BaseModel):
    enabled: bool = False
    interval_seconds: int = 30
    servers: List[SSHServerConfig] = Field(default_factory=list)


class Settings(BaseModel):
    llm: LLMConfig
    datasource: DatasourceConfig = Field(default_factory=DatasourceConfig)
    servers: List[SSHServerConfig] = Field(default_factory=list)
    collector: Optional[CollectorConfig] = None


_settings: Optional[Settings] = None

CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"


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
