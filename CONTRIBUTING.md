# Contributing

感谢你参与 GdeiAssistant 社区仓库的维护与改进。

## 基本流程

1. 从 `origin/main` 拉出分支（如 `docs/`、`chore/`、`fix/`、`feat/`）。
2. 在对应客户或服务端仓库提交业务变更，在本仓库只维护组织简介、默认社区文档与仓库卫生基线。
3. 提交前在本地运行检查：

```sh
python3 scripts/test_hygiene.py
python3 scripts/check_hygiene.py --strict --require-coc
PYTHONPATH=scripts python3 -m unittest discover -s scripts -p "test_workflows.py"
python3 scripts/check_workflows.py
```

## 提交与文档要求

- Commit 标题使用英文 Conventional Commits（不超过 72 字符），PR 描述按模板填写改动内容、验证方式和风险。
- 不在公开仓库提交 `.local/`、`ops-notes/`、`docs/plans/`、`docs/audits/`、`docs/changes/`、`docs/acceptance-policy.md` 或真实凭据。
- 所有贡献默认遵循本仓库的 `Apache-2.0` 许可证。
