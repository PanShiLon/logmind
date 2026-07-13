from typing import TypedDict, Annotated, Sequence, Optional, Literal
import operator
from datetime import datetime

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from ..core.datasource.base import LogDataSource
from ..core.llm_factory import create_llm
from ..core.settings import get_settings
from ..tools.log_tools import make_log_tools

_QUERY_SYSTEM = """你是 LogMind，一个专业的 AI 日志查询助手。
当前时间：{now}

职责：帮助用户搜索、定位具体日志内容。

原则：
- 【强制】每次用户提出日志相关问题时，必须调用工具查询实时数据，绝不能基于之前对话中的结果推断或复述
- 即使用户问的和上一轮类似，也必须重新调用工具，因为日志数据随时在变化
- 时间范围不明确时默认查最近1小时，"今天"从当天 00:00:00 到现在
- 传给工具的时间格式：ISO 8601，例如 "2026-05-19T00:00:00+08:00"
- 返回结果整理成可读格式，突出关键信息
- 用中文回复

【停止条件】严格遵守，避免无意义循环：
- 单次查询返回 total=0 或 hits=[] 时，最多再换 1 次关键词或时间范围重试，**第 2 次仍空就直接告诉用户"未找到相关日志"**，不要再继续换关键词
- 同一会话内工具调用累计不超过 3 次，达到上限就基于已查到的信息回答，不要继续
- 如果用户问的关键词在多次模糊查询后仍找不到，建议用户检查：服务名是否正确 / 时间范围是否扩大 / 关键字是否拼写错误

可用工具：search_logs / count_errors / health_check
"""

_ANALYSIS_SYSTEM = """你是 LogMind，一个专业的 AI 日志分析助手。
当前时间：{now}

职责：发现异常规律、分析错误趋势、给出根因诊断。

【强制】每次用户提出分析请求时，必须调用工具获取实时数据，绝不能基于之前对话中的结果推断或复述。日志数据随时在变化，历史回答不可信。

分析流程：
1. 先用 get_error_trend 拿时序数据，判断问题是否在加剧
2. 再用 count_errors 看错误分布
3. 用 analyze_exception 深入分析具体异常
4. 综合给出诊断结论

时间格式：ISO 8601，例如 "2026-05-19T00:00:00+08:00"

输出结构：
- **结论**（一句话）
- **数据支撑**（关键数字）
- **可能原因**（1-3条）
- **建议排查方向**

用中文回复，保持专业但易于理解。
"""

_DASHBOARD_SYSTEM = """你是 LogMind，一个专业的日志数据可视化助手。
当前时间：{now}

职责：根据用户请求，调用工具获取数据并生成图表配置。

【强制】每次用户提出图表/可视化请求时，必须调用工具获取实时数据，绝不能基于之前对话中的结果推断。

流程：
1. 调用相应工具获取数据（get_service_error_stats / get_time_series_chart / count_errors）
2. 将工具返回的 JSON 数据包装成 ECharts 配置，用 <chart_config> 标签输出
3. 配置外再给一句简短的文字说明

输出格式（必须严格遵守）：
<chart_config>
{{ECharts option JSON}}
</chart_config>
一句话说明，例如：以上是过去24小时各服务 ERROR 数量分布。

ECharts 配置规范：
- 柱状图（service_error_stats）：type="bar"，xAxis.data=服务名，series[0].data=数量
- 折线图（time_series）：type="line"，xAxis.data=时间点，series[0].data=数量，smooth=true
- 饼图：type="pie"，series[0].data=[{{name,value}}]
- 统一使用深色主题：backgroundColor="#1e2535"，textStyle.color="#e2e8f0"
- tooltip.trigger="axis"，legend.show=true

时间格式：ISO 8601，例如 "2026-05-19T00:00:00+08:00"
用中文回复。
"""

_CLASSIFY_SYSTEM = """你是一个意图分类器，判断用户对日志的操作意图。

意图类型：
- query：查找具体日志、搜索关键词、查看某个时间段的记录
- analyze：分析趋势、统计规律、异常检测、根因分析、"为什么"类问题
- dashboard：生成图表、可视化、柱状图、折线图、饼图、"画图"、"图表"相关请求

只返回一个单词：query、analyze 或 dashboard
"""


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    intent: Optional[str]


def _should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        # 防止 LLM 反复换关键词死循环：统计已发生的工具调用轮数
        # 每个 AIMessage 携带 tool_calls 算一轮，超过 4 轮强制结束让 LLM 基于已有信息总结
        tool_rounds = sum(
            1 for m in state["messages"]
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
        )
        if tool_rounds >= 4:
            return END
        return "tools"
    return END


def build_graph(datasource: LogDataSource) -> StateGraph:
    tools = make_log_tools(datasource)
    settings = get_settings()
    llm = create_llm(settings.llm)
    llm_with_tools = llm.bind_tools(tools)
    classifier_llm = create_llm(settings.llm).with_config({"tags": ["classifier"]})

    async def classify_node(state: AgentState):
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        if not last_human:
            return {"intent": "query"}

        resp = await classifier_llm.ainvoke([
            SystemMessage(content=_CLASSIFY_SYSTEM),
            HumanMessage(content=last_human.content),
        ])
        intent = resp.content.strip().lower()
        if intent not in ("query", "analyze", "dashboard"):
            intent = "query"
        return {"intent": intent}

    async def query_agent(state: AgentState):
        msgs = list(state["messages"])
        if not any(isinstance(m, SystemMessage) for m in msgs):
            now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            msgs = [SystemMessage(content=_QUERY_SYSTEM.format(now=now))] + msgs
        response = await llm_with_tools.ainvoke(msgs)
        return {"messages": [response]}

    async def analysis_agent(state: AgentState):
        msgs = list(state["messages"])
        if not any(isinstance(m, SystemMessage) for m in msgs):
            now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            msgs = [SystemMessage(content=_ANALYSIS_SYSTEM.format(now=now))] + msgs
        response = await llm_with_tools.ainvoke(msgs)
        return {"messages": [response]}

    async def dashboard_agent(state: AgentState):
        msgs = list(state["messages"])
        if not any(isinstance(m, SystemMessage) for m in msgs):
            now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            msgs = [SystemMessage(content=_DASHBOARD_SYSTEM.format(now=now))] + msgs
        response = await llm_with_tools.ainvoke(msgs)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    def route_by_intent(state: AgentState) -> str:
        return state.get("intent") or "query"

    graph = StateGraph(AgentState)
    graph.add_node("classify", classify_node)
    graph.add_node("query_agent", query_agent)
    graph.add_node("analysis_agent", analysis_agent)
    graph.add_node("dashboard_agent", dashboard_agent)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", route_by_intent, {
        "query": "query_agent",
        "analyze": "analysis_agent",
        "dashboard": "dashboard_agent",
    })
    graph.add_conditional_edges("query_agent", _should_continue, {
        "tools": "tools",
        END: END,
    })
    graph.add_conditional_edges("analysis_agent", _should_continue, {
        "tools": "analysis_tools",
        END: END,
    })
    graph.add_conditional_edges("dashboard_agent", _should_continue, {
        "tools": "dashboard_tools",
        END: END,
    })

    analysis_tool_node = ToolNode(tools)
    dashboard_tool_node = ToolNode(tools)
    graph.add_node("analysis_tools", analysis_tool_node)
    graph.add_node("dashboard_tools", dashboard_tool_node)
    graph.add_edge("tools", "query_agent")
    graph.add_edge("analysis_tools", "analysis_agent")
    graph.add_edge("dashboard_tools", "dashboard_agent")

    return graph.compile()
