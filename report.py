# -*- coding: utf-8 -*-
"""把两张表的当日/当周记录，整理成「关键事件 + 数据概览」的钉钉日报。"""
from datetime import datetime, timezone, timedelta

import config

# 这些取值代表“没发生动作 / 无异常”，分析时直接跳过
NOISE = {
    "", "无", "无调整", "无变化", "否", "无加量", "无加量动作", "无加量空间",
    "主力素材无变化", "无影响", "不涉及", "无平台活动", "无平台活动；",
    "正常", "无异常", "体力充沛", "—", "-", "/", "暂无",
}

YES_SET = {"是", "有", "有影响", "异常", "y", "yes", "true", "1"}


# ---------- 单元格 → 可读文本 ----------
def cell_text(v) -> str:
    """把飞书各种字段类型（文本/数字/人员/链接/多选…）压平成字符串。"""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        for k in ("text", "name", "value", "en_name"):
            if k in v and v[k]:
                val = v[k]
                if isinstance(val, list):
                    return "，".join(cell_text(x) for x in val if cell_text(x))
                return str(val).strip()
        return ""
    if isinstance(v, list):
        return "，".join(cell_text(x) for x in v if cell_text(x))
    return str(v).strip()


def to_float(v):
    s = cell_text(v).replace(",", "").replace("¥", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def to_percent(v):
    """把转化率之类的小数转成可读百分比，如 0.00147 -> '0.15%'"""
    f = to_float(v)
    if f is None:
        return None
    if f < 1:  # 小数形式，乘 100
        return f"{f * 100:.2f}%"
    return f"{f:.2f}%"


def meaningful(v) -> bool:
    s = cell_text(v)
    return bool(s) and s.replace("；", "").replace(";", "").strip() not in NOISE


def is_yes(v) -> bool:
    return cell_text(v).lower().strip("；; ") in YES_SET


def norm_date(v, tz) -> str:
    """统一成 YYYY-MM-DD。兼容文本日期和飞书毫秒时间戳。"""
    if isinstance(v, (int, float)) and v > 10_000_000_000:  # 毫秒时间戳
        return datetime.fromtimestamp(v / 1000, tz).strftime("%Y-%m-%d")
    s = cell_text(v)
    s = s.replace("/", "-")
    return s[:10] if len(s) >= 10 else s


def get(row, fields_map, key):
    return row.get(fields_map.get(key, key))


def weekday_str(date_str):
    return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
        datetime.strptime(date_str, "%Y-%m-%d").weekday()
    ]


# ---------- 按班次索引 ----------
def index_by_slot(rows, fields_map, target_date, tz):
    """把某张表当日的记录按 班次 归档：{ 'A': {...}, 'B': {...} }"""
    out = {}
    for row in rows:
        if norm_date(get(row, fields_map, "date"), tz) != target_date:
            continue
        slot = cell_text(get(row, fields_map, "slot")).upper().strip("； ")
        if slot:
            out[slot] = row
    return out


# ---------- 班次标签 ----------
def who_tag(s, follow):
    """生成 班次·主播（运营） 标签。"""
    op = cell_text(get(follow, config.FOLLOW_FIELDS, "operator"))
    an = cell_text(get(follow, config.FOLLOW_FIELDS, "anchor"))
    tag = f"{s}班"
    if an:
        tag += f"·{an}"
    if op:
        tag += f"（{op}）"
    return tag


