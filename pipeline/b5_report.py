"""B5 — Generate standalone HTML report from B4 classified data."""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Group / Sub-issue taxonomy ────────────────────────────────────────────────

GROUP_META = [
    {"id": "giao_dich", "name": "Giao dịch và tiền", "emoji": "💰",
     "accent": "#2563eb", "bg": "#dbeafe", "tc": "#1e40af",
     "labels": ["Hoàn tiền", "Tự động trừ tiền", "Nạp tiền / Gói data", "Chưa nhận dịch vụ", "Chuyển khoản lỗi"]},
    {"id": "cskh", "name": "CSKH", "emoji": "🎧",
     "accent": "#059669", "bg": "#dcfce7", "tc": "#065f46",
     "labels": ["Khó kết nối nhân viên", "Phản hồi chậm / Chưa xử lý"]},
    {"id": "chatbot", "name": "Chatbot", "emoji": "🤖",
     "accent": "#7c3aed", "bg": "#ede9fe", "tc": "#5b21b6",
     "labels": ["Bot không giải quyết"]},
    {"id": "tinh_nang", "name": "Tính năng", "emoji": "⚙️",
     "accent": "#d97706", "bg": "#fef9c3", "tc": "#92400e",
     "labels": ["Xác thực / eKYC", "Vay tiền / Ví trả sau", "Bảo mật / Tài khoản",
                "Hủy dịch vụ", "Thay đổi thông tin", "Tiết kiệm / Sinh lời",
                "Ưu đãi / Voucher", "Tính năng app lỗi"]},
    {"id": "feedback", "name": "Feedback tiêu cực", "emoji": "😤",
     "accent": "#ea580c", "bg": "#ffedd5", "tc": "#9a3412",
     "labels": ["Feedback tiêu cực", "Chửi bới"]},
    {"id": "khac", "name": "Khác", "emoji": "📋",
     "accent": "#64748b", "bg": "#f1f5f9", "tc": "#334155",
     "labels": ["Khác / Vô nghĩa", "Khác / Vấn đề khác"]},
]

