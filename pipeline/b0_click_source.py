"""B0 — Pre-pipeline: Click Source + Ticket Volume (weekly chart format)."""
import json
import re
import uuid
from pathlib import Path

import pandas as pd

# Freshdesk source submit values
CHATBOT_TRANS    = "Chatbot có TransID"
CHATBOT_NO_TRANS = "Chatbot không TransID"
LIVECHAT_SOURCES = ["Live Chat", "Live chat_Merchant Support", "Live chat_VietQR"]
SOURCE_COL       = "source submit"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, engine="openpyxl")
    else:
        df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    return df


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    low = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in low:
            return low[c.lower()]
    return None


def _week_num(label: str) -> int:
    m = re.search(r"\d+", str(label))
    return int(m.group()) if m else 0


def _to_week_label(val) -> str | None:
    s = str(val).strip()
    m = re.match(r"^W(\d+)$", s, re.IGNORECASE)
    if m:
        return f"W{int(m.group(1))}"
    try:
        ts = pd.to_datetime(val)
        if pd.notna(ts):
            return f"W{ts.isocalendar().week}"
    except Exception:
        pass
    return None


def _wow_badge(weeks: list[str], vals: list[float]) -> str:
    if len(vals) < 2 or vals[-2] == 0:
        return ""
    pct = (vals[-1] - vals[-2]) / vals[-2] * 100
    sign = "+" if pct >= 0 else ""
    color = "#16a34a" if pct >= 0 else "#dc2626"
    return (
        f'<span style="background:{color};color:#fff;padding:4px 14px;'
        f'border-radius:20px;font-size:11px;font-weight:700;white-space:nowrap">'
        f"{weeks[-2]} → {weeks[-1]} {sign}{pct:.1f}%</span>"
    )


# ── Data extraction ───────────────────────────────────────────────────────────

def _get_click_weekly(df: pd.DataFrame) -> tuple[list[str], list[float]]:
    """
    Returns (weeks, total_clicks_per_week).
    Supports:
      - Wide format: each week is a column  [Category | W16 | W17 | W18 | W19]
      - Long format: has a week/date column [Week | Category | Clicks]
    """
    # Wide format: columns whose names look like W<n>
    week_cols = sorted(
        [c for c in df.columns if re.match(r"^W\d+$", str(c).strip(), re.IGNORECASE)],
        key=_week_num,
    )
    if week_cols:
        weeks  = [str(c) for c in week_cols]
        totals = [float(pd.to_numeric(df[c], errors="coerce").fillna(0).sum()) for c in week_cols]
        return weeks, totals

    # Long format: explicit week/date column
    week_col = _find_col(df, ["week", "tuần", "kỳ", "w"])
    cnt_col  = _find_col(df, ["click", "clicks", "count", "total", "số click", "quantity"])
    if week_col and cnt_col:
        df = df.copy()
        df[cnt_col] = pd.to_numeric(df[cnt_col], errors="coerce").fillna(0)
        df["_wk"]   = df[week_col].apply(_to_week_label)
        grp = df.dropna(subset=["_wk"]).groupby("_wk")[cnt_col].sum()
        weeks = sorted(grp.index, key=_week_num)
        return weeks, [float(grp[w]) for w in weeks]

    return [], []


def _get_ticket_weekly(
    df: pd.DataFrame, weeks: list[str]
) -> tuple[list[float], list[float], list[float], bool]:
    """
    Returns (trans, no_trans, live, has_weekly_breakdown).
    has_weekly_breakdown = True when a date column was found and grouping worked.
    """
    src_col  = _find_col(df, [SOURCE_COL, "source_submit", "Source Submit", "Source"])
    date_col = _find_col(
        df, ["created_at", "date", "ngày tạo", "created", "createdtime", "time", "ngày"]
    )

    zero = [0.0] * len(weeks)
    if not src_col:
        return zero, zero, zero, False

    df = df.copy()
    df[src_col] = df[src_col].astype(str).str.strip()

    has_weekly = False
    if date_col:
        try:
            df["_wk"] = pd.to_datetime(df[date_col], errors="coerce").apply(
                lambda x: f"W{x.isocalendar().week}" if pd.notna(x) else None
            )
            has_weekly = df["_wk"].notna().any()
        except Exception:
            df["_wk"] = None
    else:
        df["_wk"] = None

    trans, notrans, live = [], [], []
    for w in weeks:
        sub = df[df["_wk"] == w] if has_weekly else df
        trans.append(float((sub[src_col] == CHATBOT_TRANS).sum()))
        notrans.append(float((sub[src_col] == CHATBOT_NO_TRANS).sum()))
        live.append(float(sub[src_col].isin(LIVECHAT_SOURCES).sum()))

    return trans, notrans, live, has_weekly


