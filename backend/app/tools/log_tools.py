from datetime import datetime
from typing import Optional, List
from langchain_core.tools import tool

from ..core.datasource.base import LogDataSource


def make_log_tools(datasource: LogDataSource) -> list:

    @tool
    async def search_logs(
        query: str,
        level: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 50,
        servers: Optional[str] = None,
    ) -> str:
        """
        搜索日志。
        - query: 搜索日志内容的关键词或正则，例如 "NullPointerException"、"timeout"。注意：不要传日志级别（如ERROR），级别过滤请用 level 参数
        - level: 日志级别过滤 ERROR / WARN / INFO / DEBUG
        - start_time / end_time: ISO 8601 格式，例如 "2024-01-01T00:00:00"
        - limit: 最多返回条数（默认 50）
        - servers: 指定服务器名称，多个用逗号分隔
        """
        st = datetime.fromisoformat(start_time) if start_time else None
        et = datetime.fromisoformat(end_time) if end_time else None
        sv = [s.strip() for s in servers.split(",")] if servers else None

        print(f"[DEBUG search_logs] query={query!r}, level={level!r}, start_time={start_time!r}, end_time={end_time!r}, limit={limit}, servers={servers!r}")

        result = await datasource.search(
            query=query, level=level,
            start_time=st, end_time=et,
            limit=limit, servers=sv,
        )

        if not result.entries:
            return f"未找到匹配 '{query}' 的日志（耗时 {result.took_ms}ms）"

        import json as _json
        entries_json = []
        for e in result.entries[:50]:
            ts = e.timestamp.strftime("%Y-%m-%d %H:%M:%S") if e.timestamp else None
            msg = (e.message or "")[:500].replace("\x00", "")
            entries_json.append({
                "timestamp": ts,
                "level": e.level,
                "source": e.source,
                "message": msg,
            })

        lines = [f"找到 {result.total} 条日志（耗时 {result.took_ms}ms）：\n"]
        for e in result.entries[:20]:
            ts = e.timestamp.strftime("%Y-%m-%d %H:%M:%S") if e.timestamp else "??:??:??"
            lines.append(f"[{ts}] [{e.level}] [{e.source}] {e.message[:200]}")
        if result.total > 20:
            lines.append(f"... 还有 {result.total - 20} 条未展示")

        log_data = _json.dumps({
            "total": result.total,
            "took_ms": result.took_ms,
            "entries": entries_json,
            "query_params": {
                "query": query,
                "level": level,
                "start_time": start_time,
                "end_time": end_time,
                "servers": servers,
            },
        }, ensure_ascii=False)
        lines.append(f"\n<log_data>{log_data}</log_data>")
        return "\n".join(lines)

    @tool
    async def count_errors(
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        level: str = "ERROR",
    ) -> str:
        """
        统计指定时间范围内各日志级别的数量。
        - level: 要统计的级别（默认 ERROR）
        - start_time / end_time: ISO 8601 格式
        """
        st = datetime.fromisoformat(start_time) if start_time else None
        et = datetime.fromisoformat(end_time) if end_time else None
        counts = await datasource.aggregate(
            field="level", start_time=st, end_time=et
        )
        if not counts:
            return "暂无日志数据"
        lines = ["各级别日志统计："]
        for lv, cnt in counts.items():
            lines.append(f"  {lv}: {cnt} 条")
        return "\n".join(lines)

    @tool
    async def get_error_trend(
        interval: str = "1h",
        level: str = "ERROR",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> str:
        """
        获取错误日志的时间趋势，用于判断问题是否在加剧。
        - interval: 时间粒度 1m / 5m / 1h / 1d
        - level: 日志级别（默认 ERROR）
        """
        st = datetime.fromisoformat(start_time) if start_time else None
        et = datetime.fromisoformat(end_time) if end_time else None
        series = await datasource.time_series(
            interval=interval, level=level, start_time=st, end_time=et
        )
        if not series:
            return f"无 {level} 级别日志趋势数据"
        lines = [f"{level} 级别趋势（间隔 {interval}）："]
        for point in series[-20:]:  # 只展示最近 20 个点
            bar = "█" * min(int(point["count"] / max(1, max(p["count"] for p in series)) * 20), 20)
            lines.append(f"  {point['timestamp']}  {bar} {point['count']}")
        return "\n".join(lines)

    @tool
    async def analyze_exception(keyword: str, limit: int = 20) -> str:
        """
        深入分析某个异常或错误关键词，提取堆栈、频率、首次/末次出现时间。
        - keyword: 异常名称，例如 "NullPointerException" 或 "Connection refused"
        """
        result = await datasource.search(query=keyword, level="ERROR", limit=limit)
        if not result.entries:
            result = await datasource.search(query=keyword, limit=limit)

        if not result.entries:
            return f"未找到包含 '{keyword}' 的日志"

        timestamps = [e.timestamp for e in result.entries if e.timestamp]
        first_seen = min(timestamps).strftime("%Y-%m-%d %H:%M:%S") if timestamps else "未知"
        last_seen = max(timestamps).strftime("%Y-%m-%d %H:%M:%S") if timestamps else "未知"

        lines = [
            f"异常分析: {keyword}",
            f"共出现 {result.total} 次，首次: {first_seen}，最近: {last_seen}",
            "",
            "典型样本（最多5条）：",
        ]
        for e in result.entries[:5]:
            ts = e.timestamp.strftime("%Y-%m-%d %H:%M:%S") if e.timestamp else "?"
            lines.append(f"[{ts}] {e.raw[:300]}")
        return "\n".join(lines)

    @tool
    async def health_check() -> str:
        """检查日志数据源连通性"""
        status = await datasource.health_check()
        if status.get("status") == "ok":
            info = {k: v for k, v in status.items() if k != "status"}
            return f"数据源连接正常 {info}"
        return f"数据源连接异常: {status.get('message', '未知错误')}"

    @tool
    async def get_service_error_stats(
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        top_n: int = 10,
    ) -> str:
        """
        统计各服务的错误数量，用于生成柱状图或饼图。
        - top_n: 返回错误最多的前 N 个服务
        - start_time / end_time: ISO 8601 格式
        返回 JSON 格式的服务名→错误数映射。
        """
        st = datetime.fromisoformat(start_time) if start_time else None
        et = datetime.fromisoformat(end_time) if end_time else None
        counts = await datasource.aggregate(field="service_name", start_time=st, end_time=et)
        if not counts:
            return "暂无服务错误数据"
        top = dict(list(counts.items())[:top_n])
        import json
        return json.dumps({"type": "service_error_stats", "data": top}, ensure_ascii=False)

    @tool
    async def get_time_series_chart(
        interval: str = "1h",
        level: str = "ERROR",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> str:
        """
        获取日志时间趋势数据，用于生成折线图。
        - interval: 时间粒度 1m / 5m / 15m / 1h / 1d
        - level: 日志级别 ERROR / WARN / INFO
        - start_time / end_time: ISO 8601 格式
        返回 JSON 格式的时间序列数据。
        """
        st = datetime.fromisoformat(start_time) if start_time else None
        et = datetime.fromisoformat(end_time) if end_time else None
        series = await datasource.time_series(interval=interval, level=level, start_time=st, end_time=et)
        if not series:
            return f"无 {level} 趋势数据"
        import json
        return json.dumps({"type": "time_series", "level": level, "interval": interval, "data": series}, ensure_ascii=False)

    return [search_logs, count_errors, get_error_trend, analyze_exception, health_check,
            get_service_error_stats, get_time_series_chart]
