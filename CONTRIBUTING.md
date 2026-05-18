# Contributing to LogMind

感谢你愿意为 LogMind 做贡献！

## 贡献者许可协议（CLA）

向本项目提交代码即表示你同意：

1. 你提交的代码是你自己的原创作品，或你有权以 MIT 协议授权
2. 你授予项目维护者永久、全球、免版税的权利，在 MIT 协议下使用你的贡献
3. 你的贡献不侵犯任何第三方的知识产权

## 如何贡献

1. Fork 本仓库
2. 创建功能分支 `git checkout -b feature/your-feature`
3. 提交改动 `git commit -m "add: 简短描述"`
4. 推送分支 `git push origin feature/your-feature`
5. 创建 Pull Request

## 代码规范

- Python 代码遵循 PEP8，使用 `ruff` 格式化
- 新增 DataSource 实现须继承 `LogDataSource` ABC 并通过全部抽象方法
- 新增 Tool 须通过 `make_log_tools` 工厂注入 datasource，不得直接依赖具体实现

## 报告问题

请通过 [GitHub Issues](https://github.com/panshilong/logmind/issues) 反馈 Bug 或建议。
