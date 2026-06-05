# -*- coding: utf-8 -*-
"""调用 DeepSeek API 对运营记录进行智能总结。"""
import requests

DEEPSEEK_BASE = "https://api.deepseek.com/v1"


def _call_deepseek(prompt, api_key, model, max_tokens=500):
    """通用 DeepSeek 调用。"""
    r = requests.post(
        f"{DEEPSEEK_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "你是直播运营数据分析助手，输出简洁专业的中文要点。每条约30-50字，用'- '开头。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens,
        },
        timeout=30,
    )
    data = r.json()
    if data.get("choices"):
        return data["choices"][0]["message"]["content"].strip()
    raise RuntimeError(f"DeepSeek API 错误: {data}")


def summarize_daily(date_str, weekday, gmv_total, avg_roi, events, slot_details, api_key, model="deepseek-chat"):
    """总结单日运营要点，返回 Markdown 文本。"""
    if not api_key:
        return None

    # 场次概况
    slot_text = ""
    for sd in slot_details:
        if sd["gmv"] > 0:
            roi_str = f"，ROI {sd['roi']:.2f}" if sd.get("roi") else ""
            slot_text += f"- {sd['slot']}班 {sd['anchor']}（{sd['operator']}）：GMV ¥{sd['gmv']:,.0f}{roi_str}\n"

    # 关键事件
    event_text = ""
    for cat in ["异常", "主播", "系数", "素材", "投放", "加量", "复盘", "活动"]:
        items = events.get(cat, [])
        if items:
            event_text += f"\n【{cat}】\n"
            for it in items[:5]:
                event_text += f"- {it}\n"

    prompt = f"""根据以下 {date_str}（{weekday}）的直播运营数据，用 3-5 条简洁中文要点总结当日情况。

整体：GMV ¥{gmv_total:,.0f}，平均 ROI {avg_roi:.2f}
（若 GMV=0 表示当日数据未录入，直接回复"当日数据未录入，暂无总结"）

场次明细：
{slot_text}

运营记录：
{event_text if event_text else '当日无特殊运营记录'}

重点关注：整体表现评价、最值得关注的事件、风险提示、可优化方向。
用 "- " 开头的中文要点输出，每条不超过 40 字。"""

    try:
        return _call_deepseek(prompt, api_key, model, 500)
    except Exception as e:
        return f"（AI 总结生成失败：{e}）"


def summarize_weekly(start_date, end_date, daily_list, merged_events, api_key, model="deepseek-chat"):
    """总结一周运营要点，从 daily_list 和 merged_events 自行提取所有数据。"""
    if not api_key:
        return None

    total_gmv = sum(dd["gmv_total"] for dd in daily_list)
    days_with_data = sum(1 for dd in daily_list if dd["gmv_total"] > 0)

    # 每日趋势
    trend_lines = []
    for dd in daily_list:
        roi_s = f"，ROI {dd['avg_roi']:.2f}" if dd.get("avg_roi") else ""
        trend_lines.append(f"- {dd['date']}（{dd['weekday']}）：GMV ¥{dd['gmv_total']:,.0f}{roi_s}")

    # 事件
    event_text = ""
    for cat in ["异常", "主播", "系数", "素材", "投放", "加量"]:
        items = merged_events.get(cat, [])
        if items:
            event_text += f"\n【{cat}】({len(items)}条)\n"
            for it in items[:5]:
                event_text += f"- {it}\n"

    # 告警
    alert_lines = []
    for dd in daily_list:
        for key in ["异常", "主播"]:
            for e in dd["events"].get(key, []):
                alert_lines.append(f"- [{dd['date']}] {key}: {e[:80]}")
    alert_text = "\n".join(alert_lines) if alert_lines else "无"

    # 运营/主播排行
    op_map, anchor_map = {}, {}
    for dd in daily_list:
        for sd in dd["slot_details"]:
            if sd["gmv"] <= 0:
                continue
            for op in [x.strip() for x in sd["operator"].replace("，", ",").split(",") if x.strip()]:
                if op not in op_map:
                    op_map[op] = {"gmv": 0, "slots": 0}
                op_map[op]["gmv"] += sd["gmv"]
                op_map[op]["slots"] += 1
            an = sd["anchor"]
            if an:
                if an not in anchor_map:
                    anchor_map[an] = {"gmv": 0, "slots": 0}
                anchor_map[an]["gmv"] += sd["gmv"]
                anchor_map[an]["slots"] += 1
    op_text = ", ".join(f"{n}(¥{v['gmv']:,.0f}/{v['slots']}场)"
                        for n, v in sorted(op_map.items(), key=lambda x: -x[1]["gmv"])[:5])
    an_text = ", ".join(f"{n}(¥{v['gmv']:,.0f}/{v['slots']}场)"
                        for n, v in sorted(anchor_map.items(), key=lambda x: -x[1]["gmv"])[:5])

    prompt = f"""根据以下 {start_date} 至 {end_date} 一周的直播运营数据，用 5-8 条简洁中文要点做周报总结。

周总 GMV：¥{total_gmv:,.0f}，有效天数 {days_with_data}/7
（若 GMV 全为 0 表示数据未录入，直接回复"本周数据未录入，暂无总结"）

每日趋势：
{chr(10).join(trend_lines)}

运营事件汇总：
{event_text if event_text else '本周无特殊记录'}

告警：
{alert_text}

运营 TOP5：{op_text}
主播 TOP5：{an_text}

重点关注：周整体评价、趋势变化（升/降/波动）、最值得关注的异常与风险、运营动作有效性、下周建议。
用 "- " 开头的中文要点输出，每条不超过 50 字。"""

    try:
        return _call_deepseek(prompt, api_key, model, 800)
    except Exception as e:
        return f"（AI 周报总结生成失败：{e}）"