# ── Top-15 table ──────────────────────────────────────────────────────────────

def _top15_html(df: pd.DataFrame) -> str:
    cat_col = _find_col(df, ["category", "danh mục", "danh_muc", "cat", "name", "tên"])
    cnt_col = _find_col(df, ["click", "count", "số click", "so_click", "clicks", "total", "quantity", "số lượng"])

    if cat_col is None:
        str_cols = df.select_dtypes(include="object").columns
        cat_col  = str_cols[0] if len(str_cols) else df.columns[0]

    if cnt_col is None:
        # Try summing wide-format week columns
        week_cols = [c for c in df.columns if re.match(r"^W\d+$", str(c).strip(), re.IGNORECASE)]
        if week_cols:
            df = df.copy()
            df["_total"] = df[week_cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
            cnt_col = "_total"
        else:
            num_cols = df.select_dtypes(include="number").columns
            cnt_col  = num_cols[0] if len(num_cols) else None

    if not cnt_col:
        return ""

    df = df.copy()
    df[cnt_col] = pd.to_numeric(df[cnt_col], errors="coerce").fillna(0)
    top15 = (
        df[[cat_col, cnt_col]]
        .sort_values(cnt_col, ascending=False)
        .head(15)
        .reset_index(drop=True)
    )
    total = top15[cnt_col].sum()

    rows = ""
    for i, row in top15.iterrows():
        pct = row[cnt_col] / total * 100 if total else 0
        bg  = "#f8fafc" if i % 2 == 0 else "#fff"
        rows += (
            f'<tr style="background:{bg}">'
            f'<td style="padding:8px 12px;font-size:12px;color:#64748b;font-weight:600">{i+1}</td>'
            f'<td style="padding:8px 12px;font-size:12px;color:#0f172a">{row[cat_col]}</td>'
            f'<td style="padding:8px 12px;font-size:12px;font-weight:700;color:#2563eb;text-align:right">{int(row[cnt_col]):,}</td>'
            f'<td style="padding:8px 12px;font-size:12px;color:#64748b;text-align:right">{pct:.1f}%</td>'
            f"</tr>"
        )

    return f"""
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.06)">
  <div style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#475569;margin-bottom:16px">📊 Top 15 Click Category</div>
  <div style="overflow:hidden;border-radius:8px;border:1px solid #f1f5f9">
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#f8fafc;border-bottom:1.5px solid #e2e8f0">
          <th style="padding:9px 12px;font-size:11px;font-weight:600;color:#64748b;text-align:left;width:40px">#</th>
          <th style="padding:9px 12px;font-size:11px;font-weight:600;color:#64748b;text-align:left">Category</th>
          <th style="padding:9px 12px;font-size:11px;font-weight:600;color:#64748b;text-align:right">Clicks</th>
          <th style="padding:9px 12px;font-size:11px;font-weight:600;color:#64748b;text-align:right">%</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""


# ── Chart HTML ────────────────────────────────────────────────────────────────

def _charts_html(
    cid: str,
    weeks: list[str],
    click_totals: list[float],
    ticket_rates: list[float],
    ticket_trans: list[float],
    ticket_notrans: list[float],
    ticket_live: list[float],
    has_click_data: bool,
    has_ticket_weekly: bool,
) -> str:
    ticket_totals = [t + n + l for t, n, l in zip(ticket_trans, ticket_notrans, ticket_live)]
    click_wow  = _wow_badge(weeks, click_totals) if has_click_data else ""
    ticket_wow = _wow_badge(weeks, ticket_totals)

    wj  = json.dumps(weeks)
    clj = json.dumps(click_totals)
    trj = json.dumps(ticket_rates)
    ttj = json.dumps(ticket_trans)
    tnj = json.dumps(ticket_notrans)
    tlj = json.dumps(ticket_live)

    return f"""
<!-- ── B0: Click Chatbot ─────────────────────────────────────────────── -->
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:24px 28px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.06)">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
    <div style="flex:1"></div>
    <div style="font-size:15px;font-weight:700;color:#3b82f6;letter-spacing:.8px;text-transform:uppercase;text-align:center;flex:2">CLICK CHATBOT</div>
    <div style="flex:1;display:flex;justify-content:flex-end">{click_wow}</div>
  </div>
  <div style="text-align:center;font-size:11px;color:#64748b;margin-bottom:14px;display:flex;justify-content:center;gap:16px;flex-wrap:wrap">
    <span style="display:inline-flex;align-items:center;gap:5px">
      <span style="width:13px;height:13px;background:#90cdf4;border-radius:3px;display:inline-block"></span>Click Chatbot
    </span>
    <span style="display:inline-flex;align-items:center;gap:5px">
      <span style="width:18px;height:0;border-top:2.5px dashed #f97316;display:inline-block"></span>Click Chatbot (trend)
    </span>
    <span style="display:inline-flex;align-items:center;gap:5px">
      <span style="width:18px;height:0;border-top:2.5px solid #1e40af;display:inline-block"></span>Tỷ lệ submit ticket
    </span>
  </div>
  <canvas id="b0-click-{cid}"></canvas>
