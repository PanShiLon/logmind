import time
import re
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

import httpx

from .base import LogDataSource, LogEntry, SearchResult
from ..settings import DatasourceConfig

# Loki 常见级别标签值归一
_LEVEL_ALIAS = {
    "WARNING": "WARN",
    "ERR": "ERROR",
    "FATAL": "ERROR",
    "CRITICAL": "ERROR",
}
_LEVELS = {"ERROR", "WARN", "INFO", "DEBUG", "TRACE", "FATAL"}

# 从行内容里提取真实级别：logfmt(level=info) / JSON("level":"info") / 裸词
_LOGFMT_LEVEL = re.compile(r'\blevel[=:]\s*"?([a-zA-Z]+)"?')
_WORD_LEVEL = re.compile(r'\b(ERROR|WARN|WARNING|INFO|DEBUG|TRACE|FATAL|CRITICAL)\b')
# pino 数字级别映射
_PINO_NUM = {60: "ERROR", 50: "ERROR", 40: "WARN", 30: "INFO", 20: "DEBUG", 10: "TRACE"}


def _normalize_level(raw: str) -> str:
    up = (raw or "").upper()
    return _LEVEL_ALIAS.get(up, up)


def _level_from_line(line: str) -> Optional[str]:
    """行内容里的级别比 Loki detected_level 更可信，优先用它。"""
    # pino JSON 数字级别
    if line.lstrip().startswith("{"):
        try:
            obj = json.loads(line)
            lv = obj.get("level")
            if isinstance(lv, int):
                return _PINO_NUM.get(lv)
            if isinstance(lv, str) and lv.strip():
                return _normalize_level(lv)
        except (ValueError, TypeError):
            pass
    m = _LOGFMT_LEVEL.search(line)
    if m:
        return _normalize_level(m.group(1))
    m = _WORD_LEVEL.search(line)
    if m:
        return _normalize_level(m.group(1))
    return None


def _escape_lq(s: str) -> str:
    """转义 LogQL 行过滤里的反引号字符串（用反引号包裹，避免双引号转义地狱）"""
    return s.replace("`", "")


