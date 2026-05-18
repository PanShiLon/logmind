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

    @abstractmethod
    async def search(
        self,
        query: str,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        servers: Optional[List[str]] = None,
    ) -> SearchResult: ...

    @abstractmethod
    async def aggregate(
        self,
        field: str,
        query: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, int]: ...

    @abstractmethod
    async def time_series(
        self,
        interval: str = "1m",
        query: Optional[str] = None,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]: ...

    async def health_check(self) -> Dict[str, Any]:
        return {"status": "ok", "datasource": self.__class__.__name__}