</div>

<!-- ── B0: Weekly Ticket Volume ──────────────────────────────────────── -->
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:24px 28px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.06)">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
    <div style="flex:1"></div>
    <div style="font-size:15px;font-weight:700;color:#3b82f6;letter-spacing:.8px;text-transform:uppercase;text-align:center;flex:2">WEEKLY TICKET VOLUME</div>
    <div style="flex:1;display:flex;justify-content:flex-end">{ticket_wow}</div>
  </div>
  <div style="text-align:center;font-size:11px;color:#64748b;margin-bottom:14px;display:flex;justify-content:center;gap:16px;flex-wrap:wrap">
    <span style="display:inline-flex;align-items:center;gap:5px">
      <span style="width:13px;height:13px;background:#90cdf4;border-radius:3px;display:inline-block"></span>Ticket có transaction
    </span>
    <span style="display:inline-flex;align-items:center;gap:5px">
      <span style="width:13px;height:13px;background:#86efac;border-radius:3px;display:inline-block"></span>Ticket không transaction
    </span>
    <span style="display:inline-flex;align-items:center;gap:5px">
      <span style="width:13px;height:13px;background:#fdba74;border-radius:3px;display:inline-block"></span>Live Chat
    </span>
  </div>
  <canvas id="b0-ticket-{cid}"></canvas>
</div>

