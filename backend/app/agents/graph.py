from typing import TypedDict, Annotated, Sequence, Optional
import operator

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from ..core.datasource.base import LogDataSource
from ..core.llm_factory import create_llm
from ..core.settings import get_settings
from ..tools.log_tools import make_log_tools

SYSTEM_PROMPT = """你是 LogMind，一个专业的 AI 日志分析助手。

你的职责：
1. 帮助用户搜索、分析和理解服务器日志
2. 识别错误模式、异常趋势、性能问题
3. 给出清晰的根因分析和修复建议

工作原则：
- 优先使用工具获取真实数据，不要凭空猜测
- 分析时注意时间维度（问题是什么时候开始的？趋势如何？）
- 给出具体可操作的建议，而不是泛泛而谈
- 用中文回复，保持专业但易于理解

可用工具：
- search_logs: 按关键词、级别、时间范围搜索日志
- count_errors: 统计各级别日志数量
- get_error_trend: 查看错误趋势（是否在加剧）
- analyze_exception: 深入分析特定异常
- health_check: 检查数据源连通性
"""


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


def _should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


def build_graph(datasource: LogDataSource) -> StateGraph:
    tools = make_log_tools(datasource)
    settings = get_settings()
    llm = create_llm(settings.llm).bind_tools(tools)

    async def agent_node(state: AgentState):
        msgs = list(state["messages"])
        if not any(isinstance(m, SystemMessage) for m in msgs):
            msgs = [SystemMessage(content=SYSTEM_PROMPT)] + msgs
        response = await llm.ainvoke(msgs)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()
