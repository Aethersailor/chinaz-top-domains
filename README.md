# ChinaZ Top Domains Data

此 orphan 分支只保存 `chinaz-top-domains` 工具生成的最新域名数据，不包含工具源码、抓取缓存或日志。

预期文件：

```text
top500.txt
top10000.txt
top100000.txt
all.txt
ranking.csv
manifest.json
status.json
```

数据只通过此分支更新，不创建 GitHub Release。`manifest.json` 是整批结果完成的标志，并记录源榜单日期、工具版本、实际数量和文件 SHA-256。

系统每天检查一次源榜单。源榜单变化时更新域名文件；没有变化时，只更新 `status.json` 以记录当天已经成功检查。同一天重复检查不会重复提交。

首次完整抓取和校验完成前，本分支只保留此说明。项目为非官方工具，与 ChinaZ／站长之家无隶属、授权或合作关系。