<script>
(function() {{
  var W   = {wj};
  var CL  = {clj};
  var TR  = {trj};
  var TT  = {ttj};
  var TN  = {tnj};
  var TLV = {tlj};
  var TOT = TT.map(function(t,i){{ return t + TN[i] + TLV[i]; }});

  function buildCharts() {{
    Chart.register(ChartDataLabels);

    /* ── Chart 1: Click Chatbot (bar + dual-axis lines) ── */
    new Chart(document.getElementById('b0-click-{cid}'), {{
      data: {{
        labels: W,
        datasets: [
          {{
            type: 'bar',
            label: 'Click Chatbot',
            data: CL,
            backgroundColor: 'rgba(144,205,244,0.85)',
            borderColor:     'rgba(144,205,244,1)',
            borderRadius: 5,
            borderSkipped: false,
            yAxisID: 'y',
            datalabels: {{
              anchor: 'end',
              align:  'end',
              offset: 2,
              color: '#1e293b',
              font:  {{ weight: 'bold', size: 12 }},
              formatter: function(v) {{
                return v >= 1000 ? (v/1000).toFixed(0)+'K' : String(v);
              }}
            }}
          }},
          {{
            type: 'line',
            label: 'Trend',
            data: CL,
            borderColor:          '#f97316',
            borderDash:           [6, 3],
            borderWidth:          2,
            pointBackgroundColor: '#f97316',
            pointRadius:          5,
            tension:              0.3,
            fill:                 false,
            yAxisID: 'y',
            datalabels: {{ display: false }}
          }},
          {{
            type: 'line',
            label: 'Tỷ lệ submit ticket',
            data: TR,
            borderColor:          '#1e40af',
            borderWidth:          2,
            pointBackgroundColor: '#1e40af',
            pointRadius:          5,
            tension:              0.2,
            fill:                 false,
            yAxisID: 'y1',
            datalabels: {{
              anchor: 'center',
              align:  'bottom',
              offset: 6,
              color:  '#1e40af',
              font:   {{ weight: 'bold', size: 11 }},
              formatter: function(v) {{ return v.toFixed(1)+'%'; }}
            }}
          }}
        ]
      }},
      options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend:      {{ display: false }},
          datalabels:  {{ display: true }},
          tooltip: {{
            callbacks: {{
              label: function(ctx) {{
                if (ctx.datasetIndex === 2)
                  return 'Tỷ lệ submit: ' + ctx.parsed.y.toFixed(1) + '%';
                if (ctx.datasetIndex === 0)
                  return 'Click: ' + (ctx.parsed.y/1000).toFixed(1) + 'K';
                return '';
              }}
            }}
          }}
        }},
        scales: {{
          y: {{
            type:     'linear',
            position: 'left',
            grid:     {{ color: 'rgba(0,0,0,0.05)' }},
            ticks: {{
              callback: function(v) {{ return (v/1000).toFixed(0)+'K'; }}
            }}
          }},
          y1: {{
            type:     'linear',
            position: 'right',
            grid:     {{ drawOnChartArea: false }},
            ticks: {{
              callback: function(v) {{ return v.toFixed(0)+'%'; }}
            }}
          }},
          x: {{
            grid: {{ color: 'rgba(0,0,0,0.03)' }}
          }}
        }}
      }},
      plugins: [ChartDataLabels]
    }});

    /* ── Chart 2: Weekly Ticket Volume (stacked bar) ── */
    new Chart(document.getElementById('b0-ticket-{cid}'), {{
      type: 'bar',
      data: {{
        labels: W,
        datasets: [
          {{
            label:           'Ticket có transaction',
            data:            TT,
            backgroundColor: '#90cdf4',
            stack:           'tkt',
            datalabels: {{
              color: '#1e3a5f',
              font:  {{ weight: 'bold', size: 11 }},
              formatter: function(v) {{ return v > 0 ? v.toLocaleString() : ''; }}
            }}
          }},
          {{
            label:           'Ticket không transaction',
            data:            TN,
            backgroundColor: '#86efac',
            stack:           'tkt',
            datalabels: {{
              color: '#14532d',
              font:  {{ weight: 'bold', size: 11 }},
              formatter: function(v) {{ return v > 0 ? v.toLocaleString() : ''; }}
            }}
          }},
          {{
            label:           'Live Chat',
            data:            TLV,
            backgroundColor: '#fdba74',
            stack:           'tkt',
            datalabels: {{
              anchor: 'end',
              align:  'end',
              offset: 2,
              color:  '#92400e',
              font:   {{ weight: 'bold', size: 11 }},
              formatter: function(v, ctx) {{
                var tot = TOT[ctx.dataIndex];
                if (ctx.datasetIndex !== 2) return v > 0 ? v.toLocaleString() : '';
                return tot >= 1000 ? (tot/1000).toFixed(1)+'K' : tot.toLocaleString();
              }}
            }}
          }}
        ]
      }},
      options: {{
        responsive: true,
        plugins: {{
          legend:     {{ display: false }},
          datalabels: {{ display: true }},
          tooltip: {{
            callbacks: {{
              afterTitle: function(items) {{
                var tot = TOT[items[0].dataIndex];
                return 'Total: ' + (tot >= 1000 ? (tot/1000).toFixed(1)+'K' : tot.toLocaleString());
              }},
              label: function(ctx) {{
                return ctx.dataset.label + ': ' + ctx.parsed.y.toLocaleString();
              }}
            }}
          }}
        }},
        scales: {{
          y: {{
            stacked: true,
            grid:    {{ color: 'rgba(0,0,0,0.05)' }},
            ticks: {{
              callback: function(v) {{ return v >= 1000 ? (v/1000).toFixed(0)+'K' : v; }}
            }}
          }},
          x: {{
            stacked: true,
            grid:    {{ color: 'rgba(0,0,0,0.03)' }}
          }}
        }}
      }},
      plugins: [ChartDataLabels]
    }});
  }}

  /* Load Chart.js + datalabels plugin, then build */
  function loadScript(src, cb) {{
    var s = document.createElement('script');
    s.src = src;
    s.onload = cb;
    document.head.appendChild(s);
  }}

  function ready() {{
    if (typeof Chart !== 'undefined' && typeof ChartDataLabels !== 'undefined') {{
      buildCharts();
    }} else if (typeof Chart !== 'undefined') {{
      loadScript(
        'https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js',
        buildCharts
      );
    }} else {{
      loadScript(
        'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
        function() {{
          loadScript(
            'https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js',
            buildCharts
          );
        }}
      );
    }}
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', ready);
  }} else {{
    ready();
  }}
}})();
</script>"""


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_click_source(click_path: Path, freshdesk_path: Path | None) -> str:
    """
    Returns HTML with:
      1. CLICK CHATBOT weekly bar+line chart (dual axis)
      2. WEEKLY TICKET VOLUME stacked bar chart
      3. Top 15 Click Category table
    """
    cid = uuid.uuid4().hex[:8]

    try:
        df_click = _read_file(click_path)
    except Exception as e:
        return f'<div style="color:#ef4444;padding:8px">Lỗi đọc Click Source: {e}</div>'

    df_fd = None
    if freshdesk_path and freshdesk_path.exists():
        try:
            df_fd = _read_file(freshdesk_path)
        except Exception:
            pass

    # ── Get weekly click data ────────────────────────────────────────────────
    weeks, click_totals = _get_click_weekly(df_click)

    # If click file has no weekly data, derive weeks from Freshdesk dates
    if not weeks and df_fd is not None:
        date_col = _find_col(
            df_fd, ["created_at", "date", "ngày tạo", "created", "createdtime", "time"]
        )
        if date_col:
            try:
                wk_series = pd.to_datetime(df_fd[date_col], errors="coerce").apply(
                    lambda x: f"W{x.isocalendar().week}" if pd.notna(x) else None
                )
                all_weeks = sorted(wk_series.dropna().unique(), key=_week_num)
                weeks       = list(all_weeks[-4:])   # last 4 weeks
                click_totals = [0.0] * len(weeks)
            except Exception:
                pass

    # ── Get weekly ticket data ───────────────────────────────────────────────
    if df_fd is not None and weeks:
        ticket_trans, ticket_notrans, ticket_live, has_ticket_weekly = _get_ticket_weekly(df_fd, weeks)
    else:
        z = [0.0] * len(weeks)
        ticket_trans = ticket_notrans = ticket_live = z
        has_ticket_weekly = False

    ticket_totals = [t + n + l for t, n, l in zip(ticket_trans, ticket_notrans, ticket_live)]
    ticket_rates  = [
        round(t / c * 100, 1) if c else 0.0
        for t, c in zip(ticket_totals, click_totals)
    ]

    has_click_data = any(v > 0 for v in click_totals)

    # ── Build sections ───────────────────────────────────────────────────────
    sections: list[str] = []

    if weeks and (has_click_data or any(v > 0 for v in ticket_totals)):
        sections.append(
            _charts_html(
                cid, weeks, click_totals, ticket_rates,
                ticket_trans, ticket_notrans, ticket_live,
                has_click_data, has_ticket_weekly,
            )
        )

    top15 = _top15_html(df_click)
    if top15:
        sections.append(top15)

    if not sections:
        return ""

    return f"""
<div style="margin-bottom:28px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
    <div style="font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#0f172a">📈 B0 — Click Source &amp; Ticket Volume</div>
    <div style="flex:1;height:1px;background:#e2e8f0"></div>
  </div>
  {"".join(sections)}
</div>"""
