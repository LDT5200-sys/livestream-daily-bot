# -*- coding: utf-8 -*-
"""
Web 控制台：浏览器里预览日报/周报、趋势图、运营/主播汇总、告警区、一键推送、在线改设置。
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
from report import build_report, build_weekly_report, compute_weekly_analytics
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
        else:
            out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# ---------------- 页面框架 (CSS + HTML shell) ----------------
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
.btn:disabled{opacity:.5;cursor:wait}
.status{font-size:14px;color:var(--dim);min-height:20px;margin-left:4px}
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

/* ---- 告警区 ---- */
.alert-card{background:var(--redbg);border:1px solid var(--redline);border-radius:16px;padding:12px 26px 16px;margin-top:20px;box-shadow:0 12px 32px -20px rgba(192,57,43,0.2)}
.alert-card h2{color:var(--bad);font-family:"Noto Serif SC",serif;font-size:17px;margin:10px 0 8px}
.alert-card .alert-item{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid rgba(90,32,32,0.5)}
.alert-card .alert-item:last-child{border-bottom:none}
.alert-card .alert-tag{flex-shrink:0;font-size:11px;padding:2px 8px;border-radius:6px;font-weight:500}
.alert-card .alert-tag.abnormal{background:var(--bad);color:#fff}
.alert-card .alert-tag.status{background:#7b3f1a;color:#f0b27a}
.alert-card .alert-date{color:var(--dim);font-size:12px;white-space:nowrap}
.alert-card .alert-text{color:#f5cdcd;font-size:14px;line-height:1.5}

/* ---- 趋势图 ---- */
.chart-wrap{margin-top:16px}
.chart-bars{display:flex;gap:8px;align-items:flex-end;min-height:180px;padding-bottom:6px}
.chart-col{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;min-width:0}
.chart-bar{width:100%;max-width:80px;background:linear-gradient(180deg,var(--amber2),var(--amber));border-radius:8px 8px 4px 4px;min-height:4px;transition:height .4s ease}
.chart-bar.zero{background:var(--line)}
.chart-roi{font-size:12px;color:var(--dim);font-weight:500}
.chart-roi.high{color:var(--ok)}
.chart-label{font-size:12px;color:var(--dim);text-align:center;line-height:1.3}
.chart-label .wd{font-size:11px;opacity:.7}
.chart-label .dt{font-size:10px;opacity:.5}
.chart-gmv{font-size:11px;color:var(--amber);font-weight:500}

/* ---- 汇总表 ---- */
.summary-section{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
.summary-tbl{width:100%;border-collapse:collapse;font-size:13px}
.summary-tbl th{text-align:left;color:var(--dim);font-weight:500;padding:6px 10px;border-bottom:1px solid var(--line);font-size:12px}
.summary-tbl th.right{text-align:right}
.summary-tbl td{padding:7px 10px;border-bottom:1px solid rgba(58,49,39,0.5)}
.summary-tbl td.right{text-align:right;font-variant-numeric:tabular-nums}
.summary-tbl .rank{color:var(--dim);font-size:11px;width:24px}
.summary-tbl .highlight{color:var(--amber);font-weight:600}
.summary-tbl .muted{color:var(--dim)}
@media(max-width:700px){.summary-section{grid-template-columns:1fr}}

/* ---- 随页面隐藏/显示 ---- */
.week-only,.day-only{display:none}

textarea{width:100%;min-height:420px;background:#100d0a;color:#d8cdbd;border:1px solid var(--line);border-radius:12px;padding:16px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;line-height:1.7}
.hint{color:var(--dim);font-size:13px;margin:10px 0}
.targets{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.tg{font-size:12px;padding:4px 10px;border-radius:8px;background:var(--panel2);border:1px solid var(--line);color:var(--dim)}
</style></head><body><div class="wrap">
<header>
  <div class="brand">直播运营 · <b>日报台</b></div>
  <nav>__NAV__</nav>
</header>
__BODY__
</div></body></html>"""


