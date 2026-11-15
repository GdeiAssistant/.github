# GdeiAssistant/.github

GdeiAssistant 组织的社区资料、默认模板与仓库卫生基线仓库。

> 可复用的 PR 治理门禁已统一维护在 [Pigbibi/PrGovernance](https://github.com/Pigbibi/PrGovernance)，各子仓库直接固定其 commit SHA 引用。

## 目录说明

| 路径 | 用途 |
| --- | --- |
| `profile/README.md` | 组织 GitHub 主页展示文案 |
| `SECURITY.md` | 组织默认安全漏洞披露边界 |
| `CONTRIBUTING.md` | 组织默认贡献与提交流程说明 |
| `CODE_OF_CONDUCT.md` | 组织社区行为准则 |
| `.github/pull_request_template.md` | 组织默认 PR 模板 |
| `.github/ISSUE_TEMPLATE/` | 组织默认 Issue 模板 |
| `scripts/check_hygiene.py` | 仓库文档命名、防泄露与规范检查脚本 |

## 本地检查

```sh
python3 scripts/test_hygiene.py
python3 scripts/check_hygiene.py --strict
```

## License

本项目遵循 [Apache License 2.0](LICENSE)。
