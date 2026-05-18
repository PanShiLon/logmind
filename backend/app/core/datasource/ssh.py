import asyncio
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import asyncssh

from .base import LogDataSource, LogEntry, SearchResult
from ...core.settings import SSHServerConfig

# 常见日志格式正则（Spring Boot / Nginx / Plain text）
_SPRING_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.,]\d+)"
    r".*?\s(?P<level>ERROR|WARN|INFO|DEBUG|TRACE)\s"
    r"(?P<msg>.*)"
)
_NGINX_RE = re.compile(
    r'\[(?P<ts>[^\]]+)\]\s+"[^"]*"\s+(?P<status>\d+)'
)
_LEVEL_RE = re.compile(r"\b(ERROR|WARN|WARNING|INFO|DEBUG|TRACE|FATAL|CRITICAL)\b", re.I)


def _parse_line(line: str, source: str) -> LogEntry:
    # Spring Boot
    m = _SPRING_RE.search(line)
    if m:
        try:
            ts = datetime.fromisoformat(m.group("ts").replace(",", "."))
        except ValueError:
            ts = None
        return LogEntry(
            timestamp=ts,
            level=m.group("level").upper(),
            message=m.group("msg").strip(),
            source=source,
            raw=line,
        )
    # 通用级别提取
    lm = _LEVEL_RE.search(line)
    level = lm.group(1).upper() if lm else "UNKNOWN"
    if level == "WARNING":
        level = "WARN"
    return LogEntry(timestamp=None, level=level, message=line, source=source, raw=line)


async def _fetch_server(
    server: SSHServerConfig,
    grep_cmd: str,
    limit: int,
) -> List[str]:
    connect_kwargs: Dict[str, Any] = {
        "host": server.host,
        "port": server.port,
        "username": server.username,
        "known_hosts": None,
    }
    if server.password:
        connect_kwargs["password"] = server.password
    elif server.private_key_path:
        connect_kwargs["client_keys"] = [server.private_key_path]

    lines: List[str] = []
    async with asyncssh.connect(**connect_kwargs) as conn:
        for log_path in server.log_paths:
            cmd = f"{grep_cmd} {log_path} 2>/dev/null | tail -n {limit}"
            result = await conn.run(cmd, check=False)
            if result.stdout:
                lines.extend(result.stdout.splitlines())
    return lines


class SSHDataSource(LogDataSource):

    def __init__(self, servers: List[SSHServerConfig]):
        self._servers = servers

    async def search(
        self,
        query: str,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        servers: Optional[List[str]] = None,
    ) -> SearchResult:
        import time
        t0 = time.monotonic()

        targets = [
            s for s in self._servers
            if servers is None or s.name in servers
        ]

        # 构造 grep 命令
        grep_parts = ["grep -E"]
        if query:
            grep_parts.append(f"'{re.escape(query)}'")
        else:
            grep_parts.append("'.'")  # 匹配全部
        if level:
            # 追加 level 过滤
            grep_parts = ["grep", f"-i '{level}'", "|", "grep -E '.'"]
            grep_cmd = f"grep -iE '{re.escape(query) if query else '.'}'"
            grep_cmd += f" | grep -i '{level}'"
        else:
            grep_cmd = f"grep -E '{re.escape(query) if query else '.'}'"

        # 并发拉取所有服务器
        tasks = [_fetch_server(s, grep_cmd, limit) for s in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        entries: List[LogEntry] = []
        for server, result in zip(targets, results):
            if isinstance(result, Exception):
                continue
            for line in result:
                if line.strip():
                    entries.append(_parse_line(line, server.name))

        entries = entries[:limit]
        took = int((time.monotonic() - t0) * 1000)
        return SearchResult(entries=entries, total=len(entries), took_ms=took)

    async def aggregate(
        self,
        field: str,
        query: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, int]:
        result = await self.search(query=query or "", limit=5000)
        counts: Dict[str, int] = {}
        for entry in result.entries:
            val = getattr(entry, field, None) or entry.extra.get(field, "UNKNOWN")
            counts[str(val)] = counts.get(str(val), 0) + 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    async def time_series(
        self,
        interval: str = "1m",
        query: Optional[str] = None,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        result = await self.search(query=query or "", level=level, limit=10000)
        buckets: Dict[str, int] = {}
        for entry in result.entries:
            if entry.timestamp:
                if interval.endswith("m"):
                    key = entry.timestamp.strftime("%Y-%m-%dT%H:%M")
                elif interval.endswith("h"):
                    key = entry.timestamp.strftime("%Y-%m-%dT%H:00")
                else:
                    key = entry.timestamp.strftime("%Y-%m-%d")
                buckets[key] = buckets.get(key, 0) + 1
        return [{"timestamp": k, "count": v} for k, v in sorted(buckets.items())]

    async def health_check(self) -> Dict[str, Any]:
        if not self._servers:
            return {"status": "error", "message": "未配置任何服务器"}
        s = self._servers[0]
        try:
            connect_kwargs: Dict[str, Any] = {
                "host": s.host, "port": s.port,
                "username": s.username, "known_hosts": None,
            }
            if s.password:
                connect_kwargs["password"] = s.password
            async with asyncssh.connect(**connect_kwargs) as conn:
                await conn.run("echo ok", check=True)
            return {"status": "ok", "datasource": "ssh", "servers": len(self._servers)}
        except Exception as e:
            return {"status": "error", "message": str(e)}
