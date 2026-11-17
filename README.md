# GdeiAssistant/.github

GdeiAssistant 组织的社区资料、默认模板与共享仓库卫生基线仓库。

> 可复用的 PR 治理门禁已统一维护在 [Pigbibi/PrGovernance](https://github.com/Pigbibi/PrGovernance)，各子仓库直接固定其 commit SHA 引用。

## 目录说明

| 路径 | 用途 |
| --- | --- |
| `profile/README.md` | 组织 GitHub 主页展示文案 |
| `actions/repository-hygiene/` | 供各子仓库固定 SHA 引用的复合卫生检查 Action |
| `actions/commitlint/` | 供各子仓库固定 SHA 引用的 Conventional Commits 校验 Action |
| `actions/artifact-secret-scan/` | 供各子仓库固定 SHA 引用的构建产物敏感信息扫描 Action |
| `actions/dependabot-policy/` | 供各子仓库固定 SHA 引用的 Dependabot 策略校验与自动合并 Action |
| `SECURITY.md` | 组织默认安全漏洞披露边界 |
| `CONTRIBUTING.md` | 组织默认贡献与提交流程说明 |
| `CODE_OF_CONDUCT.md` | 组织社区行为准则与举报联系方式 |
| `NOTICE` | 组织默认版权与归属说明 |
| `TRADEMARK.md` | 组织品牌与商标合理使用边界 |
| `.github/pull_request_template.md` | 组织默认 PR 模板 |
| `.github/ISSUE_TEMPLATE/` | 组织默认 Issue 模板 |
| `scripts/check_hygiene.py` | 仓库文档命名、防泄露与规范检查脚本 |
| `scripts/check_workflows.py` | 工作流权限、SHA 固定与脚本防注入检查脚本 |
| `scripts/artifact_secret_scan.py` | 受控构建产物边界解包与 Gitleaks 扫描脚本 |
| `scripts/dependabot-policy.cjs` | 参数化 Dependabot 依赖策略校验与原子合并脚本 |

## 本地检查

```sh
python3 -m unittest discover -s scripts -p "test_*.py"
python3 scripts/check_hygiene.py --strict --require-coc
node --test scripts/test-dependabot-policy.cjs
actionlint -shellcheck= -pyflakes=
```

## License

本仓库遵循 [Apache License 2.0](LICENSE)。
