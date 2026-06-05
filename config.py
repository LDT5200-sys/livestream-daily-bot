# -*- coding: utf-8 -*-
"""
读取 settings.ini，对外暴露配置。
所有“会变”的东西（密钥、表ID、钉钉机器人）都在 settings.ini 里改，不用动这里。
也支持用环境变量覆盖：环境变量名 = 段名_键名 大写，如 DINGTALK_WEBHOOK、FEISHU_APP_ID。
"""
import os
import configparser
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
_cfg = configparser.ConfigParser()
_cfg.read(_HERE / "settings.ini", encoding="utf-8")


def _get(section, key, default=""):
    env_key = f"{section}_{key}".upper()
    if os.getenv(env_key):
        return os.getenv(env_key).strip()
    if _cfg.has_option(section, key):
        return _cfg.get(section, key).strip()
    return default


def _getbool(section, key, default=False):
    return _get(section, key, str(default)).lower() in ("1", "true", "yes", "y", "on", "是")


def _split(s):
    return [x.strip() for x in s.replace("，", ",").split(",") if x.strip()]


# ========================= 飞书 =========================
FEISHU_APP_ID          = _get("feishu", "app_id", "cli_xxxxxxxxxxxx")
FEISHU_APP_SECRET      = _get("feishu", "app_secret", "xxxxxxxxxxxxxxxx")
FEISHU_WIKI_NODE_TOKEN = _get("feishu", "wiki_node_token", "")
FEISHU_APP_TOKEN       = _get("feishu", "app_token", "")
FOLLOW_TABLE_ID        = _get("feishu", "follow_table_id", "tblXXXX_follow")
DATA_TABLE_ID          = _get("feishu", "data_table_id", "tblXXXX_data")

# ========================= 钉钉（可多个群）=========================
# 收集所有 [dingtalk] / [dingtalk_2] / [dingtalk_xxx] 段，enabled!=false 且填了 webhook 的都会播。
DINGTALK_TARGETS = []
for _sec in _cfg.sections():
    if _sec == "dingtalk" or _sec.startswith("dingtalk_"):
        if not _getbool(_sec, "enabled", True):
            continue
        _wh = _get(_sec, "webhook", "")
        if not _wh or "xxxx" in _wh:   # 占位符不算
            continue
        DINGTALK_TARGETS.append({
            "name": _sec,
            "webhook": _wh,
            "secret": _get(_sec, "secret", ""),
            "at_mobiles": _split(_get(_sec, "at_mobiles", "")),
            "at_all": _getbool(_sec, "at_all", False),
        })

# 兼容：没在 ini 里配，但用环境变量给了 DINGTALK_WEBHOOK，也能用
if not DINGTALK_TARGETS and os.getenv("DINGTALK_WEBHOOK"):
    DINGTALK_TARGETS.append({
        "name": "env",
        "webhook": os.getenv("DINGTALK_WEBHOOK"),
        "secret": os.getenv("DINGTALK_SECRET", ""),
        "at_mobiles": _split(os.getenv("DINGTALK_AT_MOBILES", "")),
        "at_all": os.getenv("DINGTALK_AT_ALL", "false").lower() in ("1", "true", "yes"),
    })

# ========================= 通用 =========================
TIMEZONE     = _get("general", "timezone", "Asia/Shanghai")
REPORT_TITLE = _get("general", "report_title", "直播日报")
BRAND_NAME   = _get("general", "brand_name", "秘纤")
SLOT_ORDER   = ["A", "B", "C", "D", "E"]
SLOT_TIME    = {"A": "06-10", "B": "10-14", "C": "14-18", "D": "18-22", "E": "22-02"}

# ========================= AI 总结 =========================
AI_API_KEY  = _get("ai", "api_key", "")
AI_MODEL    = _get("ai", "model", "deepseek-chat")
AI_ENABLED  = _getbool("ai", "enabled", True) and bool(AI_API_KEY)

# ========================= 字段映射（一次性对齐，不常改，故留在代码里）=========================
# 左边是程序逻辑名（别动），右边换成你飞书表里真实的列名。
FOLLOW_FIELDS = {
    "date":                   "时间",
    "slot":                   "班次",
    "operator":               "跟播运营",
    "anchor":                 "主播",
    "coefficient":            "系数调整记录",
    "material":               "流量判断（本场流量如何、素材是否有变化）",
    "delivery":               "运营跟播记录（跟播动作、异常处理）",
    "volume":                 "加量/控量动作、时间、原因",
    "abnormal":               "主播身体是否异常影响效率",
    "abnormal_note":          "主播身体异常说明",
    "conv_impact":            "兼职班次是否有影响",
    "review_note":            "主播需求、下次调整方向",
    "anchor_status_abnormal": "主播身体是否异常影响效率",
    "anchor_status_note":     "主播身体异常说明",
    "platform_activity":      "平台活动记录",
}

DATA_FIELDS = {
    "date":       "日期",
    "slot":       "班次",
    "time_range": "时段",
    "operator":   "运营姓名",
    "anchor":     "主播姓名",
    "gmv":        "场次渠道整体用户支付金额",
    "roi":        "千川ROI",
    "conv_rate":  "曝光-成交转化率(人数)",
}
