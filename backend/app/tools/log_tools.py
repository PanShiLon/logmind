from datetime import datetime
from typing import Optional, List
from langchain_core.tools import tool

from ..core.datasource.base import LogDataSource


def make_log_tools(datasource: LogDataSource) -> list:
    """
    工厂函数：将 datasource 注入到所有 Tool 闭包中。
    LangGraph Agent 通过此列表获取可调用 Tool。
    """

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
        - query: 关键词或正则，例如 "NullPointerException"
        - level: 日志级别过滤 ERROR / WARN / INFO / DEBUG
        - start_time / end_time: ISO 8601 格式，例如 "2024-01-01T00:00:00"
        - limit: 最多返回条数（默认 50）
        - servers: 指定服务器名称，多个用逗号分隔
        """
        st = datetime.fromisoformat(start_time) if start_time else None
        et = datetime.fromisoformat(end_time) if end_time else None
        sv = [s.strip() for s in servers.split(",")] if servers else None

        result = await datasource.search(
            query=query, level=level,
            start_time=st, end_time=et,
            limit=limit, servers=sv,
        )

        if not result.entries:
            return f"未找到匹配 '{query}' 的日志（耗时 {result.took_ms}ms）"

        lines = [f"找到 {result.total} 条日志（耗时 {result.took_ms}ms）：\n"]
        for e in result.entries[:20]:
            ts = e.timestamp.strftime("%Y-%m-%d %H:%M:%S") if e.timestamp else "??:??:??"
            lines.append(f"[{ts}] [{e.level}] [{e.source}] {e.message[:200]}")
        if result.total > 20:
            lines.append(f"... 还有 {result.total - 20} 条未展示")
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

    return [search_logs, count_errors, get_error_trend, analyze_exception, health_check]
