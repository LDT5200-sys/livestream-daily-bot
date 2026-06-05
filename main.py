# -*- coding: utf-8 -*-
"""
入口：抓取飞书记录 -> 生成日报/周报 -> 推送钉钉。

用法：
  python main.py                           # 播报"今天"（单日）
  python main.py --date 2026-06-04         # 补播某一天
  python main.py --week                    # 播报最近一周（含今天，共 7 天）
  python main.py --week --date 2026-06-04  # 以指定日期为截止日的一周
  python main.py --dry-run                 # 只打印，不推送钉钉（首次调试用）
"""
import sys
import argparse
from datetime import datetime, timezone, timedelta

import config
from feishu import FeishuClient
from dingtalk import send_markdown
from report import build_report, build_weekly_report


def today_str():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=today_str(), help="YYYY-MM-DD，默认今天")
    ap.add_argument("--week", action="store_true", help="播报最近一周（以 --date 日期为截止，往前 7 天）")
    ap.add_argument("--dry-run", action="store_true", help="只打印不推送")
    args = ap.parse_args()

    fs = FeishuClient(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
    app_token = config.FEISHU_APP_TOKEN or fs.resolve_app_token(config.FEISHU_WIKI_NODE_TOKEN)

    follow_rows = fs.fetch_records(app_token, config.FOLLOW_TABLE_ID)
    if config.DATA_TABLE_ID == config.FOLLOW_TABLE_ID:
        data_rows = follow_rows
    else:
        data_rows = fs.fetch_records(app_token, config.DATA_TABLE_ID)

    if args.week:
        end_date = args.date
        tz = timezone(timedelta(hours=8))
        start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
        title, text = build_weekly_report(start_date, end_date, follow_rows, data_rows)
    else:
        title, text = build_report(args.date, follow_rows, data_rows)

    if args.dry_run:
        print(text)
        return

    targets = config.DINGTALK_TARGETS
    if not targets:
        raise RuntimeError("未配置可用的钉钉机器人：请在 settings.ini 的 [dingtalk] 段填好 webhook（和加签 secret）")

    for t in targets:
        send_markdown(t["webhook"], t["secret"], title, text,
                      at_mobiles=t["at_mobiles"], at_all=t["at_all"])
        print(f"[OK] 已推送 {title} -> {t['name']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
