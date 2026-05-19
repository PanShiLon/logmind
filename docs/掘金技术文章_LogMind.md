# 只需 SSH 权限，5 分钟用自然语言查所有服务器日志 —— LogMind 架构实录

> 不是 Demo，是一个真实接入了生产 ELK 的 AI 日志分析系统的技术复盘。
>
> 技术栈：Python 3.12 + LangGraph + FastAPI + Vue3 + ECharts，Multi-Agent 架构，三种数据源模式无缝切换。

---

## 一、为什么要造这个轮子？

公司有 ELK，Kibana 也能查日志。但现实是——

- **KQL/DSL 有门槛**：运营和测试每次查日志都要找研发写查询语句
- **排障链路长**：出了问题 → 登 Kibana → 选索引 → 写 KQL → 看结果 → 找规律，整个链路 5-10 分钟
- **中小团队更惨**：连 ELK 都没有，日志散落在各台服务器上，排障全靠 SSH + grep

我想做一个工具：**用自然语言问一句话，AI 自动去查日志、聚合统计、画图表、给结论。**

调研了一圈：

| 方案 | 问题 |
|------|------|
| 直接用 ChatGPT / Kimi | 它不认识你的服务器，也连不上你的 ES |
| LangChain + OpenAI Functions | 可以，但太重了。查日志这个场景不需要 Memory、Chain、VectorStore 全家桶 |
| 自己从头写 ReAct | 可控性高，但 StateGraph 和 ToolNode 的轮子没必要自己造 |

最终选择：**LangGraph 做 Agent 编排（状态图 + ReAct 循环），LangChain 只用 Tool 定义和 ChatOpenAI，不引入其他组件。**

轻量、可控、够用。

---

## 二、整体架构

【配图 1：整体架构图。三层：Vue3 前端（SSE 流式 + ECharts）←→ FastAPI + LangGraph Multi-Agent 引擎 ←→ DataSource 抽象层（SSH / Elasticsearch / DuckDB）】

```
┌─────────────────────────────────────────────────────┐
│                  Vue3 + ECharts 前端                  │
│  SSE 流式渲染 │ Markdown │ 图表 │ 会话管理 │ 配置页   │
└──────────────────────┬──────────────────────────────┘
                       │ SSE (POST /api/chat)
┌──────────────────────▼──────────────────────────────┐
│              FastAPI + LangGraph 引擎                 │
│                                                       │
│  ┌──────────┐    ┌──────────────────────────────┐    │
│  │ Classify │───▶│  Query / Analysis / Dashboard │    │
│  │  Node    │    │         Agent Nodes           │    │
│  └──────────┘    └──────────┬───────────────────┘    │
│                             │ ReAct Loop              │
│                  ┌──────────▼───────────────┐         │
│                  │  7 个 LangChain Tools     │         │
│                  │  (search / count / trend) │         │
│                  └──────────┬───────────────┘         │
│                             │                         │
│              ┌──────────────▼──────────────┐          │
│              │   DataSource 抽象层 (ABC)    │          │
│              │  SSH │ Elasticsearch │ DuckDB │          │
│              └─────────────────────────────┘          │
└───────────────────────────────────────────────────────┘
```

核心设计原则：**一套 Agent 逻辑，三种数据源，只改一行配置切换。**

---

## 三、Multi-Agent：LangGraph 状态图

LogMind 不是一个单 Agent 系统。用户的意图至少有三种：

- **查询**："支付服务今天有没有报错？" → 需要查日志、返回原文
- **分析**："分析一下最近的错误趋势" → 需要聚合、总结、给结论
- **可视化**："画一张过去 7 天的错误趋势图" → 需要生成 ECharts 配置

一个 Agent 用一套 System Prompt 处理所有意图，效果很差——查询类 prompt 和分析类 prompt 的要求完全不同。

### 3.1 解法：Classify → 三路 Agent

