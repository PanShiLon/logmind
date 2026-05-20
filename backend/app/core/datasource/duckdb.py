from datetime import datetime
from typing import Optional, List, Dict, Any

import duckdb

from .base import LogDataSource, LogEntry, SearchResult
from ..settings import DatasourceConfig


class DuckDBDataSource(LogDataSource):
    """DuckDB 本地存储数据源（Native 模式，配合内置 Collector 使用）"""

    def __init__(self, config: DatasourceConfig):
        db_path = config.db_path or "./data/logmind.db"
        self._conn = duckdb.connect(db_path)
        self._ensure_schema()

    def _ensure_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id          BIGINT PRIMARY KEY,
                ts          TIMESTAMP,
                level       VARCHAR,
                message     TEXT,
                source      VARCHAR,
                raw         TEXT
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON logs(ts)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_level ON logs(level)")

    def _row_to_entry(self, row: tuple) -> LogEntry:
        # id, ts, level, message, source, raw
        return LogEntry(
            timestamp=row[1],
            level=row[2] or "UNKNOWN",
            message=row[3] or "",
            source=row[4] or "",
            raw=row[5] or "",
        )

    def _time_filter(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> tuple[str, list]:
        clauses, params = [], []
        if start_time:
            clauses.append("ts >= ?")
            params.append(start_time)
        if end_time:
            clauses.append("ts <= ?")
            params.append(end_time)
        return (" AND ".join(clauses), params)

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

        clauses, params = [], []
        if query:
            clauses.append("message ILIKE ?")
            params.append(f"%{query}%")
        if level:
            clauses.append("level = ?")
            params.append(level.upper())
        if servers:
            placeholders = ",".join(["?" for _ in servers])
            clauses.append(f"source IN ({placeholders})")
            params.extend(servers)
        tc, tp = self._time_filter(start_time, end_time)
        if tc:
            clauses.append(tc)
            params.extend(tp)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        count_sql = f"SELECT COUNT(*) FROM logs {where}"
        total = self._conn.execute(count_sql, params).fetchone()[0]

        sql = f"SELECT * FROM logs {where} ORDER BY ts DESC LIMIT ? OFFSET ?"
        params.append(limit)
        params.append(offset)

        rows = self._conn.execute(sql, params).fetchall()
        entries = [self._row_to_entry(r) for r in rows]
        took = int((time.monotonic() - t0) * 1000)
        return SearchResult(entries=entries, total=total, took_ms=took)

    async def aggregate(
        self,
        field: str,
        query: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, int]:
        clauses, params = [], []
        if query:
            clauses.append("message ILIKE ?")
            params.append(f"%{query}%")
        tc, tp = self._time_filter(start_time, end_time)
        if tc:
            clauses.append(tc)
            params.extend(tp)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT {field}, COUNT(*) FROM logs {where} GROUP BY {field} ORDER BY 2 DESC LIMIT 50"
        rows = self._conn.execute(sql, params).fetchall()
        return {str(r[0]): r[1] for r in rows}

    async def time_series(
        self,
        interval: str = "1m",
        query: Optional[str] = None,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        trunc = {
            "1m": "minute", "5m": "minute", "1h": "hour", "1d": "day"
        }.get(interval, "minute")

        clauses, params = [], []
        if query:
            clauses.append("message ILIKE ?")
            params.append(f"%{query}%")
        if level:
            clauses.append("level = ?")
            params.append(level.upper())
        tc, tp = self._time_filter(start_time, end_time)
        if tc:
            clauses.append(tc)
            params.extend(tp)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT date_trunc('{trunc}', ts) AS bucket, COUNT(*)
            FROM logs {where}
            GROUP BY bucket ORDER BY bucket
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [{"timestamp": str(r[0]), "count": r[1]} for r in rows]

    async def health_check(self) -> Dict[str, Any]:
        try:
            count = self._conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            return {"status": "ok", "datasource": "duckdb", "total_logs": count}
        except Exception as e:
            return {"status": "error", "message": str(e)}