# ---------- 提取单日关键事件 ----------
def _extract_events(slots, follow):
    ev = {"系数": [], "素材": [], "投放": [], "加量": [],
          "异常": [], "主播": [], "活动": [], "复盘": []}
    for s in slots:
        f = follow.get(s, {})
        FF = config.FOLLOW_FIELDS
        tag = who_tag(s, f)
        if meaningful(get(f, FF, "coefficient")):
            ev["系数"].append(f"{tag}：{cell_text(get(f, FF, 'coefficient'))}")
        if meaningful(get(f, FF, "material")):
            ev["素材"].append(f"{tag}：{cell_text(get(f, FF, 'material'))}")
        if meaningful(get(f, FF, "delivery")):
            ev["投放"].append(f"{tag}：{cell_text(get(f, FF, 'delivery'))}")
        if meaningful(get(f, FF, "volume")):
            ev["加量"].append(f"{tag}：{cell_text(get(f, FF, 'volume'))}")
        note = cell_text(get(f, FF, "abnormal_note"))
        if is_yes(get(f, FF, "abnormal")) and note:
            ev["异常"].append(f"{tag}：{note}")
        if is_yes(get(f, FF, "anchor_status_abnormal")):
            n = cell_text(get(f, FF, "anchor_status_note")) or "状态异常（详见跟播记录）"
            ev["主播"].append(f"{tag}：{n}")
        if meaningful(get(f, FF, "review_note")):
            ev["复盘"].append(f"{tag}：{cell_text(get(f, FF, 'review_note'))}")
        act = get(f, FF, "platform_activity")
        if meaningful(act):
            ev["活动"].append(f"{tag}：{cell_text(act)}")
    # 去重：同一人同一条记录同时标了"异常"和"主播状态"，去掉"主播"里的重复
    _dedup_anchor_status(ev)
    return ev


def _dedup_anchor_status(ev):
    """如果「主播」里某条的文本已被「异常」覆盖，则从主播中移除。"""
    abnormal_texts = set()
    for item in ev.get("异常", []):
        # 提取纯文本部分（去掉 tag 前缀）
        if "：" in item:
            abnormal_texts.add(item.split("：", 1)[1])
    ev["主播"] = [item for item in ev.get("主播", [])
                  if not any(t in item or item.split("：", 1)[-1] in t for t in abnormal_texts)]


# ---------- 单日数据提取 ----------
def _extract_daily(date_str, follow_rows, data_rows, tz):
    """提取单日所有计算数据，返回字典。"""
    follow = index_by_slot(follow_rows, config.FOLLOW_FIELDS, date_str, tz)
    data = index_by_slot(data_rows, config.DATA_FIELDS, date_str, tz)
    slots = [s for s in config.SLOT_ORDER if s in follow or s in data]

    gmv_total, roi_vals, slot_gmv = 0.0, [], {}
    for s in slots:
        d = data.get(s, {})
        g = to_float(get(d, config.DATA_FIELDS, "gmv")) or 0.0
        slot_gmv[s] = g
        gmv_total += g
        r = to_float(get(d, config.DATA_FIELDS, "roi"))
        if r:
            roi_vals.append(r)

    have_gmv = {s: g for s, g in slot_gmv.items() if g > 0}
    best_slot = max(have_gmv, key=have_gmv.get) if have_gmv else None
    avg_roi = sum(roi_vals) / len(roi_vals) if roi_vals else None

    events = _extract_events(slots, follow)

    slot_details = []
    for s in slots:
        f = follow.get(s, {})
        d = data.get(s, {})
        an = cell_text(get(f, config.FOLLOW_FIELDS, "anchor"))
        op = cell_text(get(f, config.FOLLOW_FIELDS, "operator"))
        g = slot_gmv.get(s, 0)
        roi = to_float(get(d, config.DATA_FIELDS, "roi"))
        conv = to_percent(get(d, config.DATA_FIELDS, "conv_rate")) or ""
        slot_details.append({
            "slot": s, "anchor": an, "operator": op, "gmv": g,
            "roi": roi, "conv_rate": conv,
        })

    return {
        "date": date_str,
        "weekday": weekday_str(date_str),
        "slots": slots,
        "gmv_total": gmv_total,
        "avg_roi": avg_roi,
        "best_slot": best_slot,
        "best_slot_gmv": have_gmv.get(best_slot) if best_slot else None,
        "slot_gmv": slot_gmv,
        "events": events,
        "slot_details": slot_details,
        "follow": follow,
        "data": data,
    }


# ---------- 单日报表 ----------
def build_report(target_date, follow_rows, data_rows):
    tz = timezone(timedelta(hours=8))
    dd = _extract_daily(target_date, follow_rows, data_rows, tz)
    title, text = _format_daily_report(dd)
    return title, text


