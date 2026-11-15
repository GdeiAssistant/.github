# AGENTS.md

## 项目是什么

`GdeiAssistant/.github` 维护 GdeiAssistant 组织的 GitHub 主页简介、默认社区规范与仓库卫生检查基线。

## 技术栈

Markdown 组织规范文档 + Python 3（`scripts/check_hygiene.py`）+ GitHub Actions CI。

## 目录

- `profile/README.md` — 组织 GitHub 主页文案。
- `.github/` — 默认 Issue / PR 模板与 CI workflow。
- `scripts/` — 文档、防泄露和规范检查脚本及其单元测试。

## 本地验证

```bash
python3 scripts/test_hygiene.py
python3 scripts/check_hygiene.py --strict
```

## 命名与文档

- 本仓库面向开源社区，文档保持简体中文、简洁直接，不写“本轮”“this PR”等过程叙述。
- 新增文档文件名小写并以 `-` 连接，不提交 `docs/plans/`、`docs/audits/`、`docs/changes/` 或 `docs/acceptance-policy.md`。

## 不要做

- 不要在这里重新维护或拷贝 `pr-governance/`；PR 治理动作统一引用 `Pigbibi/PrGovernance/pr-governance@<SHA>`。
- 不要修改 `README.md` 在 `## License` 之后追加任何章节，也不要为纯治理调整顺手改写无关说明。
- 不要削弱 `.gitignore` 防泄露规则或提交真实账号、校园凭据与私有 ID。

<!-- content-boundary:begin -->
- 公开材料不出现真实资源名与账号，示例统一使用占位符或合成值。
- 判断一次改动是否干净看 `git diff` 和 `git ls-files`；`.gitignore` 只拦截未跟踪文件。
<!-- content-boundary:end -->

## 提交与 PR

- Commit 标题遵循英文 Conventional Commits（`feat`、`fix`、`docs`、`chore`、`ci`），不超过 72 字符。
- 从 `origin/main` 分支开发，PR 描述按 `.github/pull_request_template.md` 写明改动、验证结果与风险。