```python
graph = StateGraph(AgentState)

# 1. 入口：classify 节点，轻量 LLM 调用，只返回一个词
graph.add_node("classify", classify_node)

# 2. 三个 Agent，各自独立的 System Prompt 和 ToolNode
graph.add_node("query_agent", query_agent)
graph.add_node("analysis_agent", analysis_agent)
graph.add_node("dashboard_agent", dashboard_agent)

# 3. 各自的 ToolNode（ReAct 循环回边）
graph.add_node("tools", tool_node)
graph.add_node("analysis_tools", analysis_tool_node)
graph.add_node("dashboard_tools", dashboard_tool_node)

# 4. 路由
graph.set_entry_point("classify")
graph.add_conditional_edges("classify", route_by_intent, {
    "query": "query_agent",
    "analyze": "analysis_agent",
    "dashboard": "dashboard_agent",
})

# 5. 每个 Agent 的 ReAct 循环
graph.add_conditional_edges("query_agent", _should_continue, {
    "tools": "tools", END: END
})
graph.add_edge("tools", "query_agent")  # 工具执行完回到 Agent
```

【配图 2：LangGraph 状态图。classify 节点 → 三路条件分支 → 各自 Agent ←→ ToolNode 循环 → END】

### 3.2 为什么三个 Agent 各自有独立的 ToolNode？

最初我把三个 Agent 共用一个 `ToolNode`，回边统一指向 `query_agent`。结果 analysis_agent 调用 Tool 后，控制流跳到了 query_agent，上下文全乱了。

**LangGraph 的回边决定了 Tool 执行后回到哪个节点。** 三个 Agent 必须各自有独立的 ToolNode 和回边，才能形成正确的 ReAct 循环：

```
query_agent ←→ tools
analysis_agent ←→ analysis_tools
dashboard_agent ←→ dashboard_tools
```

这个 bug 花了半天才定位——日志看不出来，因为 Tool 确实执行了，但结果被送到了错误的 Agent。

### 3.3 Classify 节点的设计

Classify 节点不绑定任何 Tool，只做一件事：判断用户意图。

```python
_CLASSIFY_SYSTEM = """你是意图分类器。根据用户的最新消息，返回且只返回以下之一：
- query    : 查询日志原文、搜索错误、查看具体日志
- analyze  : 分析错误趋势、统计分布、给出结论
- dashboard: 需要图表、可视化、画图

只输出一个单词。"""
```

成本极低（输入 ~100 tokens，输出 1 token），但把后续 Agent 的 Prompt 复杂度降低了 60%——每个 Agent 只需要关心自己领域的指令。

---

## 四、DataSource 抽象层：一套接口，三种实现

这是 LogMind 最核心的设计决策：**Agent 和 Tool 不应该关心日志从哪来。**

### 4.1 ABC 定义

```python
@dataclass
class LogEntry:
    timestamp: Optional[datetime]
    level: str       # ERROR / WARN / INFO / DEBUG / UNKNOWN
    message: str
    source: str      # 来源服务器或索引名
    raw: str         # 原始行文本

class LogDataSource(ABC):
    @abstractmethod
    async def search(self, query, level, start_time, end_time, 
                     limit, servers) -> SearchResult: ...
    
    @abstractmethod
    async def aggregate(self, field, query, 
                        start_time, end_time) -> Dict[str, int]: ...
    
    @abstractmethod
    async def time_series(self, interval, query, level, 
                          start_time, end_time) -> List[Dict]: ...
    
    async def health_check(self) -> Dict[str, Any]:
        return {"status": "ok", "datasource": self.__class__.__name__}
```

三个方法覆盖所有日志分析场景：`search`（全文搜索）、`aggregate`（聚合统计）、`time_series`（时序趋势）。

### 4.2 SSH 实现：零基础设施，grep 就够了

```python
class SSHDataSource(LogDataSource):
    async def search(self, query, level, start_time, end_time, 
                     limit, servers):
        tasks = []
        for server in self._servers:
            for path in server.log_paths:
                tasks.append(self._grep_remote(server, path, query, level))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # 合并、排序、截断
        return SearchResult(entries=merged[:limit], total=len(merged))
    
    async def _grep_remote(self, server, path, query, level):
        async with asyncssh.connect(host=server.host, ...) as conn:
            cmd = f"grep -E '{pattern}' {path} | tail -n 500"
            result = await conn.run(cmd, check=False)
            return self._parse_lines(result.stdout, server.name)
```

**亮点**：`asyncio.gather` 并发连接多台服务器，不拉全量日志，在远端用 grep 过滤后只传回匹配行。5 台服务器并发查询，耗时和查 1 台几乎一样。

