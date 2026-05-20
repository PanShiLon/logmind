from datetime import datetime
from typing import Optional, List, Dict, Any

from elasticsearch import AsyncElasticsearch

from .base import LogDataSource, LogEntry, SearchResult
from ..settings import DatasourceConfig


class ESDataSource(LogDataSource):
    """Elasticsearch 数据源（Bridge 模式，接入已有 ELK）"""

    def __init__(self, config: DatasourceConfig):
        self._index = config.default_index or "app-logs-*"
        self._es = AsyncElasticsearch(
            hosts=config.hosts or ["http://localhost:9200"],
            basic_auth=(config.username, config.password)
            if config.username
            else None,
            verify_certs=config.verify_certs,
        )

    def _hit_to_entry(self, hit: dict) -> LogEntry:
        src = hit.get("_source", {})
        app = src.get("app", {})
        ts_raw = src.get("@timestamp") or app.get("timestamp") or src.get("timestamp")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else None
        except (ValueError, AttributeError):
            ts = None
        level = (app.get("level") or src.get("level") or src.get("log.level") or "UNKNOWN").upper()
        message = app.get("message") or src.get("message") or src.get("msg") or str(src)
        service = app.get("service_name") or src.get("service_name") or hit.get("_index", "es")
        return LogEntry(
            timestamp=ts,
            level=level,
            message=message,
            source=service,
            raw=str(src),
            extra=src,
        )

    def _build_query(
        self,
        query: Optional[str],
        level: Optional[str],
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> dict:
        must = []
        _LEVELS = {"ERROR", "WARN", "INFO", "DEBUG", "TRACE", "FATAL"}
        if query and not (level and query.upper() in _LEVELS):
            must.append({"wildcard": {"app.message": {"value": f"*{query}*", "case_insensitive": True}}})
        if level:
            must.append({"term": {"app.level": level.upper()}})
        if start_time or end_time:
            range_filter: dict = {}
            if start_time:
                range_filter["gte"] = start_time.isoformat()
            if end_time:
                range_filter["lte"] = end_time.isoformat()
            must.append({"range": {"@timestamp": range_filter}})
        return {"bool": {"must": must}} if must else {"match_all": {}}

    async def search(
        self,
        query: str,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
        servers: Optional[List[str]] = None,
    ) -> SearchResult:
        import time
        t0 = time.monotonic()
        resp = await self._es.search(
            index=self._index,
            query=self._build_query(query, level, start_time, end_time),
            size=limit,
            from_=offset,
            sort=[{"@timestamp": "desc"}],
        )
        hits = resp["hits"]["hits"]
        entries = [self._hit_to_entry(h) for h in hits]
        took = int((time.monotonic() - t0) * 1000)
        return SearchResult(entries=entries, total=resp["hits"]["total"]["value"], took_ms=took)

    async def aggregate(
        self,
        field: str,
        query: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, int]:
        # 字段名映射到实际 ES 字段
        field_map = {"level": "app.level", "service_name": "app.service_name", "env": "app.env"}
        es_field = field_map.get(field, field)
        resp = await self._es.search(
            index=self._index,
            query=self._build_query(query, None, start_time, end_time),
            size=0,
            aggs={"by_field": {"terms": {"field": es_field, "size": 50}}},
        )
        buckets = resp.get("aggregations", {}).get("by_field", {}).get("buckets", [])
        return {b["key"]: b["doc_count"] for b in buckets}

    async def time_series(
        self,
        interval: str = "1m",
        query: Optional[str] = None,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        resp = await self._es.search(
            index=self._index,
            query=self._build_query(query, level, start_time, end_time),
            size=0,
            aggs={
                "over_time": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": interval,
                    }
                }
            },
        )
        buckets = resp.get("aggregations", {}).get("over_time", {}).get("buckets", [])
        return [{"timestamp": b["key_as_string"], "count": b["doc_count"]} for b in buckets]

    async def health_check(self) -> Dict[str, Any]:
        try:
            resp = await self._es.count(index=self._index)
            return {"status": "ok", "datasource": "elasticsearch", "index": self._index, "total": resp["count"]}
        except Exception as e:
            return {"status": "error", "message": str(e)}
