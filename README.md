# LogMind — AI 日志分析平台

> 只需要 SSH 权限，5分钟内用自然语言查所有服务器的日志。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)
[![GitHub Stars](https://img.shields.io/github/stars/panshilong/logmind?style=social)](https://github.com/panshilong/logmind)

<!--
  GIF-1（Phase 2 录制后替换）：
  SSH 零配置上手 — 填写 config.yaml → docker compose up → 浏览器输入自然语言 → 日志出现
  GIF-2：跨服务器聚合分析 — "过去1小时哪台服务器报错最多" → AI 并发查询 → 排名图表
  GIF-3：一键切换模式 — 改一行 config → 同样的问题从 ES 返回
-->

> 📌 **动图演示**：前端完成后更新（Phase 2）

---

## 特性

- **SSH 直连模式** ⭐：只需服务器账号密码，零基础设施依赖，5分钟上手
- **Native 模式**：内置 DuckDB 存储 + 日志采集器，替代 ELK 全套
- **Bridge 模式**：已有 Elasticsearch 直接接入，AI 替你写 DSL
- **三模式共用一套 AI**：只改一行 `datasource.type`，Agent 逻辑不变
- **Multi-Agent 架构**：LangGraph 驱动，意图分类 → 查询/分析/看板自动路由
- **多 LLM 支持**：Kimi / DeepSeek / Qwen / OpenAI，改一行配置切换
- **错误根因分析**：不只是搜索，自动分析堆栈、趋势、给出修复建议
- **桌面应用**：Windows + Mac 安装包，无需命令行（Phase 5）
- **IDEA 插件**：IDE 内直接分析异常堆栈（Phase 6）

---

## 快速开始

### 方式一：Docker（推荐）

```bash
git clone https://github.com/panshilong/logmind.git
cd logmind
cp backend/config.example.yaml backend/config.yaml
# 编辑 config.yaml，填入 SSH 信息和 LLM API Key
docker compose up
```

访问 `http://localhost:8000/docs` 查看 API 文档。

### 方式二：本地运行

```bash
git clone https://github.com/panshilong/logmind.git
cd logmind/backend
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入 SSH 信息和 LLM API Key
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

---

## 配置示例（SSH 直连模式，最简单）

```yaml
datasource:
  type: ssh          # 改为 duckdb 或 elasticsearch 即可切换模式

llm:
  provider: kimi
  api_key: sk-xxxx
  model: moonshot-v1-8k
  base_url: https://api.moonshot.cn/v1

servers:
  - name: 支付服务
    host: 192.168.1.10
    username: deploy
    password: xxxx
    log_paths:
      - /var/log/payment/app.log
      - /var/log/payment/error.log
  - name: 订单服务
    host: 192.168.1.11
    username: deploy
    password: xxxx
    log_paths:
      - /var/log/order/*.log     # 支持通配符
```

你可以直接问：

- `"支付服务今天有没有报错？"`
- `"过去1小时 NullPointerException 出现了多少次？"`
- `"所有服务里 ERROR 最多的是哪个？"`（跨多台服务器并发查询）

---

## 支持的数据源

| 类型 | `datasource.type` | 说明 | 前置条件 |
|------|-------------------|------|---------|
| SSH 直连 ⭐ | `ssh` | 零基础设施，推荐新手 | SSH 账号密码 |
| 本地存储 | `duckdb` | 内置采集器，支持历史查询 | 无 |
| Elasticsearch | `elasticsearch` | 已有 ELK 直接接入 | ES 地址 |
| SkyWalking | `skywalking` | APM + Trace 数据（Phase 4） | OAP Server 地址 |

三种模式可以无缝升级：SSH → DuckDB → ES，**不用换工具，只改一行配置**。

---

## 支持的 LLM

| 提供商 | `provider` | 获取 Key |
|--------|-----------|---------|
| 月之暗面 Kimi | `kimi` | platform.moonshot.cn |
| DeepSeek | `deepseek` | platform.deepseek.com |
| 通义千问 | `qwen` | dashscope.aliyuncs.com |
| OpenAI | `openai` | platform.openai.com |
| 智谱 GLM | `zhipu` | open.bigmodel.cn |

---

## 项目结构

```
logmind/
├── backend/
│   ├── app/
│   │   ├── core/datasource/   # DataSource 抽象层（SSH/DuckDB/ES）
│   │   ├── tools/             # LangChain Tools
│   │   ├── agents/            # LangGraph 状态图
│   │   └── api/               # FastAPI 接口（SSE 流式输出）
│   └── main.py
├── frontend/                  # Vue3 前端（Phase 2）
├── electron/                  # 桌面应用（Phase 5）
├── idea-plugin/               # IDEA 插件（Phase 6）
└── docs/
```

---

## 开发路线图

- [x] Phase 1：SSH 直连 + LangGraph + FastAPI 骨架
- [ ] Phase 2：Analysis Agent + Vue3 前端 + GIF 演示
- [ ] Phase 3：Dashboard Agent + DuckDB Native 模式
- [ ] Phase 4：Docker Compose + SkyWalking + LangFuse 可观测性
- [ ] Phase 5：Electron 桌面应用（Windows + Mac）
- [ ] Phase 6：IntelliJ IDEA 插件

---

## Contributing

欢迎贡献！提交 PR 前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 声明

LogMind 是独立原创开发的项目，非任何现有项目的 fork 或衍生版本。
所有代码均为原创，依赖库协议详见 [NOTICE](NOTICE)。

## License

MIT © [panshilong](https://github.com/panshilong)
