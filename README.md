# LogMind — AI 日志分析平台

> 只需要 SSH 权限，5分钟内用自然语言查所有服务器的日志。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)

## 特性

- **SSH 直连模式**：只需服务器账号密码，零基础设施依赖
- **Native 模式**：内置 DuckDB 存储 + 日志采集器，替代 ELK
- **Bridge 模式**：已有 Elasticsearch 直接接入
- **Multi-Agent**：LangGraph 驱动，意图分类 → 查询/分析/看板自动路由
- **多 LLM 支持**：Kimi / DeepSeek / Qwen / OpenAI，改一行配置切换
- **桌面应用**：Windows + Mac 安装包（Phase 5）
- **IDEA 插件**：IDE 内直接分析异常堆栈（Phase 6）

## 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/panshilong/logmind.git
cd logmind

# 2. 复制配置文件，填入你的信息
cp backend/config.example.yaml backend/config.yaml
# 编辑 config.yaml，填入 SSH 信息和 LLM API Key

# 3. 安装依赖并启动
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## 配置示例（SSH 直连模式，最简单）

```yaml
datasource:
  type: ssh

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
```

启动后访问 `http://localhost:8000/docs` 查看 API 文档。

## 支持的数据源

| 类型 | 配置 `type` | 说明 |
|------|------------|------|
| SSH 直连 | `ssh` | 零基础设施，推荐新手 |
| 本地存储 | `duckdb` | 内置采集器，历史查询 |
| Elasticsearch | `elasticsearch` | 已有 ELK 直接接入 |
| SkyWalking | `skywalking` | APM + Trace 数据 |

## 支持的 LLM

| 提供商 | `provider` | 获取 Key |
|--------|-----------|---------|
| 月之暗面 Kimi | `kimi` | platform.moonshot.cn |
| DeepSeek | `deepseek` | platform.deepseek.com |
| 通义千问 | `qwen` | dashscope.aliyuncs.com |
| OpenAI | `openai` | platform.openai.com |

## 项目结构

```
logmind/
├── backend/          # Python FastAPI 后端
├── frontend/         # Vue3 前端（Phase 2）
├── electron/         # 桌面应用（Phase 5）
├── idea-plugin/      # IDEA 插件（Phase 6）
└── docs/             # 文档
```

## 开发路线图

- [x] Phase 1：SSH 直连 + LangGraph + FastAPI
- [ ] Phase 2：Analysis Agent + Vue3 前端
- [ ] Phase 3：Dashboard Agent + DuckDB Native 模式
- [ ] Phase 4：Docker Compose + LangFuse + 开源发布
- [ ] Phase 5：Electron 桌面应用
- [ ] Phase 6：IntelliJ IDEA 插件

## Contributing

欢迎贡献！提交 PR 前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 声明

LogMind 是独立原创开发的项目，非任何现有项目的 fork 或衍生版本。
所有代码均为原创，依赖库协议详见 [NOTICE](NOTICE)。

## License

MIT © [panshilong](https://github.com/panshilong)
