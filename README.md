# 直播跟播日报机器人（飞书多维表 → 钉钉群）

每天定时扫描飞书多维表里的「跟播记录」和「直播数据」，自动整理出当日
**关键事件 & 节点 + 数据概览**，通过钉钉自定义机器人播报到指定群。

## 目录结构
```
livestream_daily_bot/
├── settings.ini     # ★ 唯一要改的入口：飞书密钥 / 表ID / 钉钉机器人
├── config.py        # 读取 settings.ini + 字段映射（一次性对齐列名）
├── feishu.py        # 飞书：取 token / 解析 wiki / 读记录
├── dingtalk.py      # 钉钉：加签 + 发 markdown
├── report.py        # 核心：提取关键事件 + 拼日报
├── main.py          # 入口（定时任务跑这个）
├── demo.py          # 离线预览（无需密钥，先看效果）
└── requirements.txt
```

## 一、装依赖
```bash
pip install -r requirements.txt
```

## 二、先看效果（不用配任何东西）
```bash
python demo.py
```
会用 2026-06-04 的示例数据打印一份日报，确认格式符合预期。

## 三、改 settings.ini（换机器人/换群/改密钥都只改这个文件）
打开 `settings.ini`：

- `[feishu]`：填 `app_id` / `app_secret`；`wiki_node_token` 已是你的链接那串；
  两张表的 `follow_table_id` / `data_table_id`（同一张多维表里，地址栏 `?table=tblXXXX`）。
- `[dingtalk]`：填 `webhook` 和加签 `secret`。**以后换机器人就改这两行**，代码不用动。
- 想同时播到多个群：把文件里 `[dingtalk_2]` 那段取消注释、各填各的即可；
  想临时停用某个群，把它的 `enabled` 改成 `false`。

> 也支持环境变量覆盖（适合服务器不落盘密钥）：如 `FEISHU_APP_SECRET`、`DINGTALK_WEBHOOK`。

## 四、飞书应用授权（一次性）
1. 飞书开放平台 → 企业自建应用 → 拿到 App ID / Secret 填进 `settings.ini`。
2. 权限管理勾选并发布：`bitable:app:readonly`、`wiki:wiki:readonly`。
3. **把应用加进多维表**：打开多维表 → 右上「···」→ 添加协作者 → 搜应用名 → 给「可阅读」。

## 五、钉钉机器人（一次性）
群设置 → 智能群助手 → 添加机器人 → 自定义；安全设置**建议选「加签」**，
把 webhook 和密钥填到 `settings.ini` 的 `[dingtalk]`。
（若用「自定义关键词」，保证关键词在标题/正文里，默认标题含「直播日报」。）

## 六、对齐字段名（重要，一次性）
`config.py` 里 `FOLLOW_FIELDS` / `DATA_FIELDS` 左边别动，右边换成你表里真实列名。
尤其数据表的 `gmv / roi / conv_rate` 要确认对应哪一列。

## 六、跑起来
```bash
python main.py --dry-run            # 只打印不推送（首次必做）
python main.py                      # 播报“今天”
python main.py --date 2026-06-04    # 补播某一天
```

## 七、定时（每天自动播报）
用 crontab。例：每天 02:30 播报“前一天”（E班跨夜结束后），再在每天 22:30
播报“当天截至目前”：
```cron
# 凌晨 02:30 出完整日报（A~E 全部结束）
30 2 * * * cd /path/to/livestream_daily_bot && /usr/bin/python3 main.py --date "$(date -d yesterday +\%F)" >> bot.log 2>&1
# 晚上 22:30 出当天进度（D 班结束后）
30 22 * * * cd /path/to/livestream_daily_bot && /usr/bin/python3 main.py >> bot.log 2>&1
```
> 多次运行不会重复堆积——每次都是对“当前状态”重新汇总，覆盖式播报。
> 想做到“准实时”，把频率调密即可（如每 2 小时一次），代价是消息更多。

## 八、关键事件是怎么判定的
`report.py` 里把「无调整/无变化/无影响/否/无平台活动」等当作“无动作”过滤掉，
只要某个字段填了实质内容就算一条关键事件，并归到对应板块：
系数 / 素材 / 投放 / 加量 / 异常 / 主播状态 / 复盘 / 平台活动。
想增减过滤词，改 `report.py` 顶部的 `NOISE` 集合即可。
