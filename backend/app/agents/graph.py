from typing import TypedDict, Annotated, Sequence, Optional, Literal
import operator

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from ..core.datasource.base import LogDataSource
from ..core.llm_factory import create_llm
from ..core.settings import get_settings
from ..tools.log_tools import make_log_tools

_QUERY_SYSTEM = """你是 LogMind，一个专业的 AI 日志查询助手。

职责：帮助用户搜索、定位具体日志内容。

原则：
- 优先使用 search_logs 工具获取真实数据，不要凭空猜测
- 返回结果要整理成可读格式，突出关键信息
- 时间范围不明确时默认查最近1小时
- 用中文回复

可用工具：search_logs / count_errors / health_check
"""

_ANALYSIS_SYSTEM = """你是 LogMind，一个专业的 AI 日志分析助手。

职责：发现异常规律、分析错误趋势、给出根因诊断。

分析流程：
1. 先用 get_error_trend 拿时序数据，判断问题是否在加剧
2. 再用 count_errors 看错误分布
3. 用 analyze_exception 深入分析具体异常
4. 综合给出诊断结论

输出结构：
- **结论**（一句话）
- **数据支撑**（关键数字）
- **可能原因**（1-3条）
- **建议排查方向**

用中文回复，保持专业但易于理解。
"""

_CLASSIFY_SYSTEM = """你是一个意图分类器，判断用户对日志的操作意图。

意图类型：
- query：查找具体日志、搜索关键词、查看某个时间段的记录
- analyze：分析趋势、统计规律、异常检测、根因分析、"为什么"类问题

只返回一个单词：query 或 analyze
"""


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    intent: Optional[str]


def _should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
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
        if intent not in ("query", "analyze"):
            intent = "query"
        return {"intent": intent}

    async def query_agent(state: AgentState):
        msgs = list(state["messages"])
        if not any(isinstance(m, SystemMessage) for m in msgs):
            msgs = [SystemMessage(content=_QUERY_SYSTEM)] + msgs
        response = await llm_with_tools.ainvoke(msgs)
        return {"messages": [response]}

    async def analysis_agent(state: AgentState):
        msgs = list(state["messages"])
        if not any(isinstance(m, SystemMessage) for m in msgs):
            msgs = [SystemMessage(content=_ANALYSIS_SYSTEM)] + msgs
        response = await llm_with_tools.ainvoke(msgs)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    def route_by_intent(state: AgentState) -> str:
        return state.get("intent") or "query"

    graph = StateGraph(AgentState)
    graph.add_node("classify", classify_node)
    graph.add_node("query_agent", query_agent)
    graph.add_node("analysis_agent", analysis_agent)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", route_by_intent, {
        "query": "query_agent",
        "analyze": "analysis_agent",
    })
    graph.add_conditional_edges("query_agent", _should_continue, {
        "tools": "tools",
        END: END,
    })
    graph.add_conditional_edges("analysis_agent", _should_continue, {
        "tools": "analysis_tools",
        END: END,
    })

    analysis_tool_node = ToolNode(tools)
    graph.add_node("analysis_tools", analysis_tool_node)
    graph.add_edge("tools", "query_agent")
    graph.add_edge("analysis_tools", "analysis_agent")

    return graph.compile()