def _format_daily_report(dd):
    L = []
    L.append(f"## 📊 {config.BRAND_NAME} {config.REPORT_TITLE} | {dd['date']}（{dd['weekday']}）")

    # AI 总结
    if config.AI_ENABLED and dd["gmv_total"] > 0:
        L.append("")
        from ai_summarize import summarize_daily
        ai = summarize_daily(dd["date"], dd["weekday"], dd["gmv_total"],
                             dd["avg_roi"], dd["events"], dd["slot_details"],
                             config.AI_API_KEY, config.AI_MODEL)
        if ai:
            L.append("**🤖 AI 智能总结**")
            L.append(ai)

    L.append("")
    L.append("**一、整体概览**")
    L.append(f"- 场次：{len([s for s in dd['slots'] if dd['slot_gmv'].get(s, 0) > 0])} 场有数据 / 共 {len(dd['slots'])} 排班")
    L.append(f"- 全天 GMV：**¥{dd['gmv_total']:,.0f}**")
    if dd['avg_roi'] is not None:
        L.append(f"- 平均 ROI：**{dd['avg_roi']:.2f}**")
    if dd['best_slot']:
        L.append(f"- 最佳场次：**{who_tag(dd['best_slot'], dd['follow'])}**，GMV ¥{dd['best_slot_gmv']:,.0f}")
    L.append("")

    L.append("**二、关键事件 & 节点**")
    _append_events_section(L, dd['events'], max_per_cat=2)
    L.append("")
    L.append("**三、场次明细**")
    _append_slot_table(L, dd['slots'], dd['slot_details'])
    _append_footer(L)

    text = "\n".join(L)
    title = f"{config.REPORT_TITLE} {dd['date']}"
    return title, text


