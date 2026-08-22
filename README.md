# ChinaZ Top Domains

从 ChinaZ「中文网站总排名」提取主机名，规范化为 eTLD+1，并按原排名生成去重域名列表。

> 本项目为非官方工具，与 ChinaZ／站长之家无隶属、授权或合作关系。榜单收录只作为候选发现信号，不代表域名所有权、运营主体或网络基础设施位于中国。

## 安装

前置条件：Python 3.10 或更高版本。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

安装 Wheel 后也可以直接使用：

```powershell
python -m pip install .\chinaz_top_domains-0.1.4-py3-none-any.whl
chinaz-top-domains --version
```

## 抓取指定数量

```powershell
# 默认输出 500 个唯一注册域名
chinaz-top-domains

# 输出 10,000 个唯一注册域名
chinaz-top-domains --limit 10000
```

指定数量模式写入：

```text
output/
├── domains.txt
└── ranking.csv
```

## 抓取完整榜单

```powershell
chinaz-top-domains --full `
  --cache-dir .cache/chinaz `
  --output-dir output/full
```

全量模式默认使用单线程，并保证相邻请求至少间隔 2 秒。缓存根目录会按榜单更新日期自动分层。任务中断后，使用相同命令继续；同周期结果及哈希都有效时，工具直接退出。

ChinaZ 各分页显示的更新日期可能不同。工具会在 `manifest.json` 的 `source_update_dates` 中记录全部观察值，并在完整抓取结束后重新检查第一页日期和最大页数；抓取期间源榜单元数据发生变化时，不发布结果。

页面原始排名必须从 1 连续到最后一名。IP 地址、公共后缀本身或其他无法转换为注册域名的条目不会进入域名列表，但会记录在 `filtered_source_entries` 中，不会被伪装成排名缺口。

完整结果：

```text
output/full/
├── top500.txt
├── top10000.txt
├── top100000.txt
├── all.txt
├── ranking.csv
└── manifest.json
```

发布前独立验证完整结果：

```powershell
chinaz-top-domains --verify-output output/full
```

验证覆盖文件 SHA-256、实际行数、域名唯一性、Top 文件前缀关系和 `ranking.csv` 域名顺序。

如果完整榜单不足 100,000 个唯一注册域名，`top100000.txt` 包含全部可用域名。`manifest.json` 中对应快照的 `complete` 为 `false`，`actual` 记录实际行数。工具不会通过重复域名凑满数量。

## 输出规则

TXT 文件统一使用 UTF-8、LF 换行，每行一个小写域名，不包含注释。国际化域名转换为 Punycode。

`ranking.csv` 用于本地审计，包含：

```text
normalized_rank
source_rank
domain
hostname
name
page
```

`data` 分支保存上述完整结果，包括用于核验来源顺序的 `ranking.csv`。域名数据只通过该分支更新，不创建数据 Release。

## 安全停止条件

以下情况立即停止，不生成新的最终结果：

- HTTP 403、HTTP 429 或其他非预期 4xx；
- 验证码、安全验证或访问频率页面；
- 所有重试后的网络错误或 5xx；
- 页面结构变化；
- 页面属于不同榜单更新日期；
- 原排名缺失或重复。

工具不会使用代理池、轮换 IP、绕过验证码或无限重试。

## 仓库分支

- `master`：工具源码、测试、文档和工具构建工作流。
- `data`：最新域名 TXT、`ranking.csv` 和 `manifest.json`，不包含工具源码和抓取缓存。

GitHub Actions 只测试、构建并发布工具本体的 `v*` Release。域名抓取不在 Actions 中运行；域名数据也不创建 GitHub Release。

RFCHost 使用 `deploy/run-and-publish.sh` 生成并验证结果。内容发生变化时，脚本使用 `chore(data): publish YYYY-MM-DD snapshot` 提交标题更新 `data` 分支；内容未变化时不提交。

## 工具发布产物

```text
chinaz_top_domains-X.Y.Z-py3-none-any.whl
chinaz_top_domains-X.Y.Z.tar.gz
chinaz-top-domains-vX.Y.Z-windows-x86_64.zip
SHA256SUMS
```

Linux 和 VPS 首版使用 Wheel 安装。Windows 独立程序是补充产物，不替代 Wheel 和源码包。

## 开发检查

```powershell
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
python -m pytest
python -m build
```

离线测试不会访问 ChinaZ。有限真实烟雾测试使用：

```powershell
chinaz-top-domains --limit 30 --output-dir output/smoke
```

## 数据和法律边界

工具源码使用 MIT License。该许可证不适用于第三方页面内容，也不表示项目维护者可以授权他人复制、传播或商业使用第三方数据。公开或定时运行前，请阅读 [DATA-NOTICE.md](DATA-NOTICE.md)，并自行确认数据源当时的协议和适用规则。