class LokiDataSource(LogDataSource):
    """Grafana Loki 数据源（读现有 Loki HTTP API，不发任何数据给 LLM）。

    仅依赖 Loki 的 REST 接口：
      - /loki/api/v1/query_range  —— 拉日志行 / 时间序列
      - /loki/api/v1/query        —— instant 查询总数
      - /ready                    —— 健康检查
    """

    def __init__(self, config: DatasourceConfig):
        self._base = (config.loki_url or "http://localhost:3100").rstrip("/")
        # 基础标签选择器，例如 {container_name=~".+"}；默认匹配全部容器
        self._selector = config.loki_selector or '{container_name=~".+"}'
        self._timeout = 15.0

    # ── 内部：构造 LogQL ─────────────────────────────────────────
    def _build_logql(self, query: Optional[str], level: Optional[str]) -> str:
        expr = self._selector
        # 关键词行过滤（大小写不敏感）。当 query 本身是级别词且已指定 level 时跳过，
        # 避免 "ERROR" 既当关键词又当级别导致查空（沿用 ES 数据源踩坑经验）。
        if query and not (level and query.upper() in _LEVELS):
            expr += f' |~ `(?i){_escape_lq(query)}`'
        if level:
            # 优先按 level 标签过滤；Loki pipeline 里 level 标签存在才生效
            expr += f' | level=~`(?i){level}`'
        return expr

    def _time_ns(self, dt: Optional[datetime], default: datetime) -> int:
        d = dt or default
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int(d.timestamp() * 1e9)

    def _to_entry(self, line: str, labels: Dict[str, str]) -> LogEntry:
        # 行内容里的真实级别优先，回退到 Loki 标签
        level = _level_from_line(line)
        if not level:
            raw_level = (labels.get("level") or labels.get("detected_level") or "").upper()
            level = _LEVEL_ALIAS.get(raw_level, raw_level) or "UNKNOWN"
        # 本地 dev 是一整坨 scm-bi-dev，靠行内前缀区分；测试服是真容器名
        source = (
            labels.get("service")
            or labels.get("container_name")
            or labels.get("compose_service")
            or "loki"
        )
        return LogEntry(
            timestamp=None,  # 时间在 search 里从 Loki 的 ns 时间戳单独填
            level=level,
            message=line,
            source=source,
            raw=line,
            extra=labels,
        )

    # ── search ───────────────────────────────────────────────────
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
        t0 = time.monotonic()
        now = datetime.now(timezone.utc)
        start_default = now - timedelta(hours=1)
        start_ns = self._time_ns(start_time, start_default)
        end_ns = self._time_ns(end_time, now)

        logql = self._build_logql(query, level)
        # Loki 无 offset，取 limit+offset 条再切片
        fetch = min(limit + offset, 5000)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/loki/api/v1/query_range",
                params={
                    "query": logql,
                    "start": str(start_ns),
                    "end": str(end_ns),
                    "limit": str(fetch),
                    "direction": "backward",  # 最新在前
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # 展平所有 stream 的 values: [ [ts_ns, line], ... ]
        rows: List[tuple] = []
        for stream in data.get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            for ts_ns, line in stream.get("values", []):
                rows.append((int(ts_ns), line, labels))
        # 按时间倒序（最新在前）
        rows.sort(key=lambda r: r[0], reverse=True)
        page = rows[offset: offset + limit]

        entries: List[LogEntry] = []
        for ts_ns, line, labels in page:
            e = self._to_entry(line, labels)
            e.timestamp = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
            entries.append(e)

        total = await self._count(logql, start_ns, end_ns, client_timeout=self._timeout)
        took = int((time.monotonic() - t0) * 1000)
        return SearchResult(entries=entries, total=total or len(rows), took_ms=took)

    async def _count(self, logql: str, start_ns: int, end_ns: int, client_timeout: float) -> int:
        """用 instant 查询数命中总数（count_over_time 覆盖整个时间窗）"""
        span_s = max(1, int((end_ns - start_ns) / 1e9))
        count_expr = f"sum(count_over_time({logql} [{span_s}s]))"
        try:
            async with httpx.AsyncClient(timeout=client_timeout) as client:
                resp = await client.get(
                    f"{self._base}/loki/api/v1/query",
                    params={"query": count_expr, "time": str(end_ns)},
                )
                resp.raise_for_status()
                result = resp.json().get("data", {}).get("result", [])
                if result:
                    return int(float(result[0]["value"][1]))
        except Exception:
            pass
        return 0

    # ── aggregate（按 level / source 分组计数）────────────────────
    async def aggregate(
        self,
        field: str,
        query: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, int]:
        now = datetime.now(timezone.utc)
        start_ns = self._time_ns(start_time, now - timedelta(hours=1))
        end_ns = self._time_ns(end_time, now)
        span_s = max(1, int((end_ns - start_ns) / 1e9))
        field_map = {"level": "level", "service_name": "service", "service": "service",
                     "source": "container_name", "container": "container_name"}
        by = field_map.get(field, field)
        logql = self._build_logql(query, None)
        expr = f"sum by ({by}) (count_over_time({logql} [{span_s}s]))"
        out: Dict[str, int] = {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base}/loki/api/v1/query",
                    params={"query": expr, "time": str(end_ns)},
                )
                resp.raise_for_status()
                for item in resp.json().get("data", {}).get("result", []):
                    key = item.get("metric", {}).get(by, "UNKNOWN")
                    out[key] = int(float(item["value"][1]))
        except Exception:
            pass
        return dict(sorted(out.items(), key=lambda x: x[1], reverse=True))

    # ── time_series ──────────────────────────────────────────────
    async def time_series(
        self,
        interval: str = "1m",
        query: Optional[str] = None,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        start_ns = self._time_ns(start_time, now - timedelta(hours=1))
        end_ns = self._time_ns(end_time, now)
        logql = self._build_logql(query, level)
        expr = f"sum(count_over_time({logql} [{interval}]))"
        out: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base}/loki/api/v1/query_range",
                    params={
                        "query": expr,
                        "start": str(start_ns),
                        "end": str(end_ns),
                        "step": interval,
                    },
                )
                resp.raise_for_status()
                result = resp.json().get("data", {}).get("result", [])
                if result:
                    for ts_s, val in result[0].get("values", []):
                        out.append({
                            "timestamp": datetime.fromtimestamp(float(ts_s), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                            "count": int(float(val)),
                        })
        except Exception:
            pass
        return out

    async def health_check(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base}/ready")
                ok = resp.status_code == 200
            return {
                "status": "ok" if ok else "error",
                "datasource": "loki",
                "url": self._base,
                "selector": self._selector,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
