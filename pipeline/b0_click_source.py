"""B0 — Pre-pipeline: Click Source + Ticket Volume analysis."""
import json
from pathlib import Path
import pandas as pd

# Freshdesk source submit categories
CHATBOT_TRANS = "Chatbot có TransID"
CHATBOT_NO_TRANS = "Chatbot không TransID"
LIVECHAT_SOURCES = ["Live Chat", "Live chat_Merchant Support", "Live chat_VietQR"]
SOURCE_COL = "source submit"


def _read_file(path: Path) -> pd.DataFrame:
    """Read Excel or CSV, strip column whitespace."""
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, engine="openpyxl")
    else:
        df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    return df


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Find first matching column (case-insensitive)."""
    low = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in low:
            return low[c.lower()]
    return None


def analyze_click_source(click_path: Path, freshdesk_path: Path | None) -> str:
    """
    Returns an HTML string with 3 sections:
    1. Ticket Volume chart (Chatbot có TransID, Chatbot không TransID, Livechat)
    2. Click Source vs Total Ticket comparison table
    3. Top 15 Click Category table
    """
    sections = []

    # ── Ticket Volume from Freshdesk ─────────────────────────────────────
    ticket_html = ""
    total_ticket = 0
    if freshdesk_path and freshdesk_path.exists():
        try:
            df_fd = _read_file(freshdesk_path)
            src_col = _find_col(df_fd, [SOURCE_COL, "source_submit", "Source Submit", "Source"])
            if src_col:
                df_fd[src_col] = df_fd[src_col].astype(str).str.strip()
                cnt_chatbot_trans = int((df_fd[src_col] == CHATBOT_TRANS).sum())
                cnt_chatbot_no   = int((df_fd[src_col] == CHATBOT_NO_TRANS).sum())
                cnt_livechat     = int(df_fd[src_col].isin(LIVECHAT_SOURCES).sum())
                total_ticket     = cnt_chatbot_trans + cnt_chatbot_no + cnt_livechat

                bars_data = [
                    ("Chatbot có TransID", cnt_chatbot_trans, "#6366f1"),
                    ("Chatbot không TransID", cnt_chatbot_no, "#8b5cf6"),
                    ("Livechat", cnt_livechat, "#06b6d4"),
                ]
                max_val = max(v for _, v, _ in bars_data) or 1

                bar_rows = ""
                for label, val, color in bars_data:
                    pct = val / total_ticket * 100 if total_ticket else 0
                    width = val / max_val * 100
                    bar_rows += f"""
                    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
                      <div style="width:180px;font-size:12px;font-weight:600;color:#334155;text-align:right;flex-shrink:0">{label}</div>
                      <div style="flex:1;background:#f1f5f9;border-radius:6px;height:28px;overflow:hidden">
                        <div style="width:{width:.1f}%;background:{color};height:100%;border-radius:6px;display:flex;align-items:center;padding-left:8px;transition:width .6s ease">
                          <span style="font-size:12px;font-weight:700;color:#fff;white-space:nowrap">{val:,}</span>
                        </div>
                      </div>
                      <div style="width:52px;text-align:right;font-size:12px;font-weight:600;color:#64748b;flex-shrink:0">{pct:.1f}%</div>
                    </div>"""

                ticket_html = f"""
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.06)">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
    <div style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#475569">🎫 Ticket Volume by Source</div>
    <div style="font-size:12px;color:#64748b">Tổng: <strong style="color:#0f172a">{total_ticket:,}</strong> tickets</div>
  </div>
  {bar_rows}
  <div style="margin-top:12px;padding-top:12px;border-top:1px solid #f1f5f9;font-size:11px;color:#94a3b8">
    Livechat = Live Chat + Live chat_Merchant Support + Live chat_VietQR
  </div>