`aggregate` 和 `time_series` 没有原生能力？没关系——在 Python 内存里对 search 结果做二次聚合。日志量不大时完全够用。

### 4.3 Elasticsearch 实现：原生聚合，性能无上限

```python
class ESDataSource(LogDataSource):
    async def search(self, query, **kwargs):
        body = {"query": {"bool": {"must": filters}}}
        # keyword 字段用 wildcard，text 字段用 match
        if query:
            filters.append({
                "wildcard": {"app.message": {
                    "value": f"*{query}*", 
                    "case_insensitive": True
                }}
            })
        resp = await self._es.search(index=self._index, body=body)
        return self._parse_hits(resp)
    
    async def aggregate(self, field, **kwargs):
        # 直接用 ES terms 聚合，性能比 SSH 模式快 100 倍
        body = {"size": 0, "aggs": {
            "result": {"terms": {"field": self._field_map[field]}}
        }}
        resp = await self._es.search(index=self._index, body=body)
        return {b["key"]: b["doc_count"] for b in buckets}
    
    async def time_series(self, interval, **kwargs):
        # date_histogram 聚合
        body = {"size": 0, "aggs": {
            "ts": {"date_histogram": {
                "field": "@timestamp", 
                "calendar_interval": interval
            }}
        }}
```

### 4.4 工厂：match-case 一行切换

```python
def create_datasource(settings: Settings) -> LogDataSource:
    match settings.datasource.type:
        case "ssh":
            from .ssh import SSHDataSource
            return SSHDataSource(settings.servers)
        case "elasticsearch" | "es":
            from .es import ESDataSource
            return ESDataSource(settings.datasource)
        case "duckdb":
            from .duckdb import DuckDBDataSource
            return DuckDBDataSource(settings.datasource)
```

延迟导入——没装 `elasticsearch` 包也能跑 SSH 模式，不会启动就报错。

**用户只需要改 `config.yaml` 里的一行：**

```yaml
datasource:
  type: ssh    # 改为 elasticsearch 或 duckdb 即可切换
```

---

## 五、Tool 层：闭包注入，干净解耦

### 5.1 7 个 Tool

| Tool | 用途 | 底层调用 |
|------|------|----------|
| `search_logs` | 关键词搜索日志 | `datasource.search()` |
| `count_errors` | 各级别日志数量 | `datasource.aggregate(field="level")` |
| `get_error_trend` | 时序趋势（ASCII 柱状图） | `datasource.time_series()` |
| `analyze_exception` | 深入分析某异常 | `datasource.search()` |
| `health_check` | 数据源连通性检查 | `datasource.health_check()` |
| `get_service_error_stats` | 各服务错误数（JSON） | `datasource.aggregate()` |
| `get_time_series_chart` | 时序数据（JSON） | `datasource.time_series()` |

### 5.2 闭包注入 DataSource

Tool 怎么拿到 datasource 实例？不用全局变量，不用依赖注入框架——**闭包**。

```python
def make_log_tools(datasource: LogDataSource) -> list:
    
    @tool
    async def search_logs(query: str = "", level: str = "", 
                          start_time: str = "", end_time: str = "",
                          limit: int = 20) -> str:
        """搜索日志，支持关键词、级别、时间范围过滤"""
        result = await datasource.search(
            query=query, level=level,
            start_time=start_time, end_time=end_time, limit=limit
        )
        return format_search_result(result)
    
    @tool
    async def count_errors(...) -> str:
        counts = await datasource.aggregate(field="level", ...)
        return json.dumps(counts, ensure_ascii=False)
    
    # ... 其他 5 个 Tool
    
    return [search_logs, count_errors, get_error_trend, 
            analyze_exception, health_check,
            get_service_error_stats, get_time_series_chart]
```

构建 Graph 时，一行注入：

```python
ds = create_datasource(settings)
tools = make_log_tools(ds)
llm_with_tools = llm.bind_tools(tools)
```

Tool 内部通过闭包捕获 `datasource`，不需要任何框架层面的 DI。切换数据源时，只需要换一个 `datasource` 实例，所有 Tool 自动切换底层实现。

---

## 六、SSE 流式输出：让 AI 回复"像打字一样"

### 6.1 后端：LangGraph astream_events

