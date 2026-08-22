# systemd 部署

此模板只负责在 VPS 检查和生成域名文件，不负责创建工具 Release，也不通过 GitHub Actions 抓取数据。

## 前置条件

- Linux 主机已安装 Python 3.10 或更高版本。
- 已准备项目 Wheel。
- `/opt/chinaz-top-domains`、`/var/cache/chinaz-top-domains` 和 `/var/lib/chinaz-top-domains` 尚未被其他服务使用。

## 安装

```bash
sudo useradd --system --home /var/lib/chinaz-top-domains --shell /usr/sbin/nologin chinaz-domains
sudo install -d -o chinaz-domains -g chinaz-domains /opt/chinaz-top-domains
sudo install -d -o chinaz-domains -g chinaz-domains /var/cache/chinaz-top-domains
sudo install -d -o chinaz-domains -g chinaz-domains /var/lib/chinaz-top-domains

sudo python3 -m venv /opt/chinaz-top-domains/venv
sudo /opt/chinaz-top-domains/venv/bin/python -m pip install ./chinaz_top_domains-0.1.0-py3-none-any.whl

sudo install -m 0644 deploy/systemd/chinaz-top-domains.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/chinaz-top-domains.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chinaz-top-domains.timer
```

## 验证

```bash
systemctl list-timers chinaz-top-domains.timer
sudo systemctl start chinaz-top-domains.service
systemctl status chinaz-top-domains.service
journalctl -u chinaz-top-domains.service -n 100 --no-pager
```

成功后，结果位于：

```text
/var/lib/chinaz-top-domains/output/
```

同一榜单周期的结果及 SHA-256 均有效时，每日任务只检查第一页并退出。新周期使用新的日期缓存子目录。缓存清理应在确认最终结果已经备份后单独执行，不要在抓取任务中自动删除。

## 数据分支发布边界

将结果提交到 `data` 分支属于独立发布步骤。部署密钥、远端地址和仓库权限由实际环境决定，因此模板不自动执行 Git 推送。发布前至少确认：

1. `manifest.json` 存在。
2. 清单中所有文件 SHA-256 可复算。
3. 数据内容相较上一版本确有变化。
4. 目标工作区位于 `data` 分支。
5. 提交中不包含缓存、日志、密钥或工具源码。
