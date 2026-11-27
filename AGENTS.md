# AGENTS.md

## 项目是什么

`GdeiAssistant/.github` 维护 GdeiAssistant 组织的 GitHub 主页简介、共享复合 CI Action、默认社区规范与仓库卫生检查基线。

## 技术栈

Markdown 组织规范文档 + Python 3（`scripts/check_hygiene.py`、`scripts/check_workflows.py`、`scripts/artifact_secret_scan.py`）+ Node.js（`scripts/dependabot-policy.cjs`）+ GitHub Actions 复合 Action。

## 目录

- `profile/README.md` — 组织 GitHub 主页文案。
- `actions/` — `repository-hygiene`、`commitlint`、`artifact-secret-scan`、`dependabot-policy` 共享复合 Action。
- `.github/` — 默认 Issue / PR 模板、`CODEOWNERS`、Copilot 指引、Dependabot 与 CI workflow。
- `scripts/` — 卫生、工作流安全、产物扫描、Dependabot 策略脚本及其单元测试。
- `CODE_OF_CONDUCT.md`、`NOTICE`、`TRADEMARK.md` — 组织级社区准则与归属基线。

## 本地验证

```bash
python3 -m unittest discover -s scripts -p "test_*.py"
python3 scripts/check_hygiene.py --strict --require-coc
python3 scripts/check_workflows.py
node --test scripts/test-dependabot-policy.cjs
actionlint -shellcheck= -pyflakes=
```

## 命名与文档

- 本仓库面向开源社区，文档保持简体中文、简洁直接，不写过程叙述。规则统一写在 `AGENTS.md`，根目录 `CLAUDE.md` 与 `GEMINI.md` 仅保留单行 `@AGENTS.md`。
- 新增文档文件名小写并以 `-` 连接；单语文档不加语言后缀，仅在保留中英双语对照副本时使用 `.zh-CN.md` / `.en.md`。不提交 `docs/plans/`、`docs/audits/`、`docs/changes/` 或 `docs/acceptance-policy.md`。

## 不要做

- 不要在这里重新维护或拷贝 `pr-governance/`；PR 治理动作统一引用 `Pigbibi/PrGovernance/pr-governance@<SHA>`。
- 不要在 `README.md` 的 `## License` 之后追加任何章节，也不要破坏 `actions/` 的输入输出契约。
- 不要削弱 `.gitignore` 防泄露规则或提交真实账号、校园凭据与私有 ID。

<!-- content-boundary:begin -->
- 公开仓库、PR、Issue、commit 与评论不出现个人信息（国籍/税务居民身份、个人资金或账户规模、真实券商与账号、住址、邮箱、手机号）和真实云/校园基础设施标识（GCP 项目号/ID、存储桶名、服务器公网 IP/主机名、WIF 路径、校园账号与内部凭据，`CODEOWNERS` 路由句柄除外）。统一用 `gs://<bucket>/...`、`<project-number>`、`<host>` 等占位符或合成值，哈希或截断 ID 不算匿名化。
- 判断一次改动是否干净看 `git diff` 和 `git ls-files`；`.gitignore` 只拦截未跟踪文件。
<!-- content-boundary:end -->

## 提交与 PR

- Commit 标题遵循英文 Conventional Commits（`feat`、`fix`、`docs`、`refactor`、`test`、`chore`、`perf`、`ci`、`build`），不超过 72 字符。
- 从 `origin/main` 分支开发，PR 描述按 `.github/pull_request_template.md` 写明改动、验证结果与风险。