# ---------- 周报表 ----------
def build_weekly_report(start_date, end_date, follow_rows, data_rows):
    tz = timezone(timedelta(hours=8))
    # 生成日期列表
    d_start = datetime.strptime(start_date, "%Y-%m-%d")
    d_end = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    cur = d_start
    while cur <= d_end:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    # 每天提取数据
    daily_list = [_extract_daily(d, follow_rows, data_rows, tz) for d in dates]

    # 有过数据的日期
    active_days = [dd for dd in daily_list if dd['gmv_total'] > 0]
    all_slots_total = sum(len(dd['slots']) for dd in daily_list)
    weeks_total_gmv = sum(dd['gmv_total'] for dd in daily_list)
    active_slots = sum(
        len([s for s in dd['slots'] if dd['slot_gmv'].get(s, 0) > 0])
        for dd in daily_list
    )
    days_with_data = len(active_days)

    # 周均 ROI
    all_roi = []
    for dd in daily_list:
        for s in dd['slots']:
            d = dd['data'].get(s, {})
            r = to_float(get(d, config.DATA_FIELDS, "roi"))
            if r:
                all_roi.append(r)
    avg_roi_week = sum(all_roi) / len(all_roi) if all_roi else None

    # 最佳日期 & 最佳场次
    best_day = max(active_days, key=lambda d: d['gmv_total']) if active_days else None
    best_slot_overall = None
    best_slot_gmv = 0
    best_slot_date = None
    for dd in daily_list:
        if dd['gmv_total'] > 0 and dd['best_slot']:
            if dd['best_slot_gmv'] > best_slot_gmv:
                best_slot_gmv = dd['best_slot_gmv']
                best_slot_overall = dd['best_slot']
                best_slot_date = dd['date']

    # 合并事件
    merged_events = {"系数": [], "素材": [], "投放": [], "加量": [],
                     "异常": [], "主播": [], "活动": [], "复盘": []}
    for dd in daily_list:
        for key in merged_events:
            if dd['events'][key]:
                merged_events[key].extend(
                    [f"[{dd['date']}]{e}" for e in dd['events'][key]]
                )

    # ---- 拼装 ----
    L = []
    L.append(f"## 📊 {config.BRAND_NAME} {config.REPORT_TITLE} | {start_date} ~ {end_date}")

    # AI 周报总结
    if config.AI_ENABLED and weeks_total_gmv > 0:
        L.append("")
        from ai_summarize import summarize_weekly
        ai = summarize_weekly(start_date, end_date, daily_list, merged_events,
                              config.AI_API_KEY, config.AI_MODEL)
        if ai:
            L.append("**🤖 AI 周报总结**")
            L.append(ai)

    L.append("")
    L.append("**一、一周概览**")
    L.append(f"- 统计天数：{len(dates)} 天")
    L.append(f"- 有数据场次：{active_slots} 场 / 总排班 {all_slots_total} 场")
    L.append(f"- 周总 GMV：**¥{weeks_total_gmv:,.0f}**")
    L.append(f"- 日均 GMV：**¥{weeks_total_gmv / days_with_data:,.0f}**" if days_with_data > 0
             else "- 日均 GMV：暂无数据")
    if avg_roi_week is not None:
        L.append(f"- 周平均 ROI：**{avg_roi_week:.2f}**")
    if best_day:
        L.append(f"- 最佳日期：**{best_day['date']}（{best_day['weekday']}）**，GMV ¥{best_day['gmv_total']:,.0f}")
    if best_slot_date and best_slot_overall:
        best_follow = daily_list[dates.index(best_slot_date)]['follow'] if best_slot_date in dates else {}
        L.append(f"- 最佳场次：**{best_slot_date} {best_slot_overall}班**，GMV ¥{best_slot_gmv:,.0f}")

    # ---- 浓缩事件（每类只展示 1-2 条代表作）----
    L.append("")
    L.append("**二、本周运营要点**")
    any_ev = False
    for key in _ORDER:
        items = merged_events.get(key, [])
        if not items:
            continue
        any_ev = True
        total = len(items)
        show = items[:2]  # 每类最多 2 条
        L.append(f"\n*{_ICON.get(key, key)}（{total}条）*")
        for line in show:
            L.append(f"- {line}")
    if not any_ev:
        L.append("- 各场次运营动作平稳，无重点异常。")

    # ---- 每日速览（紧凑表格）----
    L.append("")
    L.append("**三、每日速览**")
    L.append("")
    L.append("| 日期 | GMV | ROI | 要点 |")
    L.append("|------|----:|----:|------|")
    for dd in daily_list:
        if dd['gmv_total'] == 0:
            L.append(f"| {dd['date']}（{dd['weekday']}） | — | — | 数据未录入 |")
            continue
        # 提取当日最关键的一句话
        highlight = ""
        for key in ["异常", "主播"]:
            if dd['events'].get(key):
                highlight = dd['events'][key][0][:50]
                break
        if not highlight:
            for key in ["系数", "素材", "加量", "投放"]:
                if dd['events'].get(key):
                    highlight = dd['events'][key][0][:50]
                    break
        if not highlight:
            highlight = "运营平稳"
        roi_str = f"{dd['avg_roi']:.2f}" if dd['avg_roi'] else "—"
        L.append(f"| {dd['date']}（{dd['weekday']}） | ¥{dd['gmv_total']:,.0f} | {roi_str} | {highlight} |")

    _append_footer(L)

    text = "\n".join(L)
    title = f"{config.REPORT_TITLE} {start_date} ~ {end_date}"
    return title, text


