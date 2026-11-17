## 改动内容

<!-- 一句话说清改了什么 -->

## 怎么验证的

```bash
python3 scripts/test_hygiene.py
python3 scripts/check_hygiene.py --strict --require-coc
PYTHONPATH=scripts python3 -m unittest discover -s scripts -p "test_workflows.py"
```

<!-- 记录实际执行的命令和结果；未执行的检查请说明原因。 -->

## AI 辅助

<!-- 请填写使用的 AI 工具和模型；未使用 AI 时写「未使用 AI」。 -->

## 风险

<!-- 说明风险等级与影响范围。 -->
