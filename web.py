# -*- coding: utf-8 -*-
"""
Web 控制台：月历视图 + 日报详情 + 表单配置 + 钉钉推送。
运行：
    python web.py                      # 默认 http://127.0.0.1:5001
    python web.py --host 0.0.0.0 --port 8080
"""
import re
import html as html_mod
import argparse
import pathlib
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify

import config
from report import build_report, build_weekly_report, build_monthly_calendar
from dingtalk import send_markdown
from demo import sample_rows

app = Flask(__name__)
SETTINGS_PATH = pathlib.Path(__file__).resolve().parent / "settings.ini"


# ---------------- 工具 ----------------
def today_str():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def feishu_configured():
    return "xxxx" not in (config.FEISHU_APP_ID + config.FEISHU_APP_SECRET)


def fetch_rows(date, demo):
    if demo or not feishu_configured():
        return sample_rows(), True
    from feishu import FeishuClient
    fs = FeishuClient(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
    app_token = config.FEISHU_APP_TOKEN or fs.resolve_app_token(config.FEISHU_WIKI_NODE_TOKEN)
    follow = fs.fetch_records(app_token, config.FOLLOW_TABLE_ID)
    data = follow if config.DATA_TABLE_ID == config.FOLLOW_TABLE_ID \
        else fs.fetch_records(app_token, config.DATA_TABLE_ID)
    return (follow, data), False


def render_md(text):
    def inline(s):
        s = html_mod.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
        return s
    out, in_list = [], False
    for raw in text.split("\n"):
        line = raw.rstrip()
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>"); in_list = False
        if not line:
            continue
        if line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif line.startswith("|"):
            # markdown table detection
            out.append(f"<p class=\"tbl-row\">{inline(line)}</p>")
        else:
            out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# ---------------- 页面框架 ----------------
BASE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>直播日报控制台</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;700&family=Noto+Sans+SC:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#15120f;--panel:#1f1b17;--panel2:#272019;--line:#3a3127;--ink:#ece5db;--dim:#9c8f7e;--amber:#f5a623;--amber2:#ff8a3d;--ok:#5fb87a;--bad:#e1604f;--red:#c0392b;--redbg:#1f0f0f;--redline:#5a2020;}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#2a2017 0,var(--bg) 55%);color:var(--ink);font-family:"Noto Sans SC",system-ui,sans-serif;line-height:1.6}
.wrap{max-width:960px;margin:0 auto;padding:0 22px 64px}
header{display:flex;align-items:center;justify-content:space-between;padding:26px 0 20px;border-bottom:1px solid var(--line)}
.brand{font-family:"Noto Serif SC",serif;font-weight:700;font-size:22px;letter-spacing:.5px}
.brand b{color:var(--amber)}
nav a{color:var(--dim);text-decoration:none;margin-left:18px;font-size:14px;padding-bottom:4px;border-bottom:2px solid transparent}
nav a.on{color:var(--ink);border-color:var(--amber)}
.badge{display:inline-block;font-size:12px;padding:3px 10px;border-radius:999px;border:1px solid var(--line)}
.badge.live{color:var(--ok);border-color:#2f5d3f;background:#15241a}
.badge.demo{color:var(--amber);border-color:#5d4a23;background:#241d12}
.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:22px 0}
input[type=date]{background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:10px;padding:9px 12px;font-size:15px;font-family:inherit}
select.btn{background:#2a231b;color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:9px 14px;font-size:15px;font-family:inherit;cursor:pointer}
button{cursor:pointer;border:none;border-radius:10px;padding:10px 18px;font-size:15px;font-family:inherit;font-weight:500}
.btn{background:#2a231b;color:var(--ink);border:1px solid var(--line)}
.btn:hover{border-color:var(--amber)}
.btn.primary{background:linear-gradient(120deg,var(--amber),var(--amber2));color:#241a08;border:none}
.btn.primary:hover{filter:brightness(1.06)}
.status{font-size:14px;color:var(--dim);min-height:20px;margin-left:8px}
.status.ok{color:var(--ok)} .status.err{color:var(--bad)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:6px 26px 20px;margin-top:20px;box-shadow:0 18px 40px -28px #000}
.card h2{font-family:"Noto Serif SC",serif;font-size:19px;margin:22px 0 6px}
.card h3{font-size:14px;color:var(--amber);margin:16px 0 4px;font-weight:500}
.card p{margin:6px 0}
.card ul{margin:6px 0 6px;padding-left:20px}
.card li{margin:3px 0}
.card blockquote{margin:16px 0 0;padding:8px 14px;border-left:3px solid var(--line);color:var(--dim);font-size:13px}
.card strong{color:#fff}
.empty{color:var(--dim);padding:40px 0;text-align:center}
textarea{width:100%;min-height:420px;background:#100d0a;color:#d8cdbd;border:1px solid var(--line);border-radius:12px;padding:16px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;line-height:1.7}
.hint{color:var(--dim);font-size:13px;margin:10px 0}
.targets{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.tg{font-size:12px;padding:4px 10px;border-radius:8px;background:var(--panel2);border:1px solid var(--line);color:var(--dim)}

/* ---- 月历 ---- */
.calendar{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
.cal-header{text-align:center;font-size:12px;color:var(--dim);padding:6px 0;font-weight:500}
.cal-cell{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:7px 6px;min-height:78px;cursor:pointer;transition:border .15s;display:flex;flex-direction:column;gap:2px}
.cal-cell:hover{border-color:var(--amber)}
.cal-cell.today{border-color:var(--amber);box-shadow:0 0 10px -2px rgba(245,166,35,0.18)}
.cal-cell.alert{border-color:rgba(192,57,43,0.5);background:rgba(192,57,43,0.08)}
.cal-cell.active{border-color:var(--amber2);background:var(--panel)}
.cal-cell.placeholder{background:transparent;border-color:transparent;cursor:default;min-height:0}
.cal-cell .cal-num{font-size:13px;font-weight:600;line-height:1}
.cal-cell .cal-gmv{font-size:12px;font-weight:700;color:var(--amber)}
.cal-cell .cal-gmv.zero{color:var(--dim);font-weight:400}
.cal-cell .cal-tags{font-size:10px;letter-spacing:1px}
.cal-cell .cal-note{font-size:9px;color:var(--dim);line-height:1.2;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.month-bar{display:flex;gap:10px;align-items:center;font-size:18px;font-weight:700;font-family:"Noto Serif SC",serif}
.month-bar button{background:none;border:1px solid var(--line);color:var(--ink);cursor:pointer;border-radius:8px;padding:4px 10px;font-size:14px}
.month-bar button:hover{border-color:var(--amber);color:var(--amber)}
.detail-panel{display:none;margin-top:20px}

/* ---- 日报内容（table等）---- */
.tbl-row{font-family:ui-monospace,monospace;font-size:12px;color:var(--dim);margin:2px 0}
</style></head><body><div class="wrap">
<header>
  <div class="brand">直播运营 · <b>日报台</b></div>
  <nav>__NAV__</nav>
</header>
__BODY__
</div></body></html>"""


def page(active, body):
    nav = (f'<a class="{"on" if active=="home" else ""}" href="/">月历</a>'
           f'<a class="{"on" if active=="config" else ""}" href="/config">配置</a>'
           f'<a class="{"on" if active=="settings" else ""}" href="/settings">高级</a>')
    return BASE.replace("__NAV__", nav).replace("__BODY__", body)


# ---------------- 路由 ----------------
@app.route("/")
def home():
    mode = "live" if feishu_configured() else "demo"
    badge = ('<span class="badge live">实盘 · 已连飞书</span>' if mode == "live"
             else '<span class="badge demo">演示模式 · 未配飞书，用示例数据</span>')
    tgs = "".join(f'<span class="tg">📣 {t["name"]}{" · 加签" if t["secret"] else ""}</span>'
                  for t in config.DINGTALK_TARGETS) or '<span class="tg">未配置钉钉机器人，去「配置」填</span>'
    now = datetime.now(timezone(timedelta(hours=8)))
    body = f"""
    <div style="margin-top:18px">{badge}</div>
    <div class="targets" style="margin-bottom:16px">{tgs}</div>

    <!-- 月份导航 -->
    <div class="month-bar" style="margin:18px 0 14px">
      <button onclick="prevMonth()">‹</button>
      <span id="monthLabel">{now.year}年{now.month}月</span>
      <button onclick="nextMonth()">›</button>
      <button class="btn primary" style="margin-left:auto;font-size:13px" onclick="pushDay()">📤 推送钉钉</button>
      <span id="st" class="status"></span>
    </div>

    <!-- 月历 -->
    <div class="card" style="padding:10px 14px 14px">
      <div id="calHeaders" style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:4px"></div>
      <div id="calendar" class="calendar"></div>
    </div>

    <!-- 日报详情 -->
    <div id="detail" class="card detail-panel"></div>

    <script>
    var st=document.getElementById('st'),calDiv=document.getElementById('calendar');
    var calHdr=document.getElementById('calHeaders'),ml=document.getElementById('monthLabel');
    var detail=document.getElementById('detail');
    var curYear={now.year},curMonth={now.month};
    var today='{today_str()}';
    var selDate=null;
    var WK=['一','二','三','四','五','六','日'];

    function setSt(m,c){{st.className='status '+(c||'');st.textContent=m;}}
    function fmt(n){{return (n||0).toLocaleString('en-US',{{maximumFractionDigits:0}});}}

    calHdr.innerHTML=WK.map(function(w){{return '<div class="cal-header">'+w+'</div>';}}).join('');

    async function loadMonth(){{
      ml.textContent=curYear+'年'+curMonth+'月';
      try{{
        var r=await fetch('/api/calendar?year='+curYear+'&month='+curMonth);
        var j=await r.json();
        if(!j.ok){{setSt(j.error,'err');return;}}
        var cells=[];
        for(var i=0;i<j.first_weekday;i++) cells.push('<div class="cal-cell placeholder"></div>');
        j.days.forEach(function(d){{
          var cls=['cal-cell'];
          if(d.date==today) cls.push('today');
          if(d.has_alert) cls.push('alert');
          if(d.date==selDate) cls.push('active');
          var gmvCls=d.gmv>0?'cal-gmv':'cal-gmv zero';
          var gmvTxt=d.gmv>0?'¥'+fmt(d.gmv):'—';
          var tags=d.tags?d.tags.join(' '):'';
          var note=d.highlight?d.highlight.substring(0,28):'';
          cells.push('<div class="'+cls.join(' ')+'" data-date="'+d.date+'">'
            +'<div class="cal-num">'+d.day+'</div>'
            +'<div class="'+gmvCls+'">'+gmvTxt+'</div>'
            +'<div class="cal-tags">'+tags+'</div>'
            +'<div class="cal-note">'+note+'</div>'
            +'</div>');
        }});
        calDiv.innerHTML=cells.join('');
        // 事件委托：点格子打开日报
        Array.from(calDiv.querySelectorAll('.cal-cell[data-date]')).forEach(function(el){{
          el.addEventListener('click',function(){{openDay(this.getAttribute('data-date'));}});
        }});
      }}catch(e){{setSt(''+e,'err');}}
    }}

    async function openDay(date){{
      selDate=date;
      setSt('加载中…');
      try{{
        var r=await fetch('/api/report?date='+date);var j=await r.json();
        if(!j.ok){{setSt(j.error,'err');return;}}
        detail.style.display='block';
        detail.innerHTML='<div style="display:flex;justify-content:space-between;align-items:center"><h2 style="margin:0">'+j.title+'</h2><button class="btn" id="closeDetail" style="font-size:12px">✕ 关闭</button></div>'+j.html;
        document.getElementById('closeDetail').addEventListener('click',function(){{detail.style.display='none';selDate=null;loadMonth();}});
        detail.scrollIntoView({{behavior:'smooth'}});
        setSt('已加载 '+date,'ok');
        loadMonth();
      }}catch(e){{setSt(''+e,'err');}}
    }}

    async function pushDay(){{
      var d=selDate||today;
      if(!confirm('确认把 '+d+' 的日报推送到钉钉？'))return;
      setSt('推送中…');
      try{{
        var r=await fetch('/api/push',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{date:d}})}});
        var j=await r.json();
        if(!j.ok){{setSt(j.error,'err');return;}}
        setSt('已推送', 'ok');
      }}catch(e){{setSt(''+e,'err');}}
    }}

    function prevMonth(){{curMonth--;if(curMonth<1){{curYear--;curMonth=12;}}selDate=null;detail.style.display='none';loadMonth();}}
    function nextMonth(){{curMonth++;if(curMonth>12){{curYear++;curMonth=1;}}selDate=null;detail.style.display='none';loadMonth();}}
    loadMonth();
    </script>
    """
    return page("home", body)


@app.route("/api/calendar")
def api_calendar():
    """返回月历数据。"""
    year = int(request.args.get("year") or datetime.now(timezone(timedelta(hours=8))).year)
    month = int(request.args.get("month") or datetime.now(timezone(timedelta(hours=8))).month)
    demo = request.args.get("demo") == "1"
    try:
        (follow, data), _ = fetch_rows(today_str(), demo)
        cal = build_monthly_calendar(year, month, follow, data)
        return jsonify(ok=True, **cal)
    except Exception as e:
        return jsonify(ok=False, error=f"读取失败：{e}")


@app.route("/api/report")
def api_report():
    date = request.args.get("date") or today_str()
    demo = request.args.get("demo") == "1"
    week = request.args.get("week") == "1"
    try:
        (follow, data), used_demo = fetch_rows(date, demo)
        if week:
            end_date = date
            start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
            title, text = build_weekly_report(start_date, end_date, follow, data)
        else:
            title, text = build_report(date, follow, data)
        return jsonify(ok=True, title=title, html=render_md(text), demo=used_demo)
    except Exception as e:
        return jsonify(ok=False, error=f"读取/生成失败：{e}")


@app.route("/api/push", methods=["POST"])
def api_push():
    body = request.get_json(silent=True) or {}
    date = body.get("date") or today_str()
    demo = bool(body.get("demo"))
    week = bool(body.get("week"))
    if not config.DINGTALK_TARGETS:
        return jsonify(ok=False, error="未配置钉钉机器人，请到「配置」填 webhook")
    try:
        (follow, data), _ = fetch_rows(date, demo)
        if week:
            start_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
            title, text = build_weekly_report(start_date, date, follow, data)
        else:
            title, text = build_report(date, follow, data)
    except Exception as e:
        return jsonify(ok=False, error=f"生成失败：{e}")
    results = []
    for t in config.DINGTALK_TARGETS:
        try:
            send_markdown(t["webhook"], t["secret"], title, text, t["at_mobiles"], t["at_all"])
            results.append({"name": t["name"], "ok": True})
        except Exception as e:
            results.append({"name": t["name"], "ok": False, "msg": str(e)})
    return jsonify(ok=True, results=results)


@app.route("/config", methods=["GET", "POST"])
def config_page():
    import configparser
    msg = ""
    if request.method == "POST":
        cfg = configparser.ConfigParser()
        if SETTINGS_PATH.exists():
            cfg.read(SETTINGS_PATH, encoding="utf-8")
        for sec in ["feishu", "dingtalk", "ai", "general"]:
            if not cfg.has_section(sec):
                cfg.add_section(sec)
        cfg.set("feishu", "app_id", request.form.get("feishu_app_id", "").strip())
        cfg.set("feishu", "app_secret", request.form.get("feishu_app_secret", "").strip())
        cfg.set("feishu", "app_token", request.form.get("feishu_app_token", "").strip())
        cfg.set("feishu", "wiki_node_token", request.form.get("feishu_wiki_node_token", "").strip())
        cfg.set("feishu", "follow_table_id", request.form.get("feishu_follow_table_id", "").strip())
        cfg.set("feishu", "data_table_id", request.form.get("feishu_data_table_id", "").strip())
        cfg.set("dingtalk", "webhook", request.form.get("dingtalk_webhook", "").strip())
        cfg.set("dingtalk", "secret", request.form.get("dingtalk_secret", "").strip())
        cfg.set("dingtalk", "at_mobiles", request.form.get("dingtalk_at_mobiles", "").strip())
        cfg.set("dingtalk", "at_all", request.form.get("dingtalk_at_all", "").strip())
        cfg.set("dingtalk", "enabled", "true")
        cfg.set("ai", "api_key", request.form.get("ai_api_key", "").strip())
        cfg.set("ai", "model", request.form.get("ai_model", "deepseek-chat").strip())
        cfg.set("ai", "enabled", "true" if request.form.get("ai_enabled") else "false")
        cfg.set("general", "brand_name", request.form.get("brand_name", "秘纤").strip())
        cfg.set("general", "report_title", request.form.get("report_title", "直播日报").strip())
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)
        msg = "配置已保存，重启服务后生效。"

    import importlib
    importlib.reload(config)

    def val(v):
        return html_mod.escape(v) if v else ""

    body = f"""
    <div style="margin-top:18px">
      <span class="badge live">表单式配置</span>
      <span style="color:var(--dim);font-size:13px;margin-left:10px">改完点保存，重启服务即可</span>
    </div>
    {f'<div class="status ok" style="margin:8px 0">{html_mod.escape(msg)}</div>' if msg else ''}
    <form method="post">
    <div class="card" style="padding-bottom:16px"><h3>📡 飞书</h3><div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px">
    <div><label style="color:var(--dim);font-size:12px">App ID</label><input name="feishu_app_id" value="{val(config.FEISHU_APP_ID)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px"></div>
    <div><label style="color:var(--dim);font-size:12px">App Secret</label><input name="feishu_app_secret" value="{val(config.FEISHU_APP_SECRET)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px"></div>
    <div><label style="color:var(--dim);font-size:12px">App Token（base链接 /base/ 后面那段）</label><input name="feishu_app_token" value="{val(config.FEISHU_APP_TOKEN)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px"></div>
    <div><label style="color:var(--dim);font-size:12px">跟播记录表 ID</label><input name="feishu_follow_table_id" value="{val(config.FOLLOW_TABLE_ID)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px"></div>
    <div><label style="color:var(--dim);font-size:12px">直播数据表 ID</label><input name="feishu_data_table_id" value="{val(config.DATA_TABLE_ID)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px"></div>
    </div></div>
    <div class="card" style="padding-bottom:16px"><h3>📣 钉钉机器人</h3><div style="display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-top:8px">
    <div><label style="color:var(--dim);font-size:12px">Webhook</label><input name="dingtalk_webhook" value="{val(config.DINGTALK_TARGETS[0]['webhook'] if config.DINGTALK_TARGETS else '')}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px"></div>
    <div><label style="color:var(--dim);font-size:12px">加签 Secret</label><input name="dingtalk_secret" value="{val(config.DINGTALK_TARGETS[0]['secret'] if config.DINGTALK_TARGETS else '')}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px"></div>
    </div></div>
    <div class="card" style="padding-bottom:16px"><h3>🤖 AI 智能总结</h3><div style="display:grid;grid-template-columns:2fr 1fr 100px;gap:12px;margin-top:8px;align-items:end">
    <div><label style="color:var(--dim);font-size:12px">DeepSeek API Key</label><input name="ai_api_key" value="{val(config.AI_API_KEY)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px"></div>
    <div><label style="color:var(--dim);font-size:12px">模型</label><input name="ai_model" value="{val(config.AI_MODEL)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px"></div>
    <div style="padding-bottom:2px"><label style="display:flex;align-items:center;gap:6px;color:var(--dim);font-size:13px;cursor:pointer"><input type="checkbox" name="ai_enabled" {'checked' if config.AI_ENABLED else ''} style="accent-color:var(--amber)"> 启用</label></div>
    </div></div>
    <div class="card" style="padding-bottom:16px"><h3>⚙️ 通用</h3><div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px">
    <div><label style="color:var(--dim);font-size:12px">品牌名称</label><input name="brand_name" value="{val(config.BRAND_NAME)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;margin-top:2px"></div>
    <div><label style="color:var(--dim);font-size:12px">报表标题</label><input name="report_title" value="{val(config.REPORT_TITLE)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;margin-top:2px"></div>
    </div></div>
    <div class="bar" style="margin-top:16px"><button class="btn primary" type="submit">💾 保存配置</button><span style="color:var(--dim);font-size:13px">保存后需重启服务生效</span></div>
    </form>
    """
    return page("config", body)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    msg = ""
    if request.method == "POST":
        SETTINGS_PATH.write_text(request.form.get("content", ""), encoding="utf-8")
        msg = "已保存。改了机器人/密钥后，重启服务即可生效。"
    content = SETTINGS_PATH.read_text(encoding="utf-8") if SETTINGS_PATH.exists() else ""
    note = ('<span class="badge live">飞书已配置</span>' if feishu_configured()
            else '<span class="badge demo">飞书未配置</span>')
    saved = f'<div class="status ok" style="margin:8px 0">{html_mod.escape(msg)}</div>' if msg else ""
    body = f"""
    <div style="margin-top:18px">{note}</div>
    {saved}
    <p class="hint">直接编辑 settings.ini 原始内容</p>
    <form method="post">
      <textarea name="content" spellcheck="false">{html_mod.escape(content)}</textarea>
      <div class="bar"><button class="btn primary" type="submit">保存</button></div>
    </form>
    """
    return page("settings", body)


if __name__ == "__main__":
    import socket, subprocess
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5001)
    a = ap.parse_args()

    # 端口冲突检测
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(("127.0.0.1", a.port))
    sock.close()
    if result == 0:
        try:
            out = subprocess.check_output(["lsof", "-i", f":{a.port}", "-P", "-n"], stderr=subprocess.STDOUT, timeout=5).decode()
            lines = out.strip().split("\n")
            if len(lines) > 1:
                parts = lines[1].split()
                proc, pid = (parts[0], parts[1]) if len(parts) > 1 else ("?", "?")
                print(f"\n⚠️  端口 {a.port} 已被占用：{proc}（PID {pid}）")
                print(f"   换端口：python web.py --port {a.port + 1}\n")
        except Exception:
            print(f"\n⚠️  端口 {a.port} 已被占用，请换端口：python web.py --port {a.port + 1}\n")

    print(f"控制台已启动： http://{a.host}:{a.port}")
    app.run(host=a.host, port=a.port, debug=False)