def page(active, body):
    nav = (f'<a class="{"on" if active=="home" else ""}" href="/">控制台</a>'
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
                  for t in config.DINGTALK_TARGETS) or '<span class="tg">未配置钉钉机器人，去「设置」填</span>'
    body = f"""
    <div style="margin-top:18px">{badge}</div>
    <div class="bar">
      <input type="date" id="d" value="{today_str()}">
      <select id="mode" class="btn">
        <option value="day">单日</option>
        <option value="week" selected>周报</option>
      </select>
      <button class="btn" onclick="preview()">预览</button>
      <button class="btn primary" onclick="push()">推送到钉钉</button>
      <span id="st" class="status"></span>
    </div>
    <div class="targets">{tgs}</div>

    <!-- 告警区 -->
    <div id="alerts" class="alert-card" style="display:none">
      <h2>🚨 异常 & 主播状态告警</h2>
      <div id="alert-list"></div>
    </div>

    <!-- 趋势图 + 汇总表 -->
    <div id="analytics" style="display:none">
      <div class="card" style="padding-bottom:16px">
        <h2 style="margin-bottom:2px">📈 近 7 天 GMV / ROI 趋势</h2>
        <div class="chart-wrap">
          <div id="chart" class="chart-bars"></div>
        </div>
      </div>
      <div class="summary-section" id="summary"></div>
    </div>

    <!-- 日报/周报卡片 -->
    <div id="card" class="card"><div class="empty">点「预览」生成当日内容</div></div>

    <script>
    const st=document.getElementById('st'), card=document.getElementById('card');
    const alertsDiv=document.getElementById('alerts'), analyticsDiv=document.getElementById('analytics');
    const alertList=document.getElementById('alert-list'), chartDiv=document.getElementById('chart');
    const summaryDiv=document.getElementById('summary'), modeSel=document.getElementById('mode');

    function setSt(m,c){{st.className='status '+(c||'');st.textContent=m;}}

    function fmt(n){{return (n||0).toLocaleString('en-US',{{maximumFractionDigits:0}});}}
    function fmtRoi(r){{return r!=null ? r.toFixed(2) : '-';}}

    // ---- 告警 ----
    function renderAlerts(alerts){{
      if(!alerts||!alerts.length){{alertsDiv.style.display='none';return;}}
      alertsDiv.style.display='block';
      alertList.innerHTML=alerts.map(a=>'<div class="alert-item">'
        +'<span class="alert-tag '+(a.type==='异常'?'abnormal':'status')+'">'+(a.type==='异常'?'⚠ 异常':'🎤 主播')+'</span>'
        +'<span class="alert-date">'+a.date+'</span>'
        +'<div class="alert-text">'+a.text.replace(/</g,'&lt;')+'</div>'
        +'</div>').join('');
    }}

    // ---- 趋势图 ----
    function renderChart(trends){{
      var maxGmv=Math.max.apply(null,trends.map(function(t){{return t.gmv;}}))||1;
      chartDiv.innerHTML=trends.map(function(t){{
        var h=t.gmv>0?Math.max(8,(t.gmv/maxGmv)*100):4;
        var barClass=t.gmv>0?'chart-bar':'chart-bar zero';
        var roiClass=t.roi!=null&&t.roi>=8?'chart-roi high':'chart-roi';
        return '<div class="chart-col">'
          +'<div class="chart-gmv">'+(t.gmv>0?'¥'+fmt(t.gmv).substring(0,6)+'k':'')+'</div>'
          +'<div class="'+roiClass+'">'+(t.roi!=null?fmtRoi(t.roi):'')+'</div>'
          +'<div class="'+barClass+'" style="height:'+h+'%"></div>'
          +'<div class="chart-label"><span class="wd">'+t.weekday+'</span><br><span class="dt">'+t.date.substring(5)+'</span></div>'
          +'</div>';
      }}).join('');
    }}

    // ---- 汇总表 ----
    function renderSummary(op,an){{
      var opRows=op.map(function(o,i){{return '<tr><td class="rank">'+(i+1)+'</td><td>'+o.name+'</td><td class="right highlight">¥'+fmt(o.gmv)+'</td><td class="right muted">'+o.slots+'场</td><td class="right muted">ROI '+fmtRoi(o.avg_roi)+'</td></tr>';}}).join('');
      var anRows=an.map(function(a,i){{return '<tr><td class="rank">'+(i+1)+'</td><td>'+a.name+'</td><td class="right highlight">¥'+fmt(a.gmv)+'</td><td class="right muted">'+a.slots+'场</td><td class="right muted">ROI '+fmtRoi(a.avg_roi)+'</td></tr>';}}).join('');
      summaryDiv.innerHTML='<div class="card" style="padding-bottom:16px"><h2 style="margin-bottom:6px">👤 运营排行</h2><table class="summary-tbl"><thead><tr><th></th><th>运营</th><th class="right">GMV 合计</th><th class="right">场次</th><th class="right">平均 ROI</th></tr></thead><tbody>'+opRows+'</tbody></table></div>'
        +'<div class="card" style="padding-bottom:16px"><h2 style="margin-bottom:6px">🎤 主播排行</h2><table class="summary-tbl"><thead><tr><th></th><th>主播</th><th class="right">GMV 合计</th><th class="right">场次</th><th class="right">平均 ROI</th></tr></thead><tbody>'+anRows+'</tbody></table></div>';
    }}

    // ---- 主流程 ----
    async function preview(){{
      var isWeek=modeSel.value==='week';
      var d=document.getElementById('d').value;
      setSt('生成中…');
      try{{
        var w=isWeek?'&week=1':'';
        var r=await fetch('/api/report?date='+d+w);var j=await r.json();
        if(!j.ok){{setSt(j.error,'err');return;}}
        card.innerHTML=j.html;
        analyticsDiv.style.display=isWeek?'block':'none';
        alertsDiv.style.display='none';
        if(isWeek){{
          var a=await fetch('/api/analytics?date='+d);var aj=await a.json();
          if(aj.ok){{
            renderChart(aj.trends);
            renderSummary(aj.operator_summary,aj.anchor_summary);
            renderAlerts(aj.alerts);
          }}
        }}
        setSt('已生成 '+d+(j.demo?'（示例数据）':''),'ok');
      }}catch(e){{setSt(''+e,'err');}}
    }}

    async function push(){{
      var isWeek=modeSel.value==='week';
      if(!confirm('确认把该'+(isWeek?'周':'日')+'报推送到所有已启用的钉钉群？'))return;
      setSt('推送中…');
      try{{
        var d=document.getElementById('d').value;
        var r=await fetch('/api/push',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{date:d,week:isWeek}})}});
        var j=await r.json();
        if(!j.ok){{setSt(j.error,'err');return;}}
        setSt('已推送：'+j.results.map(function(x){{return x.name+(x.ok?'✓':'✗');}}).join('  '), 'ok');
      }}catch(e){{setSt(''+e,'err');}}
    }}

    // 模式切换时自动刷新
    modeSel.onchange=preview;
    preview();
    </script>
    """
    return page("home", body)


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