```python
@router.post("/api/chat")
async def chat(req: ChatRequest):
    return StreamingResponse(
        _stream_generator(req.message, req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

`astream_events` 是 LangGraph 的事件流 API，可以监听图执行过程中的每一个事件：

```python
async for event in graph.astream_events(state, version="v1"):
    kind = event["event"]

    if kind == "on_chain_end" and name == "classify":
        # 意图识别完成
        yield f"data: {json.dumps({'type': 'intent', 'intent': intent})}\n\n"

    elif kind == "on_tool_start":
        yield f"data: {json.dumps({'type': 'tool_start', 'tool': name})}\n\n"

    elif kind == "on_chat_model_stream":
        # ⚠️ 关键：过滤掉 classify 节点的 token
        if event["metadata"]["langgraph_node"] == "classify":
            continue
        chunk = event["data"]["chunk"]
        if chunk.content:
            yield f"data: {json.dumps({'type': 'text', 'content': chunk.content})}\n\n"
```

**SSE 消息协议：**

| 类型 | 时机 | 前端行为 |
|------|------|----------|
| `intent` | classify 完成 | 显示"正在查询..."/"正在分析..." |
| `tool_start` | Tool 开始执行 | 显示"正在搜索日志..." |
| `tool_end` | Tool 执行完毕 | 标记工具调用完成 |
| `text` | LLM 输出 token | 逐字追加到气泡，实时解析 Markdown |
| `done` | 流结束 | 显示追问建议 |

### 6.2 前端：fetch + ReadableStream

为什么不用 `EventSource`？因为 EventSource 只支持 GET，而我们需要 POST 发送 `session_id` 和 `message`。

```javascript
const resp = await fetch('/api/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message: msg, session_id: currentSessionId.value }),
})

const reader = resp.body.getReader()
const decoder = new TextDecoder()
let buf = ''

while (true) {
  const { done, value } = await reader.read()
  if (done) break
  buf += decoder.decode(value, { stream: true })

  const parts = buf.split('\n\n')
  buf = parts.pop()  // 未完成的帧留在缓冲区

  for (const part of parts) {
    if (!part.trim().startsWith('data:')) continue
    const evt = JSON.parse(part.trim().slice(5))

    if (evt.type === 'text') {
      aiMsg.content += evt.content
      // 实时提取图表配置
      aiMsg.charts = extractCharts(aiMsg.content)
    }
  }
}
```

`stream: true` 参数确保 TextDecoder 正确处理 UTF-8 多字节字符的边界切割——不加这个参数，中文字符被截断时会解码成乱码。

### 6.3 踩坑：classify 节点的 token 会混入正文

classify 节点也是 LLM 调用，它输出的 `query`/`analyze`/`dashboard` 这几个字也会触发 `on_chat_model_stream` 事件。如果不过滤，用户会看到 AI 回复里莫名其妙地出现一个 `query` 字。

解决：通过 `event.metadata.langgraph_node` 判断事件来源，classify 节点的 token 全部跳过。

```python
if event.get("metadata", {}).get("langgraph_node") == "classify":
    continue
```

这个问题很隐蔽——开发时用非流式模式测试不会暴露，只有用 SSE 流式输出时才会发现。

---

## 七、Dashboard Agent：让 AI 直接生成 ECharts 图表

### 7.1 协议设计

Dashboard Agent 的 System Prompt 里有一条特殊指令：

```
当需要展示图表时，在你的回复中嵌入以下格式：
<chart_config>
{标准 ECharts option JSON}
</chart_config>
```

AI 的回复文本中会夹带 `<chart_config>` 标签，前端正则提取后直接喂给 ECharts：

```javascript
function extractCharts(text) {
  const charts = []
  const re = /<chart_config>([\s\S]*?)<\/chart_config>/g
  let m
  while ((m = re.exec(text)) !== null) {
    try { charts.push(JSON.parse(m[1].trim())) } 
    catch { /* 容错 AI 输出格式不稳定 */ }
  }
  return charts
}
```

### 7.2 渲染：vue-echarts 按需引入

```javascript
// ChartWidget.vue
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart } from 'echarts/charts'

use([CanvasRenderer, BarChart, LineChart, PieChart,
     GridComponent, TooltipComponent, LegendComponent])
