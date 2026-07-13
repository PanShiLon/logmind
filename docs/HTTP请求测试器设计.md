# HTTP 请求测试器（HttpTester）设计文档

> 状态：✅ 已实施并验收通过（2026-07-13）
> 创建：2026-07-13
> 定位：在 LogMind 内一站式发 HTTP 请求（类 curl / Apifox）并美观展示响应，
> 免去「终端 curl 看返回 ↔ LogMind 查日志」两平台来回切。

## 1. 背景与目标

验收对外 OpenAPI（如物流查询）时，需要一边在终端跑 curl 看返回、一边在 LogMind 查日志。
本功能把「发测试请求 + 看格式化响应」搬进 LogMind，与现有「日志直查 / AI 分析」并列为第三个独立能力。

**典型用法**：粘一条 curl 命令，或填 method / url / headers / body → 发送 →
展示状态码（彩色徽章）+ 响应头（表格）+ 格式化高亮的 JSON body。

**验收用例**（实施完成后用这条验证）：

```
GET http://localhost:3002/openapi/v1/logistics/tracking?billNo=271878354
Header: Authorization: Bearer sk_...（seed 出的测试 Key）
```

期望：`status=tracking` + 船名 `DAMIETTA EXPRESS` 等完整 JSON，2xx 绿色徽章。
依赖 bi-backend(:3002) + scm-ai-service(:3004 + gRPC:50051) 在运行；
Key 失效则重跑 `apps/bi-backend/prisma/seed-openapi-testkey.ts` 拿新 Key。

## 2. 为什么走后端代理（CORS 评估）

浏览器直接 fetch 目标 OpenAPI 会撞 CORS —— 目标服务不会给 LogMind 前端放行。
**走 FastAPI 后端代理是正确且唯一干净的方案**：

```
前端(HttpTesterView) ──{method,url,headers,body}──► LogMind 后端 /api/http/send
                                                        │ httpx 转发
                                                        ▼
                                                  目标服务(任意 URL)
前端 ◄──{status,headers,body,elapsed_ms,size}── LogMind 后端
```

附带好处：后端能拿到目标返回的**真实响应头和状态码**（浏览器 fetch 对跨域响应头有可见性限制，
服务端代理没有此限制），展示更完整。

**curl 解析放前端**：纯 JS 字符串解析成 `{method,url,headers,body}`，不碰后端 shell，零注入风险。
后端只认结构化入参。

## 3. 安全设计（SSRF）

本功能可向任意地址发请求，是典型 SSRF 面。分层防护：

1. **只绑本地**：后端以 `uvicorn --host 127.0.0.1` 启动，不暴露公网/局域网。第一道也是最重要一道。
2. **元数据地址黑名单**：转发前解析目标 host，硬拒 `169.254.169.254`（云元数据）、`0.0.0.0` 等。
   内网地址（`127.*` / `10.*` / `192.168.*`）**默认放行** —— 验收目标正是本地/内网 OpenAPI，一刀切禁内网功能就废了。
3. **白名单可控**（已实施，做成页面 UI 开关）：`enabled` 开关 + `allow_hosts` 白名单，
   经页面右上「⚙ 设置抽屉」增删，保存即生效。
   - `allow_hosts` 为空 = 只走黑名单（宽松，本地默认）。
   - `allow_hosts` 填了 = 只放行列表内 host（严格，仅放行验收目标域名）。
   - **状态存 sidecar**：写 `backend/http_tester_state.json`（config.yaml 旁），**不回写 config.yaml**
     —— config.yaml 里有大段注释掉的数据源示例，yaml 程序化回写会抹掉注释。
     `settings.py` 加载时用 sidecar 覆盖 config.yaml 里的 http_tester 值。文件已 gitignore。
4. **不透传敏感头到日志**：后端不落盘、不打印 Authorization 等头值。
5. 页面顶部 `⚠️ 仅本地开发 · 白名单N项` 状态徽章（禁用时变红 `⛔ 已禁用`），点击即开设置抽屉；
   与直查页 `🔒 不经过 AI` badge 风格一致。

## 4. 涉及文件

### 后端

| 文件 | 动作 | 说明 |
|---|---|---|
| `backend/app/api/http_tester.py` | 新增 | router：`POST /api/http/send`（转发 + SSRF 校验）+ `GET/PUT /api/http/config`（读写白名单/开关）。 |
| `backend/main.py` | 改 | `app.include_router(http_tester.router)` 一行。 |
| `backend/app/core/settings.py` | 改 | 加 `HttpTesterConfig`；加载时用 sidecar（`http_tester_state.json`）覆盖 http_tester 值。 |
| `backend/http_tester_state.json` | 运行时生成 | 白名单/开关状态，UI 写入，已 gitignore。 |
| `.gitignore` | 改 | 忽略 `backend/http_tester_state.json`。 |

### 前端

| 文件 | 动作 | 说明 |
|---|---|---|
| `frontend/src/views/HttpTesterView.vue` | 新增 | 主页面。Postman 式布局：URL 栏 + 请求卡片（Params/Headers/Body 分页签，Params↔URL 双向同步）+ 响应卡片（大号状态码徽章、耗时/大小、Body/Headers 分页签、**JSON 可折叠树 + 行号**、响应头键值行）+ curl 弹层 + 设置抽屉 + 请求历史。 |
| `frontend/src/utils/parseCurl.js` | 新增 | curl 命令串 → `{method,url,headers,body}`。 |
| `frontend/src/router/index.js` | 改 | 加 `/http` 路由。 |
| ExplorerView / ChatView / ConfigView 的 nav | 改 | 各补一个 `🛰️ 接口测试` 链接，保持三页导航一致。 |

> 复用现有依赖，无需装新包：后端 `httpx` 已用于 loki/config；前端 `highlight.js@11` 已在依赖内。

## 5. 分步实施（已完成）

1. ✅ **后端代理接口**：`http_tester.py`，httpx 转发 + SSRF 黑名单校验 + 结构化返回；`main.py` 注册。
2. ✅ **配置开关 + 白名单**：`settings.py` 加 `HttpTesterConfig` + sidecar 覆盖；`GET/PUT /api/http/config`。
3. ✅ **前端页面骨架**：`HttpTesterView.vue` + 路由 + 导航链接。
4. ✅ **响应美化**：状态码上色、耗时/大小、响应头键值化、JSON 可折叠树 + 行号（非 JSON 走 hljs 行号视图）。
5. ✅ **curl 解析**：`parseCurl.js` + 页面「📋 curl」入口。
6. ✅ **联调验收**：物流 OpenAPI 用例经代理 200 + `status=tracking` + `DAMIETTA EXPRESS`，与终端 curl 一致。
7. ✅ **UI 迭代**：白名单/开关设置抽屉、Params↔URL 同步、请求历史、骨架屏、JSON 折叠。

## 6. 架构一致性

- 沿用现有 router 注册模式（`APIRouter(prefix=...)` + Pydantic 模型 + `include_router`）。
- 与「日志直查 / AI 分析」**解耦**：独立页面、独立后端接口，不复用数据源抽象（DataSource 是日志专用，HTTP 测试与之无关）。
- 前端同源代理（vite `/api` → `:8000`），前端调后端无 CORS 问题。

## 7. 更新记录

- 2026-07-13：初稿，设计确认（含 SSRF 白名单方案）。
- 2026-07-13：实施完成并验收通过；UI 迭代（设置抽屉 + JSON 可折叠树 + 请求历史等）。
```