@app.route("/api/analytics")
def api_analytics():
    """返回结构化分析数据：趋势、运营/主播汇总、告警。"""
    date = request.args.get("date") or today_str()
    demo = request.args.get("demo") == "1"
    try:
        (follow, data), _ = fetch_rows(date, demo)
        end_date = date
        start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
        ana = compute_weekly_analytics(start_date, end_date, follow, data)
        return jsonify(ok=True, **ana)
    except Exception as e:
        return jsonify(ok=False, error=f"分析失败：{e}")


@app.route("/api/push", methods=["POST"])
def api_push():
    body = request.get_json(silent=True) or {}
    date = body.get("date") or today_str()
    demo = bool(body.get("demo"))
    week = bool(body.get("week"))
    if not config.DINGTALK_TARGETS:
        return jsonify(ok=False, error="未配置钉钉机器人，请到「设置」填 webhook")
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
        # 读取现有配置，保留未在表单中出现的段
        if SETTINGS_PATH.exists():
            cfg.read(SETTINGS_PATH, encoding="utf-8")
        for sec in ["feishu", "dingtalk", "ai", "general"]:
            if not cfg.has_section(sec):
                cfg.add_section(sec)
        # 飞书
        cfg.set("feishu", "app_id", request.form.get("feishu_app_id", "").strip())
        cfg.set("feishu", "app_secret", request.form.get("feishu_app_secret", "").strip())
        cfg.set("feishu", "app_token", request.form.get("feishu_app_token", "").strip())
        cfg.set("feishu", "wiki_node_token", request.form.get("feishu_wiki_node_token", "").strip())
        cfg.set("feishu", "follow_table_id", request.form.get("feishu_follow_table_id", "").strip())
        cfg.set("feishu", "data_table_id", request.form.get("feishu_data_table_id", "").strip())
        # 钉钉
        cfg.set("dingtalk", "webhook", request.form.get("dingtalk_webhook", "").strip())
        cfg.set("dingtalk", "secret", request.form.get("dingtalk_secret", "").strip())
        cfg.set("dingtalk", "at_mobiles", request.form.get("dingtalk_at_mobiles", "").strip())
        cfg.set("dingtalk", "at_all", request.form.get("dingtalk_at_all", "").strip())
        cfg.set("dingtalk", "enabled", "true")
        # AI
        cfg.set("ai", "api_key", request.form.get("ai_api_key", "").strip())
        cfg.set("ai", "model", request.form.get("ai_model", "deepseek-chat").strip())
        cfg.set("ai", "enabled", "true" if request.form.get("ai_enabled") else "false")
        # general
        cfg.set("general", "brand_name", request.form.get("brand_name", "秘纤").strip())
        cfg.set("general", "report_title", request.form.get("report_title", "直播日报").strip())
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)
        msg = "配置已保存，重启服务后生效。"

    # 读取当前值
    import config as cfg_mod
    # 重新加载以便读取最新值（避免缓存）
    import importlib
    importlib.reload(cfg_mod)

    def val(v):
        return html_mod.escape(v) if v else ""

    body = f"""
    <div style="margin-top:18px">
      <span class="badge live">表单式配置</span>
      <span style="color:var(--dim);font-size:13px;margin-left:10px">改完点保存，重启服务即可</span>
    </div>
    {f'<div class="status ok" style="margin:8px 0">{html_mod.escape(msg)}</div>' if msg else ''}
    <form method="post">
    <div class="card" style="padding-bottom:16px">
      <h3>📡 飞书</h3>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px">
        <div><label style="color:var(--dim);font-size:12px">App ID</label>
          <input name="feishu_app_id" value="{val(cfg_mod.FEISHU_APP_ID)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="cli_xxxxxxxx"></div>
        <div><label style="color:var(--dim);font-size:12px">App Secret</label>
          <input name="feishu_app_secret" value="{val(cfg_mod.FEISHU_APP_SECRET)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="xxxxxxxx"></div>
        <div><label style="color:var(--dim);font-size:12px">App Token（base链接 /base/ 后面那段）</label>
          <input name="feishu_app_token" value="{val(cfg_mod.FEISHU_APP_TOKEN)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="留空则用 wiki_node_token 解析"></div>
        <div><label style="color:var(--dim);font-size:12px">Wiki Node Token</label>
          <input name="feishu_wiki_node_token" value="{val(cfg_mod.FEISHU_WIKI_NODE_TOKEN)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="有 app_token 时留空"></div>
        <div><label style="color:var(--dim);font-size:12px">跟播记录表 ID</label>
          <input name="feishu_follow_table_id" value="{val(cfg_mod.FOLLOW_TABLE_ID)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="tblXXXX"></div>
        <div><label style="color:var(--dim);font-size:12px">直播数据表 ID</label>
          <input name="feishu_data_table_id" value="{val(cfg_mod.DATA_TABLE_ID)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="tblXXXX"></div>
      </div>
    </div>
    <div class="card" style="padding-bottom:16px">
      <h3>📣 钉钉机器人</h3>
      <div style="display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-top:8px">
        <div><label style="color:var(--dim);font-size:12px">Webhook 地址</label>
          <input name="dingtalk_webhook" value="{val(config.DINGTALK_TARGETS[0]['webhook'] if config.DINGTALK_TARGETS else '')}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="https://oapi.dingtalk.com/robot/send?access_token=xxx"></div>
        <div><label style="color:var(--dim);font-size:12px">加签 Secret</label>
          <input name="dingtalk_secret" value="{val(config.DINGTALK_TARGETS[0]['secret'] if config.DINGTALK_TARGETS else '')}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="SECxxx"></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">
        <div><label style="color:var(--dim);font-size:12px">@ 手机号（逗号分隔）</label>
          <input name="dingtalk_at_mobiles" value="{val(','.join(config.DINGTALK_TARGETS[0].get('at_mobiles',[])) if config.DINGTALK_TARGETS else '')}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="留空不@"></div>
        <div><label style="color:var(--dim);font-size:12px">@所有人</label>
          <select name="dingtalk_at_all" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px">
            <option value="false" {'selected' if not (config.DINGTALK_TARGETS and config.DINGTALK_TARGETS[0].get('at_all')) else ''}>关闭</option>
            <option value="true" {'selected' if config.DINGTALK_TARGETS and config.DINGTALK_TARGETS[0].get('at_all') else ''}>开启</option>
          </select></div>
      </div>
    </div>
    <div class="card" style="padding-bottom:16px">
      <h3>🤖 AI 智能总结</h3>
      <div style="display:grid;grid-template-columns:2fr 1fr 120px;gap:12px;margin-top:8px;align-items:end">
        <div><label style="color:var(--dim);font-size:12px">DeepSeek API Key</label>
          <input name="ai_api_key" value="{val(cfg_mod.AI_API_KEY)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="sk-xxx"></div>
        <div><label style="color:var(--dim);font-size:12px">模型</label>
          <input name="ai_model" value="{val(cfg_mod.AI_MODEL)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;font-family:monospace;margin-top:2px" placeholder="deepseek-chat"></div>
        <div style="padding-bottom:2px"><label style="display:flex;align-items:center;gap:6px;color:var(--dim);font-size:13px;cursor:pointer">
          <input type="checkbox" name="ai_enabled" {'checked' if cfg_mod.AI_ENABLED else ''} style="accent-color:var(--amber)"> 启用</label></div>
      </div>
    </div>
    <div class="card" style="padding-bottom:16px">
      <h3>⚙️ 通用</h3>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px">
        <div><label style="color:var(--dim);font-size:12px">品牌名称</label>
          <input name="brand_name" value="{val(cfg_mod.BRAND_NAME)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;margin-top:2px" placeholder="秘纤"></div>
        <div><label style="color:var(--dim);font-size:12px">报表标题</label>
          <input name="report_title" value="{val(cfg_mod.REPORT_TITLE)}" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:14px;margin-top:2px" placeholder="直播日报"></div>
      </div>
    </div>
    <div class="bar" style="margin-top:16px">
      <button class="btn primary" type="submit">💾 保存配置</button>
      <span style="color:var(--dim);font-size:13px">保存后需重启服务生效</span>
    </div>
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
    <p class="hint">这里就是「换机器人 / 换群 / 改密钥」的唯一入口。直接编辑下面的 settings.ini，保存后重启服务生效。
    想加群就复制一段 <code>[dingtalk_2]</code>；想停用某群把它的 <code>enabled</code> 改成 <code>false</code>。</p>
    <form method="post">
      <textarea name="content" spellcheck="false">{html_mod.escape(content)}</textarea>
      <div class="bar"><button class="btn primary" type="submit">保存 settings.ini</button></div>
    </form>
    """
    return page("settings", body)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5001)
    a = ap.parse_args()
    print(f"控制台已启动： http://{a.host}:{a.port}")
    app.run(host=a.host, port=a.port, debug=False)