# ---------- 周报分析（供 Web 前端用）----------
def compute_weekly_analytics(start_date, end_date, follow_rows, data_rows):
    """返回结构化分析数据：趋势、运营/主播汇总、告警列表。"""
    tz = timezone(timedelta(hours=8))
    d_start = datetime.strptime(start_date, "%Y-%m-%d")
    d_end = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    cur = d_start
    while cur <= d_end:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    daily_list = [_extract_daily(d, follow_rows, data_rows, tz) for d in dates]

    # 趋势
    trends = []
    for dd in daily_list:
        roi_vals = []
        for s in dd["slots"]:
            d = dd["data"].get(s, {})
            r = to_float(get(d, config.DATA_FIELDS, "roi"))
            if r:
                roi_vals.append(r)
        trends.append({
            "date": dd["date"], "weekday": dd["weekday"],
            "gmv": dd["gmv_total"],
            "roi": sum(roi_vals) / len(roi_vals) if roi_vals else None,
        })

    # 运营 & 主播汇总
    op_map = {}
    anchor_map = {}
    for dd in daily_list:
        for sd in dd["slot_details"]:
            if sd["gmv"] <= 0:
                continue
            ops = [x.strip() for x in sd["operator"].replace("，", ",").split(",") if x.strip()]
            for op in ops:
                if op not in op_map:
                    op_map[op] = {"gmv": 0, "slots": 0, "roi_vals": []}
                op_map[op]["gmv"] += sd["gmv"]
                op_map[op]["slots"] += 1
                if sd["roi"]:
                    op_map[op]["roi_vals"].append(sd["roi"])
            an = sd["anchor"]
            if an:
                if an not in anchor_map:
                    anchor_map[an] = {"gmv": 0, "slots": 0, "roi_vals": []}
                anchor_map[an]["gmv"] += sd["gmv"]
                anchor_map[an]["slots"] += 1
                if sd["roi"]:
                    anchor_map[an]["roi_vals"].append(sd["roi"])

    operator_summary = []
    for name, v in sorted(op_map.items(), key=lambda x: -x[1]["gmv"]):
        operator_summary.append({
            "name": name, "gmv": v["gmv"], "slots": v["slots"],
            "avg_roi": sum(v["roi_vals"]) / len(v["roi_vals"]) if v["roi_vals"] else None,
        })
    anchor_summary = []
    for name, v in sorted(anchor_map.items(), key=lambda x: -x[1]["gmv"]):
        anchor_summary.append({
            "name": name, "gmv": v["gmv"], "slots": v["slots"],
            "avg_roi": sum(v["roi_vals"]) / len(v["roi_vals"]) if v["roi_vals"] else None,
        })

    # 告警
    alerts = []
    for dd in daily_list:
        for key in ["异常", "主播"]:
            for e in dd["events"].get(key, []):
                alerts.append({"date": dd["date"], "type": key, "text": e})

    return {
        "trends": trends,
        "operator_summary": operator_summary,
        "anchor_summary": anchor_summary,
        "alerts": alerts,
    }


# ---------- 共用：事件板块 ----------
_ICON = {"系数": "🔧 系数调整", "素材": "🎬 素材动作", "投放": "📈 投放/成本",
         "加量": "⏫ 加量/控量", "异常": "⚠️ 异常 & 风险", "主播": "🎤 主播状态",
         "复盘": "📝 复盘要点", "活动": "🎁 平台活动"}
_ORDER = ["异常", "主播", "系数", "素材", "投放", "加量", "复盘", "活动"]


def _event_icon(key):
    return _ICON.get(key, key)


def _append_events_section(L, events, max_per_cat=None):
    any_event = False
    for key in _ORDER:
        items = events.get(key, [])
        if not items:
            continue
        any_event = True
        total = len(items)
        show = items[:max_per_cat] if max_per_cat else items
        label = f"{_ICON.get(key, key)}" + (f"（共{total}条）" if max_per_cat and total > len(show) else "")
        L.append(f"\n*{label}*")
        for line in show:
            L.append(f"- {line}")
    if not any_event:
        L.append("- 各场次运营动作平稳，无重点异常。")


# ---------- 共用：场次明细表格 ----------
def _append_slot_table(L, slots, slot_details):
    L.append("")
    L.append("| 班次 | 时段 | 主播 | 运营 | GMV | ROI | 转化 |")
    L.append("|------|------|------|------|----:|----:|------|")
    for s, sd in zip(slots, slot_details):
        g = sd['gmv']
        roi_s = f"{sd['roi']:.2f}" if sd['roi'] and g > 0 else "—"
        conv_s = sd['conv_rate'] if sd['conv_rate'] and g > 0 and sd['conv_rate'] not in ("0%", "0.00%", "0") else "—"
        gmv_s = f"¥{g:,.0f}" if g > 0 else "—"
        L.append(f"| {s} | {config.SLOT_TIME.get(s,'')} | {sd['anchor'] or '—'} | {sd['operator'] or '—'} | {gmv_s} | {roi_s} | {conv_s} |")


# ---------- 共用：生成时间 ----------
def _append_footer(L):
    tz = timezone(timedelta(hours=8))
    L.append("")
    L.append(f"> 自动播报 · {datetime.now(tz).strftime('%Y-%m-%d %H:%M')} 生成")
