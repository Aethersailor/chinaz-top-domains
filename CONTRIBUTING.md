# 贡献指南

## 开发环境

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## 提交前检查

```powershell
ruff format --check .
ruff check .
python -m pytest
python -m build
```

测试默认使用本地最小 HTML，不访问 ChinaZ。除非维护者明确要求，不要在自动化测试中加入实时网络抓取。

提交信息使用 Conventional Commits：

```text
feat(cli): add snapshot selection
fix(crawler): stop on rate limiting
docs(readme): clarify data boundaries
```