SUBS_META = [
    {"g": "Giao dịch và tiền", "s": "Hoàn tiền",          "labels": ["Hoàn tiền"],           "bold": True},
    {"g": "Giao dịch và tiền", "s": "Tự động trừ tiền",    "labels": ["Tự động trừ tiền"],    "bold": True},
    {"g": "Giao dịch và tiền", "s": "Chuyển khoản lỗi",    "labels": ["Chuyển khoản lỗi"],    "bold": False},
    {"g": "Giao dịch và tiền", "s": "Nạp tiền / Gói data", "labels": ["Nạp tiền / Gói data"], "bold": False},
    {"g": "Giao dịch và tiền", "s": "Chưa nhận dịch vụ",   "labels": ["Chưa nhận dịch vụ"],   "bold": False},
    {"g": "CSKH", "s": "Phản hồi chậm / Chưa xử lý", "labels": ["Phản hồi chậm / Chưa xử lý"], "bold": True},
    {"g": "CSKH", "s": "Khó kết nối nhân viên",       "labels": ["Khó kết nối nhân viên"],       "bold": True},
    {"g": "Chatbot", "s": "Bot không giải quyết", "labels": ["Bot không giải quyết"], "bold": True},
    {"g": "Tính năng", "s": "Vay tiền / Ví trả sau", "labels": ["Vay tiền / Ví trả sau"], "bold": True},
    {"g": "Tính năng", "s": "Tính năng app lỗi",     "labels": ["Tính năng app lỗi"],     "bold": False},
    {"g": "Tính năng", "s": "Xác thực / eKYC",       "labels": ["Xác thực / eKYC"],       "bold": False},
    {"g": "Tính năng", "s": "Bảo mật / Tài khoản",   "labels": ["Bảo mật / Tài khoản"],   "bold": False},
    {"g": "Tính năng", "s": "Hủy dịch vụ",           "labels": ["Hủy dịch vụ"],           "bold": False},
    {"g": "Tính năng", "s": "Thay đổi thông tin",     "labels": ["Thay đổi thông tin"],     "bold": False},
    {"g": "Tính năng", "s": "Tiết kiệm / Sinh lời",   "labels": ["Tiết kiệm / Sinh lời"],   "bold": False},
    {"g": "Tính năng", "s": "Ưu đãi / Voucher",       "labels": ["Ưu đãi / Voucher"],       "bold": False},
    {"g": "Feedback tiêu cực", "s": "Chửi bới",             "labels": ["Chửi bới"],           "bold": True},
    {"g": "Feedback tiêu cực", "s": "Không hài lòng chung", "labels": ["Feedback tiêu cực"], "bold": False},
    {"g": "Khác", "s": "Vấn đề không rõ", "labels": ["Khác / Vô nghĩa", "Khác / Vấn đề khác"], "bold": False},
]

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CSAT REPORT {{PERIOD}}</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#f8fafc;--surface:#fff;--border:#e2e8f0;--border-light:#f1f5f9;
  --text-1:#0f172a;--text-2:#475569;--text-3:#94a3b8;
  --blue-50:#eff6ff;--blue-100:#dbeafe;--blue-600:#2563eb;
  --green-50:#f0fdf4;--green-600:#16a34a;
  --red-50:#fef2f2;--red-600:#dc2626;
  --radius:12px;--shadow:0 1px 3px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.04);
}
body{background:var(--bg);color:var(--text-1);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;line-height:1.5;padding:24px;min-width:820px}
.report-header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:24px;padding-bottom:20px;border-bottom:1.5px solid var(--border)}
.report-title{font-size:20px;font-weight:700;letter-spacing:-.3px}
.report-sub{font-size:13px;color:var(--text-2);margin-top:3px}
.badge{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600}
.badge-live{background:#dcfce7;color:#15803d}
.badge-week{background:#eff6ff;color:#1d4ed8}
.badge-dot{width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.8}
.summary-row{display:grid;gap:12px;margin-bottom:24px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;box-shadow:var(--shadow)}
.card-label{font-size:11px;font-weight:600;color:var(--text-3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.card-value{font-size:22px;font-weight:700;line-height:1}
.neg-bar{height:6px;background:var(--border-light);border-radius:3px;overflow:hidden;margin-top:4px}
.neg-fill{height:100%;border-radius:3px;background:#f97316}
.card-accent{background:linear-gradient(135deg,#1e1b4b 0%,#312e81 100%);border-color:#312e81}
.card-accent .card-label{color:#a5b4fc}
.card-accent .card-value{color:#fff}
.change-pill{font-size:12px;font-weight:600;padding:3px 8px;border-radius:6px;display:inline-block;margin-top:6px}
.rating-summary{display:flex;align-items:center;gap:16px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 18px;margin-bottom:24px;box-shadow:var(--shadow)}
.rating-stars{display:flex;gap:12px}
.star-item{display:flex;flex-direction:column;align-items:center;gap:2px}
.star-val{font-size:18px;font-weight:700}
.star-label{font-size:10px;color:var(--text-3);text-transform:uppercase;letter-spacing:.4px}
.star-pct{font-size:11px;font-weight:600}
.rating-divider{width:1px;height:40px;background:var(--border)}
.rating-bar-wrap{flex:1}
.rating-row{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.rating-row:last-child{margin-bottom:0}
.r-label{font-size:11px;color:var(--text-2);min-width:28px}
.r-track{flex:1;height:8px;background:var(--border-light);border-radius:4px;overflow:hidden}
.r-fill{height:100%;border-radius:4px}
.r-count{font-size:11px;color:var(--text-2);min-width:32px;text-align:right;font-weight:500}
.section-header{display:flex;align-items:center;gap:10px;margin:28px 0 12px}
.section-title{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.6px}
.section-line{flex:1;height:1px;background:var(--border)}
.section-badge{font-size:10px;font-weight:600;background:var(--blue-100);color:var(--blue-600);padding:3px 8px;border-radius:10px}
.table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow)}
table{width:100%;border-collapse:collapse}
thead tr{background:#f8fafc;border-bottom:1.5px solid var(--border)}
th{padding:9px 12px;font-size:11px;font-weight:600;color:var(--text-2);text-align:right;white-space:nowrap;letter-spacing:.3px}
th:first-child,th.col-group{text-align:left}
th.col-sub{text-align:left;padding-left:10px}
td{padding:9px 12px;border-bottom:1px solid var(--border-light);vertical-align:middle;text-align:right;white-space:nowrap}
td.col-name{text-align:left;white-space:normal}
td.col-sub-name{text-align:left;padding-left:10px;white-space:normal}
tr:last-child td{border-bottom:none}
.heat{border-radius:4px;padding:2px 6px;display:inline-block;min-width:42px;text-align:center;font-weight:500;font-size:12px}
.group-name-wrap{display:flex;align-items:center;gap:8px;padding:10px 12px;border-left:3px solid transparent}
.group-icon{font-size:15px;line-height:1;flex-shrink:0}
.group-text{font-weight:600;font-size:12px}
.row-bold td{background:#eff6ff}
.row-bold td.col-sub-name{font-weight:700;color:var(--text-1)}
.chg{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:5px;font-size:11px;font-weight:700;min-width:52px;justify-content:center}
.chg-up{background:var(--red-50);color:var(--red-600)}
.chg-down{background:var(--green-50);color:var(--green-600)}
.chg-zero{background:#f8fafc;color:var(--text-3);border:1px solid var(--border)}
</style>
</head>
<body>
<div class="report-header">
  <div>
    <div class="report-title">{{REPORT_TITLE}}</div>
    <div class="report-sub">ZaloPay Customer Service · Phân tích survey 1–2 sao · <span id="wk-range-label"></span></div>
    <div style="display:flex;align-items:center;gap:8px;margin-top:8px">
      <span class="badge badge-live"><span class="badge-dot"></span>Auto-generated</span>
      <span class="badge badge-week" id="last-wk-badge"></span>
    </div>
  </div>
  <div style="text-align:right">
    <div style="font-size:11px;color:var(--text-3);margin-bottom:4px">Kỳ báo cáo</div>
    <div style="font-size:13px;font-weight:600" id="wk-range-right"></div>
    <div style="font-size:11px;color:var(--text-3);margin-top:2px" id="period-dates"></div>
  </div>
</div>

{{B0_HTML}}
<div class="rating-summary" id="rating-summary"></div>
<div class="summary-row" id="summary-cards"></div>

<div class="section-header">
  <div class="section-title">Group Issue</div>
  <div class="section-badge" id="group-badge"></div>
  <div class="section-line"></div>
  <div style="font-size:11px;color:var(--text-3)">% = ticket nhóm / tổng 1–2★ {{PERIOD_UNIT}} · Heatmap theo cột</div>
</div>
<div class="table-wrap" id="group-table"></div>

<div class="section-header" style="margin-top:28px">
  <div class="section-title">Sub Issue</div>
  <div class="section-badge" id="sub-badge"></div>
  <div class="section-line"></div>
  <div style="font-size:11px;color:var(--text-3)">Hàng in đậm = vấn đề trọng tâm · Heatmap toàn cột</div>
</div>
<div class="table-wrap" id="sub-table"></div>

<div style="margin-top:24px;font-size:11px;color:var(--text-3);text-align:center;padding-bottom:8px">
  Báo cáo tự động · CSAT Pipeline · ZaloPay CS Analytics · {{REPORT_DATE}}
</div>

<script>
const T = {{T_JSON}};
const GROUPS = {{GROUPS_JSON}};
const SUBS = {{SUBS_JSON}};
const RATING = {{RATING_JSON}};
const TOTAL_ALL = {{TOTAL_ALL_JSON}};
const WEEK_LABELS = {{WEEK_LABELS_JSON}};
const META = {{META_JSON}};
const WK_KEYS = Object.keys(T);
const lastW = WK_KEYS[WK_KEYS.length-1];
const prevW = WK_KEYS[WK_KEYS.length-2];

document.getElementById('wk-range-label').textContent = META.wk_range;
document.getElementById('last-wk-badge').textContent = lastW + ' · ' + META.report_date;
document.getElementById('wk-range-right').textContent = META.wk_range;
document.getElementById('period-dates').textContent = META.period_dates;

function pct(v,t){return t?v/t*100:0}
function chgBadge(vN,tN,vO,tO){
  const sN=pct(vN,tN),sO=pct(vO,tO);
  if(!sO)return '<span class="chg chg-zero">—</span>';
  const c=(sN-sO)/sO*100;
  if(Math.abs(c)<1)return '<span class="chg chg-zero">≈0%</span>';
  return c>0?`<span class="chg chg-up">▲ ${Math.abs(c).toFixed(0)}%</span>`
            :`<span class="chg chg-down">▼ ${Math.abs(c).toFixed(0)}%</span>`;
}
function heatCell(v,t,colMax){
  const p=pct(v,t);
  if(!p||!colMax)return '<span class="heat" style="color:#94a3b8">—</span>';
  const intensity=p/colMax;
  const alpha=(0.08+intensity*0.55).toFixed(2);
  const color=intensity>0.55?'#1e3a8a':'#1d4ed8';
  return `<span class="heat" style="background:rgba(37,99,235,${alpha});color:${color}">${p.toFixed(1)}%</span>`;
}

// Rating summary
(function(){
  const rd=RATING, total=TOTAL_ALL[lastW]||0;
  const neg=(rd['1'][lastW]||0)+(rd['2'][lastW]||0);
  const pos=(rd['4'][lastW]||0)+(rd['5'][lastW]||0);
  const negPct=(neg/total*100||0).toFixed(1);
  const rColors={1:'#ef4444',2:'#f97316',3:'#f59e0b',4:'#84cc16',5:'#22c55e'};
  const maxR=Math.max(...[1,2,3,4,5].map(s=>rd[s][lastW]||0));
  const bars=[5,4,3,2,1].map(s=>{
    const v=rd[s][lastW]||0, w=maxR?Math.round(v/maxR*100):0;
    return `<div class="rating-row"><span class="r-label">${s} ★</span>
      <div class="r-track"><div class="r-fill" style="width:${w}%;background:${rColors[s]}"></div></div>
      <span class="r-count">${v} <span style="color:var(--text-3)">(${(v/total*100||0).toFixed(1)}%)</span></span></div>`;
  }).join('');
  document.getElementById('rating-summary').innerHTML=`
    <div class="rating-stars">
      <div class="star-item"><div class="star-val" style="color:#ef4444">${neg}</div><div class="star-label">1-2 ★</div><div class="star-pct" style="color:#ef4444">${negPct}%</div></div>
      <div class="rating-divider"></div>
      <div class="star-item"><div class="star-val" style="color:#f59e0b">${rd['3'][lastW]||0}</div><div class="star-label">3 ★</div><div class="star-pct">${((rd['3'][lastW]||0)/total*100||0).toFixed(1)}%</div></div>
      <div class="rating-divider"></div>
      <div class="star-item"><div class="star-val" style="color:#22c55e">${pos}</div><div class="star-label">4-5 ★</div><div class="star-pct" style="color:#16a34a">${(pos/total*100||0).toFixed(1)}%</div></div>
      <div class="rating-divider"></div>
      <div style="font-size:11px;color:var(--text-2)">
        <div style="font-weight:600;color:var(--text-1);font-size:12px">${lastW} (mới nhất)</div>
        <div>Tổng: ${total} survey</div>
        <div style="color:#ef4444;font-weight:600">Negative rate: ${negPct}%</div>
      </div>
    </div>
    <div class="rating-divider"></div>
    <div class="rating-bar-wrap">${bars}</div>`;
})();

// KPI cards
(function(){
  const cols=`repeat(${WK_KEYS.length+1},1fr)`;
  document.getElementById('summary-cards').style.gridTemplateColumns=cols;
  const negLast=pct(T[lastW],TOTAL_ALL[lastW]).toFixed(1);
  const negPrev=prevW?pct(T[prevW],TOTAL_ALL[prevW]).toFixed(1):null;
  const chgVal=negPrev?((negLast-negPrev)/negPrev*100).toFixed(1):null;
  const cards=WK_KEYS.map((w,i)=>{
    const neg=T[w]||0, all=TOTAL_ALL[w]||0;
    const negP=(neg/all*100||0).toFixed(1), fillW=Math.round(neg/all*100||0);
    const lbl=(WEEK_LABELS[i]||w).replace('\n',' ');
    return `<div class="card"><div class="card-label">${lbl}</div>
      <div class="card-value">${neg}</div>
      <div style="font-size:11px;color:var(--text-2);margin-top:5px">1-2★: <strong style="color:#ef4444">${negP}%</strong> / ${all}</div>
      <div class="neg-bar"><div class="neg-fill" style="width:${fillW}%"></div></div></div>`;
  }).join('');
  const chgColor=chgVal>0?'#fca5a5':'#86efac';
  const chgText=chgVal?(chgVal>0?`▲ +${chgVal}%`:`▼ ${chgVal}%`):'—';
  const prevLabel=prevW?((WEEK_LABELS[WK_KEYS.indexOf(prevW)]||prevW).replace('\n',' ')):'—';
  document.getElementById('summary-cards').innerHTML=cards+`
    <div class="card card-accent">
      <div class="card-label">${prevLabel} → ${lastW}</div>
      <div class="card-value">${negLast}%</div>
      <div style="font-size:10px;color:#a5b4fc;margin-top:3px">negative rate ${lastW}</div>
      <div class="change-pill" style="background:rgba(255,255,255,.12);color:${chgColor}">${chgText} vs tuần trước</div>
    </div>`;
})();

// Group table
(function(){
  document.getElementById('group-badge').textContent=GROUPS.length+' nhóm';
  const colMax={};
  WK_KEYS.forEach(w=>{colMax[w]=Math.max(...GROUPS.map(g=>pct(g.v[w]||0,T[w]||1)));});
  const header=`<thead><tr><th style="width:180px">Group Issue</th>
    ${WK_KEYS.map((w,i)=>`<th>${(WEEK_LABELS[i]||w).replace('\n','<br>')}</th>`).join('')}
    <th>${prevW||'—'}→${lastW}</th></tr></thead>`;
  const rows=GROUPS.map(g=>`<tr>
    <td class="col-name"><div class="group-name-wrap" style="border-left-color:${g.accent}">
      <span class="group-icon">${g.emoji}</span><span class="group-text">${g.name}</span></div></td>
    ${WK_KEYS.map(w=>`<td>${heatCell(g.v[w]||0,T[w],colMax[w])}</td>`).join('')}
    <td>${chgBadge(g.v[lastW]||0,T[lastW],g.v[prevW]||0,T[prevW]||1)}</td></tr>`).join('');
  document.getElementById('group-table').innerHTML=`<table>${header}<tbody>${rows}</tbody></table>`;
})();

// Sub table
(function(){
  document.getElementById('sub-badge').textContent=SUBS.length+' sub issues';
  const colMax={};
  WK_KEYS.forEach(w=>{colMax[w]=Math.max(...SUBS.map(s=>pct(s.v[w]||0,T[w]||1)));});
  const gMap={};
  GROUPS.forEach(g=>{gMap[g.name]=g;});
  const grouped={};
  GROUPS.forEach(g=>{grouped[g.name]=SUBS.filter(s=>s.g===g.name);});
  const header=`<thead><tr>
    <th class="col-group" style="width:110px">Nhóm</th>
    <th class="col-sub" style="width:190px">Sub Issue</th>
    ${WK_KEYS.map((w,i)=>`<th>${(WEEK_LABELS[i]||w).replace('\n','<br>')}</th>`).join('')}
    <th>${prevW||'—'}→${lastW}</th></tr></thead>`;
  let body='';
  GROUPS.forEach(g=>{
    const list=grouped[g.name]||[];
    if(!list.length)return;
    list.forEach((sub,si)=>{
      const rc=sub.bold?' class="row-bold"':'';
      const cells=WK_KEYS.map(w=>`<td>${heatCell(sub.v[w]||0,T[w],colMax[w])}</td>`).join('');
      const chg=chgBadge(sub.v[lastW]||0,T[lastW],sub.v[prevW]||0,T[prevW]||1);
      const gc=si===0?`<td rowspan="${list.length}" style="border-left:3px solid ${g.accent};background:${g.accent}0d;vertical-align:middle;text-align:center;padding:8px 6px">
        <div style="display:flex;flex-direction:column;align-items:center;gap:5px">
          <span style="font-size:15px">${g.emoji}</span>
          <span style="font-size:10px;font-weight:700;color:${g.accent};writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap">${g.name}</span>
        </div></td>`:'';
      body+=`<tr${rc}>${gc}<td class="col-sub-name">${sub.bold?`<strong>${sub.s}</strong>`:sub.s}</td>${cells}<td>${chg}</td></tr>`;
    });
  });
  document.getElementById('sub-table').innerHTML=`<table>${header}<tbody>${body}</tbody></table>`;
})();
</script>
</body>
</html>"""


def generate_csat_report(
    df_classified: pd.DataFrame,
    df_raw: pd.DataFrame,
    job_id: str,
    period: str = "",
    report_type: str = "weekly",
    b0_html: str = "",
) -> Path:
    df = df_classified.copy()

    if report_type == "monthly":
        # ── Monthly mode ─────────────────────────────────────────────────
        if "Thời gian" not in df.columns:
            raise ValueError("df_classified missing 'Thời gian' column (required for monthly mode)")

        df["Thời gian"] = pd.to_datetime(df["Thời gian"], errors="coerce")
        df["_period"] = df["Thời gian"].dt.to_period("M")
        df = df.dropna(subset=["_period"])

        all_periods = sorted(df["_period"].unique())
        selected = all_periods[-4:] if len(all_periods) >= 4 else all_periods

        df = df[df["_period"].isin(selected)].copy()
        period_keys = [f"T{p.month}" for p in selected]

        # Period labels: "T1\n01/2025"
        period_labels = [f"{pk}\n{p.strftime('%m/%Y')}" for pk, p in zip(period_keys, selected)]

        # T: total neg per period key
        T = {period_keys[i]: int(df[df["_period"] == p].shape[0]) for i, p in enumerate(selected)}

        # Rating distribution from raw (B2) data
        RATING = {str(s): {pk: 0 for pk in period_keys} for s in [1, 2, 3, 4, 5]}
        TOTAL_ALL = {pk: 0 for pk in period_keys}

        if df_raw is not None and "Thời gian" in df_raw.columns and "Đánh giá (sao)" in df_raw.columns:
            dr = df_raw.copy()
            dr["Thời gian"] = pd.to_datetime(dr["Thời gian"], errors="coerce")
            dr["Đánh giá (sao)"] = pd.to_numeric(dr["Đánh giá (sao)"], errors="coerce")
            dr["_period"] = dr["Thời gian"].dt.to_period("M")
            dr = dr.dropna(subset=["_period", "Đánh giá (sao)"])
            dr = dr[dr["_period"].isin(selected)]
            for i, p in enumerate(selected):
                pk = period_keys[i]
                wdf = dr[dr["_period"] == p]
                TOTAL_ALL[pk] = len(wdf)
                for star in [1, 2, 3, 4, 5]:
                    RATING[str(star)][pk] = int((wdf["Đánh giá (sao)"] == star).sum())
        else:
            for i, p in enumerate(selected):
                pk = period_keys[i]
                n = T[pk]
                TOTAL_ALL[pk] = n
                RATING["1"][pk] = int(n * 0.78)
                RATING["2"][pk] = n - int(n * 0.78)

        # GROUPS counts
        lbl_col = "primary_label" if "primary_label" in df.columns else None
        groups_js = []
        for g in GROUP_META:
            v = {}
            for i, p in enumerate(selected):
                pk = period_keys[i]
                if lbl_col:
                    v[pk] = int(df[(df["_period"] == p) & df[lbl_col].isin(g["labels"])].shape[0])
                else:
                    v[pk] = 0
            groups_js.append({"name": g["name"], "emoji": g["emoji"], "accent": g["accent"],
                              "bg": g["bg"], "tc": g["tc"], "v": v})

        # SUBS counts
        subs_js = []
        for sm in SUBS_META:
            v = {}
            for i, p in enumerate(selected):
                pk = period_keys[i]
                if lbl_col:
                    v[pk] = int(df[(df["_period"] == p) & df[lbl_col].isin(sm["labels"])].shape[0])
                else:
                    v[pk] = 0
            if sum(v.values()) == 0:
                continue
            subs_js.append({"g": sm["g"], "s": sm["s"], "v": v, "bold": sm["bold"]})

        # Metadata
        if "Thời gian" in df.columns:
            dates = pd.to_datetime(df["Thời gian"], errors="coerce").dropna()
            report_date = dates.max().strftime("%d/%m/%Y") if len(dates) else datetime.now().strftime("%d/%m/%Y")
            period_dates = f"{dates.min().strftime('%d/%m')} – {dates.max().strftime('%d/%m/%Y')}" if len(dates) else ""
        else:
            report_date = datetime.now().strftime("%d/%m/%Y")
            period_dates = ""

        wk_range = f"T{selected[0].month}–T{selected[-1].month}/{selected[-1].year}"
        meta = {"report_date": report_date, "wk_range": wk_range, "period_dates": period_dates}
        week_labels = period_labels
        report_title = "CSAT Chatbot — Monthly Analysis Report"
        period_unit = "tháng"

    else:
        # ── Weekly mode (original logic) ─────────────────────────────────
        if "Tuần" not in df.columns:
            raise ValueError("df_classified missing 'Tuần' column (from B2 clean step)")

        df["_wk"] = df["Tuần"].astype("Int64")
        df = df.dropna(subset=["_wk"])

        all_weeks = sorted(df["_wk"].unique())
        selected = all_weeks[-4:] if len(all_weeks) >= 4 else all_weeks

        df = df[df["_wk"].isin(selected)].copy()
        period_keys = [f"W{int(w)}" for w in selected]

        # Week labels with start date
        week_labels = []
        for w, pk in zip(selected, period_keys):
            sub = df[df["_wk"] == w]
            if "Thời gian" in sub.columns:
                dates = pd.to_datetime(sub["Thời gian"], errors="coerce").dropna()
                if len(dates):
                    week_labels.append(f"{pk}\n{dates.min().strftime('%d/%m')}")
                    continue
            week_labels.append(pk)

        # T: total neg per week key
        T = {period_keys[i]: int(df[df["_wk"] == w].shape[0]) for i, w in enumerate(selected)}

        # Rating distribution from raw (B2) data
        RATING = {str(s): {pk: 0 for pk in period_keys} for s in [1, 2, 3, 4, 5]}
        TOTAL_ALL = {pk: 0 for pk in period_keys}

        if df_raw is not None and "Thời gian" in df_raw.columns and "Đánh giá (sao)" in df_raw.columns:
            dr = df_raw.copy()
            dr["Thời gian"] = pd.to_datetime(dr["Thời gian"], errors="coerce")
            dr["Đánh giá (sao)"] = pd.to_numeric(dr["Đánh giá (sao)"], errors="coerce")
            if "Tuần" not in dr.columns:
                dr["Tuần"] = (dr["Thời gian"].dt.isocalendar().week.astype("Int64") - 1).where(
                    dr["Thời gian"].notna(), pd.NA)
            dr = dr.dropna(subset=["Tuần", "Đánh giá (sao)"])
            dr["_wk"] = dr["Tuần"].astype("Int64")
            dr = dr[dr["_wk"].isin(selected)]
            for i, w in enumerate(selected):
                pk = period_keys[i]
                wdf = dr[dr["_wk"] == w]
                TOTAL_ALL[pk] = len(wdf)
                for star in [1, 2, 3, 4, 5]:
                    RATING[str(star)][pk] = int((wdf["Đánh giá (sao)"] == star).sum())
        else:
            for i, w in enumerate(selected):
                pk = period_keys[i]
                n = T[pk]
                TOTAL_ALL[pk] = n
                RATING["1"][pk] = int(n * 0.78)
                RATING["2"][pk] = n - int(n * 0.78)

        # GROUPS counts
        lbl_col = "primary_label" if "primary_label" in df.columns else None
        groups_js = []
        for g in GROUP_META:
            v = {}
            for i, w in enumerate(selected):
                pk = period_keys[i]
                if lbl_col:
                    v[pk] = int(df[(df["_wk"] == w) & df[lbl_col].isin(g["labels"])].shape[0])
                else:
                    v[pk] = 0
            groups_js.append({"name": g["name"], "emoji": g["emoji"], "accent": g["accent"],
                              "bg": g["bg"], "tc": g["tc"], "v": v})

        # SUBS counts
        subs_js = []
        for sm in SUBS_META:
            v = {}
            for i, w in enumerate(selected):
                pk = period_keys[i]
                if lbl_col:
                    v[pk] = int(df[(df["_wk"] == w) & df[lbl_col].isin(sm["labels"])].shape[0])
                else:
                    v[pk] = 0
            if sum(v.values()) == 0:
                continue
            subs_js.append({"g": sm["g"], "s": sm["s"], "v": v, "bold": sm["bold"]})

        # Metadata
        if "Thời gian" in df.columns:
            dates = pd.to_datetime(df["Thời gian"], errors="coerce").dropna()
            report_date = dates.max().strftime("%d/%m/%Y") if len(dates) else datetime.now().strftime("%d/%m/%Y")
            period_dates = f"{dates.min().strftime('%d/%m')} – {dates.max().strftime('%d/%m/%Y')}" if len(dates) else ""
        else:
            report_date = datetime.now().strftime("%d/%m/%Y")
            period_dates = ""

        wk_range = f"{period_keys[0]}–{period_keys[-1]}"
        meta = {"report_date": report_date, "wk_range": wk_range, "period_dates": period_dates}
        report_title = "CSAT Chatbot — Weekly Analysis Report"
        period_unit = "tuần"

    # ── Render HTML ───────────────────────────────────────────────────────
    html = HTML_TEMPLATE
    html = html.replace("{{T_JSON}}", json.dumps(T, ensure_ascii=False))
    html = html.replace("{{GROUPS_JSON}}", json.dumps(groups_js, ensure_ascii=False, indent=2))
    html = html.replace("{{SUBS_JSON}}", json.dumps(subs_js, ensure_ascii=False, indent=2))
    html = html.replace("{{RATING_JSON}}", json.dumps(RATING, ensure_ascii=False))
    html = html.replace("{{TOTAL_ALL_JSON}}", json.dumps(TOTAL_ALL, ensure_ascii=False))
    html = html.replace("{{WEEK_LABELS_JSON}}", json.dumps(week_labels, ensure_ascii=False))
    html = html.replace("{{META_JSON}}", json.dumps(meta, ensure_ascii=False))
    html = html.replace("{{PERIOD}}", period or job_id)
    html = html.replace("{{REPORT_DATE}}", report_date)
    html = html.replace("{{REPORT_TITLE}}", report_title)
    html = html.replace("{{PERIOD_UNIT}}", period_unit)
    html = html.replace("{{B0_HTML}}", b0_html)

    fname = f"CSAT REPORT {period}.html" if period else f"b5_report_{job_id}.html"
    out_path = OUTPUT_DIR / fname
    out_path.write_text(html, encoding="utf-8")
    return out_path