</div>"""
        except Exception as e:
            ticket_html = f'<div style="color:#ef4444;font-size:12px;padding:8px">Lỗi đọc Freshdesk: {e}</div>'

    if ticket_html:
        sections.append(ticket_html)

    # ── Click Source file analysis ────────────────────────────────────────
    click_html = ""
    comparison_html = ""
    try:
        df_click = _read_file(click_path)

        # Detect category and count columns
        cat_col = _find_col(df_click, ["category", "danh mục", "danh_muc", "cat", "name", "tên"])
        cnt_col = _find_col(df_click, ["click", "count", "số click", "so_click", "clicks", "total", "quantity", "số lượng"])

        if cat_col is None:
            # fallback: first string column
            str_cols = df_click.select_dtypes(include="object").columns
            cat_col = str_cols[0] if len(str_cols) else df_click.columns[0]
        if cnt_col is None:
            # fallback: first numeric column
            num_cols = df_click.select_dtypes(include="number").columns
            cnt_col = num_cols[0] if len(num_cols) else df_click.columns[1] if len(df_click.columns) > 1 else None

        if cat_col and cnt_col:
            df_click[cnt_col] = pd.to_numeric(df_click[cnt_col], errors="coerce").fillna(0)
            df_top15 = df_click[[cat_col, cnt_col]].copy()
            df_top15 = df_top15.sort_values(cnt_col, ascending=False).head(15).reset_index(drop=True)
            total_click = df_top15[cnt_col].sum()

            rows_top15 = ""
            for i, row in df_top15.iterrows():
                pct = row[cnt_col] / total_click * 100 if total_click else 0
                bg = "#f8fafc" if i % 2 == 0 else "#fff"
                rows_top15 += f"""<tr style="background:{bg}">
                  <td style="padding:8px 12px;font-size:12px;color:#64748b;font-weight:600">{i+1}</td>
                  <td style="padding:8px 12px;font-size:12px;color:#0f172a">{row[cat_col]}</td>
                  <td style="padding:8px 12px;font-size:12px;font-weight:700;color:#2563eb;text-align:right">{int(row[cnt_col]):,}</td>
                  <td style="padding:8px 12px;font-size:12px;color:#64748b;text-align:right">{pct:.1f}%</td>
                </tr>"""

            click_html = f"""
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
      <tbody>{rows_top15}</tbody>
    </table>
  </div>
</div>"""

            # ── Comparison: Click vs Ticket ─────────────────────────────
            if freshdesk_path and freshdesk_path.exists() and ticket_html and total_ticket:
                click_total_all = int(df_click[cnt_col].sum())

                comparison_html = f"""
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.06)">
  <div style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#475569;margin-bottom:16px">🔍 Click vs Ticket — Tổng quan</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div style="background:#eff6ff;border-radius:8px;padding:16px;text-align:center">
      <div style="font-size:11px;font-weight:600;color:#2563eb;text-transform:uppercase;letter-spacing:.4px">Tổng Click Chatbot</div>
      <div style="font-size:28px;font-weight:700;color:#1d4ed8;margin:8px 0">{click_total_all:,}</div>
      <div style="font-size:11px;color:#60a5fa">từ file Click Source - Category</div>
    </div>
    <div style="background:#f0fdf4;border-radius:8px;padding:16px;text-align:center">
      <div style="font-size:11px;font-weight:600;color:#16a34a;text-transform:uppercase;letter-spacing:.4px">Tổng Ticket Submit</div>
      <div style="font-size:28px;font-weight:700;color:#15803d;margin:8px 0">{total_ticket:,}</div>
      <div style="font-size:11px;color:#86efac">Chatbot + Livechat (Freshdesk)</div>
    </div>
  </div>
  <div style="margin-top:14px;padding:10px 14px;background:#fef9c3;border-radius:8px;font-size:12px;color:#92400e">
    <strong>Tỷ lệ chuyển đổi click → ticket:</strong>
    {(total_ticket/click_total_all*100 if click_total_all else 0):.1f}%
    &nbsp;·&nbsp; Cứ ~{int(click_total_all/total_ticket) if total_ticket else '—'} click → 1 ticket
  </div>
</div>"""
        else:
            click_html = '<div style="color:#f97316;font-size:12px;padding:8px">Không tìm được cột Category/Count trong file Click Source.</div>'
    except Exception as e:
        click_html = f'<div style="color:#ef4444;font-size:12px;padding:8px">Lỗi đọc Click Source: {e}</div>'

    if comparison_html:
        sections.append(comparison_html)
    if click_html:
        sections.append(click_html)

    if not sections:
        return ""

    return f"""
<div style="margin-bottom:28px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
    <div style="font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#0f172a">📈 B0 — Click Source &amp; Ticket Volume</div>
    <div style="flex:1;height:1px;background:#e2e8f0"></div>
  </div>
  {''.join(sections)}
</div>"""
