from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class LogEntry:
    timestamp: Optional[datetime]
    level: str          # ERROR / WARN / INFO / DEBUG / UNKNOWN
    message: str
    source: str         # 来源服务器或索引名
    raw: str            # 原始行文本
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    entries: List[LogEntry]
    total: int
    took_ms: int


class LogDataSource(ABC):
    """
    所有数据源的统一抽象接口。
    Tool 层只依赖此接口，不感知底层是 SSH / DuckDB / Elasticsearch。
    """

    @abstractmethod
    async def search(
        self,
        query: str,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        servers: Optional[List[str]] = None,
    ) -> SearchResult:
        """全文搜索日志"""
        ...

    @abstractmethod
    async def aggregate(
        self,
        field: str,
        query: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, int]:
        """聚合统计，返回 {value: count} 字典"""
        ...

    @abstractmethod
    async def time_series(
        self,
        interval: str = "1m",
        query: Optional[str] = None,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """时序数据，返回 [{timestamp, count, ...}] 列表"""
        ...

    async def health_check(self) -> Dict[str, Any]:
        """数据源连通性检查，子类可覆盖"""
        return {"status": "ok", "datasource": self.__class__.__name__}