```

只引入 Bar/Line/Pie 三种图表类型，打包体积比全量引入减少 60%+。

### 7.3 Markdown 和图表分区渲染

AI 回复同时包含文字和图表配置，需要分开渲染：

```javascript
// 文字部分：去掉 chart_config 标签后，用 marked.js 渲染
function renderText(text) {
  const stripped = text.replace(/<chart_config>[\s\S]*?<\/chart_config>/g, '').trim()
  return marked.parse(stripped)
}
```

模板里文字和图表各占一个区域：

```html
<div class="text-section" v-html="renderText(msg.content)"></div>
<div class="chart-section" v-for="chart in msg.charts">
  <ChartWidget :option="chart" />
</div>
```

图表在流式过程中实时出现——每次收到 `text` 事件都重新调用 `extractCharts`，一旦 `<chart_config>` 标签闭合，图表立即渲染。

---

## 八、LLM 工厂：所有国产模型都兼容 OpenAI 接口

```python
_PROVIDER_DEFAULTS = {
    "openai": "https://api.openai.com/v1",
    "kimi":   "https://api.moonshot.cn/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen":  "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}

def create_llm(config: LLMConfig, streaming: bool = False) -> ChatOpenAI:
    base_url = config.base_url or _PROVIDER_DEFAULTS.get(config.provider)
    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=base_url,
        streaming=streaming,
        temperature=0.1,
    )
```

**一个 `ChatOpenAI` 类打天下。** Kimi、DeepSeek、通义千问、智谱 GLM 都兼容 OpenAI Chat Completions 接口格式，只需要换 `base_url` 和 `model`。

配置文件里改一行就切换模型：

```yaml
llm:
  provider: kimi          # 改成 deepseek / qwen / openai
  api_key: sk-xxxx
  model: kimi-k2-0711-preview
```

---

## 九、配置热更新：GUI 替代 config.yaml

### 9.1 痛点

`config.yaml` 手写容易出错，K8s 环境下 ES 的端口转发步骤繁琐，对不懂运维的开发者是巨大的卡点。

### 9.2 方案

做了一个 GUI 配置页，三个 Tab（SSH / Elasticsearch / DuckDB）+ LLM 配置区。

**核心交互：「测试连接」按钮**

```python
@router.post("/test-connection/elasticsearch")
async def test_es(req: ESTestRequest):
    es_client = AsyncElasticsearch(
        hosts=req.hosts,
        basic_auth=(req.username, req.password) if (req.username and req.password) else None,
        verify_certs=req.verify_certs,
    )
    try:
        resp = await es_client.count(index=req.index)
        count = resp.get("count", 0)
        return {"ok": True, "message": f"ES 连接成功，索引 {req.index} 共 {count:,} 条日志"}
    except Exception:
        await es_client.ping()
        return {"ok": True, "message": f"ES 连接成功（索引查询受限，但连接正常）"}
    finally:
        await es_client.close()
