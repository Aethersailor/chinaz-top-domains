# 贡献指南

## 开发环境

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## 本地构建

```powershell
python -m build
```


提交信息使用 Conventional Commits：

```text
feat(cli): add snapshot selection
fix(crawler): stop on rate limiting
docs(readme): clarify data boundaries
```

Commit 标题最长 100 个字符，不使用句号结尾。`master` 和 `data` 分支采用同一提交格式。功能由维护者人工验证，CodeQL 独立扫描，Dependabot 自动合并。