```

ES 测试通过后自动加载数据预览面板：总日志量、ERROR 数、各服务文档分布（Top 20 + 进度条）。

**保存时前端自动序列化为 YAML → PUT /api/config → 后端 reload_settings()。**

---

## 十、8 个踩坑实录

### 坑 1：macOS Python + libexpat 符号找不到

```
ImportError: symbol not found '_XML_SetAllocTrackerActivationThreshold'
```

macOS 系统自带旧版 libexpat，Homebrew Python 编译时链接了新版，运行时找到旧版，符号不存在。

**解决**：`brew install expat`，所有命令前加 `DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib`。

### 坑 2：LangChain 0.2 + Python 3.12 = pydantic v1 崩溃

```
TypeError: ForwardRef._evaluate() missing 'recursive_guard'
```

pydantic v1 不兼容 Python 3.12。**必须升级到 LangChain 0.3.x + pydantic v2。**

验证通过的版本组合：`langchain==0.3.7 + langchain-openai==0.2.9 + langgraph==0.2.45 + pydantic==2.9.2`

### 坑 3：AI 不知道"今天"是哪天

用户问"查一下今天的 ERROR"，AI 传给 Tool 的 `start_time` 是 `2024-12-19`——这是训练数据里的日期。

**解决**：System Prompt 里注入当前时间：

```python
now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
system_msg = _SYSTEM_PROMPT.format(now=now)
```

**任何依赖当前时间的 Agent，System Prompt 必须显式注入 `now`。**

### 坑 4：ES 字段嵌套，查询全返回空

代码里写 `{"term": {"level": "ERROR"}}`，但实际 ES 的字段结构是 `app.level`。

不同 ELK 部署的字段结构不同。**接入新环境前，先 `curl ES/_search?size=1` 看一条原始数据的实际结构。**

### 坑 5：`app.message` 是 keyword 类型，`match` 查不到

Kibana 能搜到，代码里搜不到。因为 `app.message` 是 `keyword` 类型，`match` 要求精确匹配整个字段值。

**解决**：改用 `wildcard` 查询：

```python
{"wildcard": {"app.message": {"value": f"*{query}*", "case_insensitive": True}}}
```

### 坑 6：`health_check` 用 `es.info()` 需要 cluster 权限

只读日志账号没有 cluster monitor 权限，`es.info()` 报 403，AI 误判"数据源有问题"。

**解决**：改用 `es.count(index=self._index)`，只需索引级 read 权限。

**教训：health_check 的权限要求必须 ≤ 正常查询的权限要求。**

### 坑 7：`elasticsearch-py` 8.x `http_auth` 改名了

7.x 用 `http_auth=(user, pass)`，8.x 改为 `basic_auth=(user, pass)`。而且如果 password 是 `None`，会报 `sequence item 1: expected str instance, NoneType found`。

**解决**：`basic_auth=(u, p) if (u and p) else None`

### 坑 8：classify 节点的 token 混入正文流

分类器输出的 `query`/`analyze` 字样会通过 `on_chat_model_stream` 事件推到前端，用户看到 AI 回复里莫名多了一个 `query`。

**解决**：`event.metadata.langgraph_node == "classify"` 过滤。非流式模式测试不出来，只有 SSE 流式输出才会暴露。

---

## 十一、前端：Vue3 + 极简依赖

| 包 | 用途 |
|----|------|
| vue 3.5 | 框架 |
| vue-router 4.6 | 路由（仅 2 个页面：Chat / Config） |
| echarts 6 + vue-echarts 8 | 图表渲染 |
| marked 18 + highlight.js 11 | Markdown + 代码高亮 |
| element-plus | 只用了 textarea 和 button |

**主题切换**：CSS 变量 + `data-theme` attribute + localStorage 持久化，零 JS 框架依赖。

**会话管理**：左侧边栏显示历史会话列表，支持新建 / 切换 / 删除 / 结束 / 继续。后端 SQLite 存储，`aiosqlite` 全异步，`ON DELETE CASCADE` 删会话自动清消息。

**日志导出**：CSV（BOM UTF-8）和 Markdown 两种格式一键导出。

---

## 十二、效果与数据

接入公司生产 ELK 后的实际数据：

| 指标 | 数据 |
|------|------|
| 索引 | `.ds-springboot-log-*` |
| 日总量 | ~104 万条 |
| 日 ERROR 量 | ~677 条 |
| 查询响应 | SSH 模式 2-4s / ES 模式 <1s |
| 首 Token 延迟 | SSE 模式 <200ms |

**三种模式无缝升级**：SSH → DuckDB → Elasticsearch，不换工具，只改一行配置。

---

## 十三、项目地址

GitHub：[github.com/PanShiLon/logmind](https://github.com/PanShiLon/logmind)

MIT 协议开源。Star 支持一下，有问题欢迎提 Issue。

---

## 总结

做一个生产可用的 AI 日志分析工具，关键不在于框架多新、模型多大，而在于：

1. **DataSource 抽象要干净** —— 一套 Agent 逻辑适配所有数据源，才能真正零门槛
2. **Multi-Agent 要简单** —— classify 节点成本极低，但能让每个 Agent 的 Prompt 质量提升一个量级
3. **SSE 流式必须做** —— 200ms 看到"正在思考..."和 5 秒白屏，是两种完全不同的产品体验
4. **接入真实环境再说** —— Demo 能跑 ≠ 生产能用，ES 字段映射、权限模型、时间注入，每一个都是坑

如果你也在做 AI + DevOps 方向的工具，欢迎交流。
