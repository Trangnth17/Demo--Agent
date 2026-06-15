"""
B6 — Enrich CSAT data with Freshdesk tickets.
Output: 5-sheet Excel + 7-section HTML (rootcause analysis + alignment + LLM insights).
"""
import asyncio
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

API_URL = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1/chat/completions"
API_KEY = os.getenv(
    "GREENNODE_API_KEY",
    "vn-MzRcWF_ZyN550_Ui2-h2U1mWUj0a2Vc39825bdede74944bb692a02fec35fde2d1R3_6q-VtqLzUg__7mh3w_IdJSRgr",
)
MODEL = "google/gemma-4-31b-it"
CONCURRENCY_LLM = 6
JOIN_WINDOW_DAYS = 7

# ── LLM system prompts ─────────────────────────────────────────────────────────

LLM_DESC_SYSTEM = """Bạn là chuyên gia phân tích ticket hỗ trợ khách hàng ZaloPay.
Đọc mô tả ticket và trả về JSON (không có text khác):
{
  "summary": "<tóm tắt 1 câu vấn đề thực tế>",
  "root_cause": "<lỗi hệ thống|lỗi user|lỗi đối tác|chính sách|không rõ>",
  "urgency": <1-5>,
  "topic_label": "<tên nhóm taxonomy>"
}"""

LLM_ALIGN_SYSTEM = """So sánh phản hồi survey và mô tả ticket của cùng khách hàng ZaloPay.
Trả về JSON (không có text khác):
{"alignment": "<match|partial|mismatch|unclear>", "reasoning": "<1 câu>"}
- match: user nói đúng vấn đề được ghi trong ticket
- partial: liên quan nhưng chưa khớp hoàn toàn
- mismatch: user phàn nàn khác với nội dung ticket thực tế
- unclear: không đủ thông tin để so sánh"""

# ── Freshdesk → B4 label mapping (67 entries) ─────────────────────────────────

TICKET_TO_TAXONOMY: dict[str, str] = {
    # KTGD
    "ktgd-giao dịch thành công":                             "Chuyển khoản lỗi",
    "ktgd-chưa nhận được dịch vụ":                           "Chưa nhận dịch vụ",
    "ktgd-yêu cầu hoàn hủy":                                 "Hoàn tiền",
    "ktgd-thu hồi giao dịch nhầm":                           "Hoàn tiền",
    "ktgd-trạng thái hoàn tiền":                             "Hoàn tiền",
    "ktgd-vietqr":                                            "Chuyển khoản lỗi",
    "ktgd-khiếu nại sản phẩm, chất lượng dịch vụ":          "Chuyển khoản lỗi",
    "ktgd-phí dịch vụ":                                      "Chuyển khoản lỗi",
    "ktgd-gửi sao kê/lsgd":                                  "Tính năng app lỗi",
    "ktgd-xuất vat":                                          "Tính năng app lỗi",
    "ktgd-thanh toán trùng":                                  "Chuyển khoản lỗi",
    # TT
    "tt-tpe thất bại":                                        "Tính năng app lỗi",
    "tt-thu hồi giao dịch napas ibft nhầm":                  "Hoàn tiền",
    "tt-tpe không có giao dịch":                              "Tính năng app lỗi",
    # TK
    "tk-hướng dẫn bảo mật thông tin tài khoản":              "Bảo mật / Tài khoản",
    "tk-thay đổi thông tin tài khoản zalopay":                "Thay đổi thông tin",
    "tk-thay đổi thông tin tài khoản zalopay - 1 tài khoản": "Thay đổi thông tin",
    "tk-thay đổi thông tin tài khoản zalopay - 2 tài khoản": "Thay đổi thông tin",
    "tk-hủy đăng ký sản phẩm tài chính":                     "Hủy dịch vụ",
    "tk-mở khóa tài khoản zalopay":                           "Bảo mật / Tài khoản",
    "tk-khóa tài khoản zalopay":                              "Bảo mật / Tài khoản",
    "tk-đóng/tất toán tài khoản":                             "Hủy dịch vụ",
    "tk-thanh lý số dư cho chủ ví - 1 tài khoản":            "Hủy dịch vụ",
    "tk-khiếu nại gian lận của chủ ví":                       "Bảo mật / Tài khoản",
    "tk-khiếu nại gian lận của chủ thẻ":                      "Bảo mật / Tài khoản",
    "tk-hướng dẫn đăng ký/đăng nhập zalopay":                "Bảo mật / Tài khoản",
    # UD
    "ud-gỡ liên kết thẻ/tài khoản ngân hàng":                "Bảo mật / Tài khoản",
    "ud-liên kết thẻ/tài khoản ngân hàng":                   "Tính năng app lỗi",
    "ud-báo lỗi chung-xin thêm thông tin":                    "Tính năng app lỗi",
    "ud-bị treo/ loading/ trắng màn hình":                    "Tính năng app lỗi",
    "ud-lỗi giao diện (ui)":                                  "Tính năng app lỗi",
    "ud-hủy liên kết autodebit":                               "Hủy dịch vụ",
    "ud-liên kết autodebit":                                   "Tính năng app lỗi",
    "ud-tự thoát/văng":                                       "Tính năng app lỗi",
    # KM
    "km-tư vấn chương trình khuyến mãi":                      "Ưu đãi / Voucher",
    "km-không nhận được cashback":                             "Ưu đãi / Voucher",
    "km-không sử dụng được voucher":                           "Ưu đãi / Voucher",
    "km-không nhận được quà":                                  "Ưu đãi / Voucher",
    "km-không nhận được xu":                                   "Ưu đãi / Voucher",
    "km-blacklist/greylist":                                   "Ưu đãi / Voucher",
    "km-không nhận/đổi được voucher":                          "Ưu đãi / Voucher",
    "km-không sử dụng được direct discount (giảm giá)":        "Ưu đãi / Voucher",
    "km-lỗi xác thực ngân hàng":                              "Xác thực / eKYC",
    # DVTC
    "dvtc-đăng ký dịch vụ":                                   "Vay tiền / Ví trả sau",
    "dvtc-tài khoản bị khóa hạn mức":                         "Vay tiền / Ví trả sau",
    "dvtc-mở khóa tài khoản":                                 "Vay tiền / Ví trả sau",
    "dvtc-thay đổi thông tin tài khoản":                      "Vay tiền / Ví trả sau",
    "dvtc-tái ký hợp đồng":                                    "Vay tiền / Ví trả sau",
    "dvtc-khóa tài khoản":                                    "Vay tiền / Ví trả sau",
    # KYC
    "kyc-hỗ trợ xác thực tài khoản":                          "Xác thực / eKYC",
    "kyc-hướng dẫn xác thực tài khoản":                       "Xác thực / eKYC",
    "kyc-phản hồi nguyên nhân từ chối":                        "Xác thực / eKYC",
    # MKTT
    "mktt-hỗ trợ duyệt mật khẩu thanh toán":                  "Bảo mật / Tài khoản",
    "mktt-quên mật khẩu - tư vấn thao thác":                  "Bảo mật / Tài khoản",
    "mktt-hướng dẫn lấy lại mật khẩu thanh toán":             "Bảo mật / Tài khoản",
    "mktt-phản hồi nguyên nhân bị từ chối":                    "Bảo mật / Tài khoản",
    # Tư vấn tính năng
    "tư vấn tính năng-cách sử dụng/ thanh toán":              "Bot không giải quyết",
    "tư vấn tính năng-cách sử dụng/thanh toán":               "Bot không giải quyết",
    "tư vấn tính năng-hạn mức":                               "Tính năng app lỗi",
    "tư vấn tính năng-phí dịch vụ":                           "Tính năng app lỗi",
    "tư vấn tính năng-điều kiện sử dụng":                     "Tính năng app lỗi",
    "tư vấn tính năng-lãi/tiền lời":                          "Tiết kiệm / Sinh lời",
    "tư vấn tính năng-nguồn tiền thanh toán":                 "Tính năng app lỗi",
    # MC_
    "mc_kiểm tra trạng thái giao dịch":                        "Chuyển khoản lỗi",
    # VMB
    "vmb_hỗ trợ hủy/hoàn vé máy bay":                         "Hoàn tiền",
    "vmb_vé ticket on process (top)":                          "Chưa nhận dịch vụ",
    # Partner
    "123phim_thanh toán thành công không nhận được mã vé":     "Chưa nhận dịch vụ",
}

LABEL_TO_GROUP: dict[str, str] = {
    "Hoàn tiền": "GD & Tiền", "Tự động trừ tiền": "GD & Tiền",
    "Nạp tiền / Gói data": "GD & Tiền", "Chưa nhận dịch vụ": "GD & Tiền",
    "Chuyển khoản lỗi": "GD & Tiền",
    "Khó kết nối nhân viên": "CSKH", "Phản hồi chậm / Chưa xử lý": "CSKH",
    "Bot không giải quyết": "Chatbot",
    "Xác thực / eKYC": "Tính năng", "Vay tiền / Ví trả sau": "Tính năng",
    "Bảo mật / Tài khoản": "Tính năng", "Hủy dịch vụ": "Tính năng",
    "Thay đổi thông tin": "Tính năng", "Tiết kiệm / Sinh lời": "Tính năng",
    "Ưu đãi / Voucher": "Tính năng", "Tính năng app lỗi": "Tính năng",
    "Feedback tiêu cực": "Feedback", "Chửi bới": "Feedback",
    "Khác / Vô nghĩa": "Khác", "Khác / Vấn đề khác": "Khác",
}

# ── Excel / file helpers ───────────────────────────────────────────────────────

def _read_any_excel(path: Path) -> pd.DataFrame:
    for engine in ["openpyxl", "xlrd"]:
        try:
            return pd.read_excel(path, engine=engine)
        except Exception:
            continue
    return _read_spreadsheetml(path)


def _read_spreadsheetml(path: Path) -> pd.DataFrame:
    for enc in ["utf-8-sig", "utf-8", "utf-16", "cp1252"]:
        try:
            raw = path.read_bytes().decode(enc)
            break
        except UnicodeDecodeError:
            continue
    NS = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}
    root = ET.fromstring(raw)
    ws = root.find(".//ss:Worksheet", NS)
    if ws is None:
        raise ValueError("SpreadsheetML: no Worksheet found")
    table = ws.find("ss:Table", NS)
    rows_data = []
    for row in table.findall("ss:Row", NS):
        cells, idx = {}, 1
        for cell in row.findall("ss:Cell", NS):
            ss_idx = cell.get("{urn:schemas-microsoft-com:office:spreadsheet}Index")
            if ss_idx:
                idx = int(ss_idx)
            data = cell.find("ss:Data", NS)
            cells[idx] = data.text if data is not None else ""
            idx += 1
        rows_data.append(cells)
    if not rows_data:
        return pd.DataFrame()
    max_col = max(max(r.keys()) for r in rows_data)
    records = [{c: r.get(c, "") for c in range(1, max_col + 1)} for r in rows_data]
    df = pd.DataFrame(records)
    df.columns = [df.iloc[0].get(c, c) for c in df.columns]
    return df.iloc[1:].reset_index(drop=True)


def _clean_uid(val) -> str:
    if pd.isna(val):
        return ""
    s = str(val).strip()
    return s[:-2] if s.endswith(".0") else s


def _extract_uid_from_text(text: str) -> str:
    m = re.search(r"\b\d{15}\b", str(text))
    return m.group() if m else ""


def _match_result(survey_label: str, ticket_issue: str) -> str:
    key = str(ticket_issue).lower().strip()
    mapped = TICKET_TO_TAXONOMY.get(key)
    if mapped is None:
        return "unknown"
    if mapped == survey_label:
        return "exact"
    if LABEL_TO_GROUP.get(mapped) == LABEL_TO_GROUP.get(survey_label):
        return "group_match"
    return "mismatch"


def _find_col(df: pd.DataFrame, candidates: list) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    for c in df.columns:
        for cand in candidates:
            if cand.lower() in c.lower():
                return c
    return None


# ── Async LLM batch helpers ────────────────────────────────────────────────────

async def _llm_classify_desc_batch(descriptions: list[str]) -> list[dict]:
    """Classify Freshdesk ticket descriptions: summary, root_cause, urgency, topic_label."""
    fallback = {"summary": "—", "root_cause": "không rõ", "urgency": 1, "topic_label": "Khác / Vô nghĩa"}
    sem = asyncio.Semaphore(CONCURRENCY_LLM)
    results: list[dict] = [dict(fallback) for _ in descriptions]

    async def _one(i: int):
        desc = str(descriptions[i]).strip()
        if not desc or len(desc) < 5:
            return
        async with sem:
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            API_URL,
                            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                            json={
                                "model": MODEL,
                                "messages": [
                                    {"role": "system", "content": LLM_DESC_SYSTEM},
                                    {"role": "user", "content": f"Mô tả ticket: {desc[:600]}"},
                                ],
                                "max_tokens": 200, "temperature": 0.1, "top_p": 0.7,
                            },
                        )
                        resp.raise_for_status()
                        content = resp.json()["choices"][0]["message"]["content"].strip()
                        m = re.search(r"\{.*\}", content, re.DOTALL)
                        if m:
                            results[i] = json.loads(m.group())
                            return
                except Exception:
                    if attempt == 2:
                        pass

    await asyncio.gather(*[_one(i) for i in range(len(descriptions))])
    return results


async def _llm_alignment_batch(pairs: list[tuple]) -> list[str]:
    """Compare (free_comment, ticket_description) → alignment label."""
    sem = asyncio.Semaphore(CONCURRENCY_LLM)
    results: list[str] = ["unclear"] * len(pairs)

    async def _one(i: int):
        comment, description = pairs[i]
        comment = str(comment).strip()
        description = str(description).strip()
        if not comment or not description or len(comment) < 2 or len(description) < 2:
            return
        prompt = f"Survey feedback: {comment[:300]}\n\nTicket description: {description[:400]}"
        async with sem:
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            API_URL,
                            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                            json={
                                "model": MODEL,
                                "messages": [
                                    {"role": "system", "content": LLM_ALIGN_SYSTEM},
                                    {"role": "user", "content": prompt},
                                ],
                                "max_tokens": 100, "temperature": 0.1, "top_p": 0.7,
                            },
                        )
                        resp.raise_for_status()
                        content = resp.json()["choices"][0]["message"]["content"].strip()
                        m = re.search(r'"alignment"\s*:\s*"([^"]+)"', content)
                        if m:
                            val = m.group(1).lower()
                            if val in ("match", "partial", "mismatch", "unclear"):
                                results[i] = val
                            return
                except Exception:
                    if attempt == 2:
                        pass

    await asyncio.gather(*[_one(i) for i in range(len(pairs))])
    return results


# ── Synchronous join computation ───────────────────────────────────────────────

def _build_join(
    df_classified: pd.DataFrame, fd: pd.DataFrame,
    uid_col, desc_col, issue_col, appid_col, partner_col, error_col, created_col,
) -> tuple[list[dict], list]:
    fd = fd.copy()
    fd["uid_clean"] = ""
    if uid_col:
        fd["uid_clean"] = fd[uid_col].apply(_clean_uid)
    if desc_col:
        mask = fd["uid_clean"] == ""
        fd.loc[mask, "uid_clean"] = fd.loc[mask, desc_col].apply(_extract_uid_from_text)

    if created_col:
        fd["ticket_date"] = pd.to_datetime(fd[created_col], errors="coerce", dayfirst=True)
    else:
        fd["ticket_date"] = pd.NaT

    df = df_classified.copy()
    if "User ID (zalopayid)" in df.columns:
        df["uid_clean"] = df["User ID (zalopayid)"].apply(_clean_uid)
    elif "User ID" in df.columns:
        df["uid_clean"] = df["User ID"].apply(_clean_uid)
    else:
        df["uid_clean"] = ""

    if "Thời gian" in df.columns:
        df["survey_date"] = pd.to_datetime(df["Thời gian"], errors="coerce")
    else:
        df["survey_date"] = pd.NaT

    pairs: list[dict] = []
    no_ticket_rows: list = []

    for _, srow in df.iterrows():
        uid = srow["uid_clean"]
        sdate = srow.get("survey_date")
        label = srow.get("primary_label", "")
        comment = srow.get("Free_Comment", "")

        fd_uid = fd[fd["uid_clean"] == uid] if uid else pd.DataFrame()

        if fd_uid.empty or pd.isna(sdate):
            no_ticket_rows.append(srow)
            continue

        matched = fd_uid[fd_uid["ticket_date"].apply(
            lambda d: not pd.isna(d) and abs((d - sdate).days) <= JOIN_WINDOW_DAYS
        )]

        if matched.empty:
            no_ticket_rows.append(srow)
            continue

        multi = len(matched) > 1
        for _, trow in matched.iterrows():
            td = trow.get("ticket_date")
            chi_tiet = trow.get(issue_col, "") if issue_col else ""
            description = trow.get(desc_col, "") if desc_col else ""
            mr = _match_result(label, chi_tiet)
            mapped_b4 = TICKET_TO_TAXONOMY.get(str(chi_tiet).lower().strip())
            pairs.append({
                "uid":                uid,
                "survey_date":        sdate.strftime("%Y-%m-%d") if pd.notna(sdate) else "",
                "rating":             srow.get("Đánh giá (sao)", ""),
                "primary_label":      label,
                "free_comment":       comment,
                "ticket_date":        td.strftime("%Y-%m-%d") if pd.notna(td) else "",
                "day_diff":           abs((td - sdate).days) if pd.notna(td) else "",
                "chi_tiet_van_de":    chi_tiet,
                "ticket_sub_issue":   mapped_b4 or "",
                "ticket_description": str(description)[:800] if description else "",
                "match_result":       mr,
                "app_id":             trow.get(appid_col, "") if appid_col else "",
                "doi_tac":            trow.get(partner_col, "") if partner_col else "",
                "ma_loi":             trow.get(error_col, "") if error_col else "",
                "multi_ticket":       multi,
            })

    return pairs, no_ticket_rows


# ── LLM insights (sync, wrapped in asyncio.to_thread by caller) ────────────────

def _llm_insights(stats: dict) -> str:
    prompt = f"""Dựa trên data phân tích CSAT × Freshdesk sau, hãy viết 4-6 bullet insight
ngắn gọn bằng tiếng Việt cho manager, tập trung vào nguyên nhân thật sự
user không hài lòng và đề xuất cải thiện cụ thể.

Data:
- Tổng survey 1-2★: {stats['total_neg']}
- Số UID có ticket: {stats['with_ticket']} ({stats['match_rate']}%)
- Tỷ lệ mismatch: {stats['mismatch_rate']}%
- Nhóm mismatch cao nhất: {stats['top_mismatch']}
- AppID nóng nhất: {stats['top_appid']}
- Tỷ lệ no-ticket: {stats['no_ticket_rate']}%
- Top issues: {stats['top_issues']}

Chỉ viết bullet (bắt đầu bằng •), không có tiêu đề, không giải thích thêm."""

    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                API_URL,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 400, "temperature": 0.3},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return "• Không thể tạo insight tự động — vui lòng kiểm tra kết nối API."


def _write_excel_5sheets(out_path, df_pairs, df_no_ticket, df_mismatch, df_appid, df_rootcause):
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df_pairs.to_excel(writer, sheet_name="matched_pairs", index=False)
        df_no_ticket.to_excel(writer, sheet_name="no_ticket", index=False)
        df_mismatch.to_excel(writer, sheet_name="mismatch_review", index=False)
        df_appid.to_excel(writer, sheet_name="appid_heatmap", index=False)
        df_rootcause.to_excel(writer, sheet_name="rootcause_summary", index=False)


# ── Main entry point (async) ───────────────────────────────────────────────────

async def enrich_tickets(
    df_classified: pd.DataFrame,
    ticket_path: Path,
    job_id: str,
    period: str = "",
) -> tuple[Path, Path]:
    # 1. Read Freshdesk file (IO)
    fd = await asyncio.to_thread(_read_any_excel, ticket_path)
    fd.columns = fd.columns.str.strip()

    # 2. Detect columns
    uid_col     = _find_col(fd, ["UID", "uid", "User ID", "userid", "ZaloPay ID"])
    desc_col    = _find_col(fd, ["Description", "description", "Mô tả", "Mo ta"])
    issue_col   = _find_col(fd, ["Chi tiết vấn đề", "chi_tiet_van_de", "issue", "Issue"])
    appid_col   = _find_col(fd, ["AppID", "App ID", "app_id"])
    partner_col = _find_col(fd, ["Đối tác", "doi_tac", "partner"])
    error_col   = _find_col(fd, ["Mã lỗi", "ma_loi", "error_code"])
    created_col = _find_col(fd, ["Created time", "created_time", "Created At", "Ngày tạo"])

    # 3. Join (CPU, run in thread)
    pairs, no_ticket_rows = await asyncio.to_thread(
        _build_join, df_classified, fd,
        uid_col, desc_col, issue_col, appid_col, partner_col, error_col, created_col,
    )

    # 4. LLM description classify + alignment analysis (async, parallel)
    if pairs and desc_col:
        descriptions = [p["ticket_description"] for p in pairs]
        align_pairs  = [(p["free_comment"], p["ticket_description"]) for p in pairs]
        desc_results, align_results = await asyncio.gather(
            _llm_classify_desc_batch(descriptions),
            _llm_alignment_batch(align_pairs),
        )
        for i, p in enumerate(pairs):
            dr = desc_results[i]
            p["desc_summary"]     = dr.get("summary", "—")
            p["desc_root_cause"]  = dr.get("root_cause", "không rõ")
            p["desc_urgency"]     = int(dr.get("urgency", 1))
            p["desc_topic_label"] = dr.get("topic_label", "—")
            p["alignment"]        = align_results[i]
    else:
        for p in pairs:
            p.update({"desc_summary": "—", "desc_root_cause": "không rõ",
                      "desc_urgency": 1, "desc_topic_label": "—", "alignment": "unclear"})

    # 5. Build DataFrames
    default_cols = [
        "uid", "survey_date", "rating", "primary_label", "free_comment",
        "ticket_date", "day_diff", "chi_tiet_van_de", "ticket_sub_issue",
        "ticket_description", "desc_summary", "desc_root_cause", "desc_urgency",
        "desc_topic_label", "match_result", "alignment", "app_id", "doi_tac",
        "ma_loi", "multi_ticket",
    ]
    df_pairs = pd.DataFrame(pairs) if pairs else pd.DataFrame(columns=default_cols)
    df_no_ticket = pd.DataFrame(no_ticket_rows).reset_index(drop=True) if no_ticket_rows else pd.DataFrame()
    df_mismatch  = df_pairs[df_pairs["match_result"] == "mismatch"].copy() if len(df_pairs) else pd.DataFrame()

    # AppID heatmap pivot
    if len(df_pairs) and "app_id" in df_pairs.columns and "primary_label" in df_pairs.columns:
        df_appid = df_pairs.pivot_table(
            index="app_id", columns="primary_label", values="uid",
            aggfunc="count", fill_value=0,
        )
        df_appid["Total"] = df_appid.sum(axis=1)
        df_appid = df_appid.sort_values("Total", ascending=False).reset_index()
    else:
        df_appid = pd.DataFrame()

    # Rootcause summary
    if len(df_pairs) and "desc_root_cause" in df_pairs.columns:
        rc_grp = df_pairs.groupby("desc_root_cause")
        df_rootcause = pd.DataFrame({
            "root_cause": list(rc_grp.size().index),
            "count": list(rc_grp.size().values),
            "avg_urgency": list(rc_grp["desc_urgency"].mean().round(1).values),
        }).sort_values("count", ascending=False).reset_index(drop=True)
    else:
        df_rootcause = pd.DataFrame()

    # 6. Compute stats
    total_neg    = len(df_classified)
    with_ticket  = int(df_pairs["uid"].nunique()) if len(df_pairs) else 0
    match_rate   = round(with_ticket / total_neg * 100, 1) if total_neg else 0
    mismatch_n   = len(df_mismatch)
    mismatch_rate  = round(mismatch_n / len(df_pairs) * 100, 1) if len(df_pairs) else 0
    no_ticket_rate = round(len(no_ticket_rows) / total_neg * 100, 1) if total_neg else 0

    top_mismatch = "—"
    if len(df_mismatch) and "primary_label" in df_mismatch.columns:
        vc = df_mismatch["primary_label"].value_counts()
        if len(vc):
            top_mismatch = vc.index[0]

    top_appid = "—"
    if len(df_pairs) and "app_id" in df_pairs.columns:
        vc = df_pairs["app_id"].value_counts()
        if len(vc):
            top_appid = f"{vc.index[0]} ({vc.iloc[0]} pairs)"

    top_issues_str = "—"
    if len(df_pairs) and "primary_label" in df_pairs.columns:
        top5 = df_pairs["primary_label"].value_counts().head(5)
        top_issues_str = ", ".join(f"{k}: {v}" for k, v in top5.items())

    # Match rate by issue group
    match_by_label = []
    if len(df_pairs):
        for lbl, grp in df_pairs.groupby("primary_label"):
            total_l = len(grp)
            exact_l = (grp["match_result"] == "exact").sum()
            mm_l    = (grp["match_result"] == "mismatch").sum()
            match_by_label.append({
                "label": lbl, "total": total_l, "matched": int(exact_l),
                "match_rate": round(exact_l / total_l * 100, 1) if total_l else 0,
                "mismatch_pct": round(mm_l / total_l * 100, 1) if total_l else 0,
            })
        match_by_label.sort(key=lambda x: x["total"], reverse=True)

    # AppID summary rows
    appid_rows = []
    if len(df_pairs) and "app_id" in df_pairs.columns:
        for aid, grp in df_pairs.groupby("app_id"):
            if not aid:
                continue
            mm = (grp["match_result"] == "mismatch").sum()
            appid_rows.append({
                "app_id": aid, "total": len(grp),
                "top_issue": grp["primary_label"].value_counts().index[0] if len(grp) else "—",
                "mismatch_pct": round(mm / len(grp) * 100, 1) if len(grp) else 0,
            })
        appid_rows.sort(key=lambda x: x["total"], reverse=True)

    # Flow pairs (top 60)
    flow_pairs = []
    if len(df_pairs):
        for _, r in df_pairs.head(60).iterrows():
            flow_pairs.append({
                "survey_issue": r.get("primary_label", ""),
                "ticket_issue": r.get("chi_tiet_van_de", ""),
                "match_result": r.get("match_result", ""),
            })

    # Detail rows
    detail_rows = []
    if len(df_pairs):
        for _, r in df_pairs.iterrows():
            uid_str = str(r.get("uid", ""))
            detail_rows.append({
                "uid":          uid_str[-8:] if len(uid_str) >= 8 else uid_str,
                "survey_issue": r.get("primary_label", ""),
                "free_comment": str(r.get("free_comment", ""))[:80],
                "ticket_issue": r.get("chi_tiet_van_de", ""),
                "app_id":       r.get("app_id", ""),
                "doi_tac":      r.get("doi_tac", ""),
                "match_result": r.get("match_result", ""),
                "alignment":    r.get("alignment", "unclear"),
                "day_diff":     r.get("day_diff", ""),
            })

    # Rootcause analysis data for HTML
    rc_rows_data = []
    align_dist_data: dict = {}
    if len(df_pairs):
        if "desc_root_cause" in df_pairs.columns:
            total_p = len(df_pairs)
            for rc, cnt in df_pairs["desc_root_cause"].value_counts().items():
                avg_urg = df_pairs[df_pairs["desc_root_cause"] == rc]["desc_urgency"].mean()
                rc_rows_data.append({
                    "root_cause": rc, "count": int(cnt),
                    "pct": round(cnt / total_p * 100, 1),
                    "avg_urgency": round(float(avg_urg), 1) if not pd.isna(avg_urg) else 1.0,
                })
        if "alignment" in df_pairs.columns:
            total_p = len(df_pairs)
            for al in ["match", "partial", "mismatch", "unclear"]:
                cnt = int((df_pairs["alignment"] == al).sum())
                align_dist_data[al] = {"count": cnt, "pct": round(cnt / total_p * 100, 1) if total_p else 0}

    # 7. Write Excel 5 sheets (IO, thread)
    fname_xlsx = f"CSAT B6 {period}.xlsx" if period else f"b6_pairs_{job_id}.xlsx"
    out_xlsx = OUTPUT_DIR / fname_xlsx
    await asyncio.to_thread(
        _write_excel_5sheets, out_xlsx, df_pairs, df_no_ticket, df_mismatch, df_appid, df_rootcause,
    )

    # 8. LLM insights (sync, thread)
    stats = {
        "total_neg": total_neg, "with_ticket": with_ticket, "match_rate": match_rate,
        "mismatch_rate": mismatch_rate, "top_mismatch": top_mismatch,
        "top_appid": top_appid, "no_ticket_rate": no_ticket_rate, "top_issues": top_issues_str,
    }
    insights_text = await asyncio.to_thread(_llm_insights, stats)
    insight_bullets = [b.strip() for b in re.split(r"\n+", insights_text) if b.strip()]

    # 9. Build HTML (7 sections)
    html = _build_b6_html(
        period=period or job_id,
        stats=stats,
        match_by_label=match_by_label,
        appid_rows=appid_rows,
        flow_pairs=flow_pairs,
        detail_rows=detail_rows,
        rc_rows=rc_rows_data,
        align_dist=align_dist_data,
        insight_bullets=insight_bullets,
    )
    fname_html = f"CSAT B6 REPORT {period}.html" if period else f"b6_report_{job_id}.html"
    out_html = OUTPUT_DIR / fname_html
    await asyncio.to_thread(out_html.write_text, html, encoding="utf-8")

    return out_xlsx, out_html


# ── HTML builder ──────────────────────────────────────────────────────────────

def _badge(mr: str) -> str:
    colors = {"exact": "#16a34a", "group_match": "#2563eb", "mismatch": "#dc2626", "unknown": "#64748b"}
    labels = {"exact": "Exact", "group_match": "Group", "mismatch": "Mismatch", "unknown": "Unknown"}
    c = colors.get(mr, "#64748b")
    return (f'<span style="background:{c}22;color:{c};border:1px solid {c}55;'
            f'border-radius:4px;padding:2px 7px;font-size:10px;font-weight:700">'
            f'{labels.get(mr, mr)}</span>')


def _align_badge(al: str) -> str:
    colors = {"match": "#16a34a", "partial": "#2563eb", "mismatch": "#dc2626", "unclear": "#64748b"}
    c = colors.get(al, "#64748b")
    return (f'<span style="background:{c}22;color:{c};border:1px solid {c}55;'
            f'border-radius:4px;padding:2px 7px;font-size:10px;font-weight:700">{al}</span>')


def _build_b6_html(
    *, period, stats, match_by_label, appid_rows, flow_pairs,
    detail_rows, rc_rows, align_dist, insight_bullets,
) -> str:
    # KPI cards
    kpi_cards = [
        ("Tổng survey 1-2★", stats["total_neg"], "#ef4444"),
        ("UID có ticket", stats["with_ticket"], "#2563eb"),
        ("Match rate", f"{stats['match_rate']}%", "#16a34a"),
        ("Mismatch rate", f"{stats['mismatch_rate']}%", "#dc2626"),
        ("No-ticket rate", f"{stats['no_ticket_rate']}%", "#f97316"),
    ]
    kpi_html = "".join(
        f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;'
        f'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
        f'<div style="font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase;'
        f'letter-spacing:.5px;margin-bottom:6px">{label}</div>'
        f'<div style="font-size:24px;font-weight:800;color:{color}">{value}</div></div>'
        for label, value, color in kpi_cards
    )

    mr_rows_html = "".join(
        f"<tr><td>{r['label']}</td><td style='text-align:right'>{r['total']}</td>"
        f"<td style='text-align:right'>{r['matched']}</td>"
        f"<td style='text-align:right;color:#16a34a;font-weight:600'>{r['match_rate']}%</td>"
        f"<td style='text-align:right;color:#dc2626;font-weight:600'>{r['mismatch_pct']}%</td></tr>"
        for r in match_by_label
    )

    appid_html = "".join(
        f"<tr style='background:{'#fef2f2' if r['mismatch_pct'] >= 50 else 'transparent'}'>"
        f"<td>{r['app_id']}</td><td style='text-align:right'>{r['total']}</td>"
        f"<td>{r['top_issue']}</td>"
        f"<td style='text-align:right;color:{'#dc2626' if r['mismatch_pct'] >= 50 else 'inherit'};"
        f"font-weight:600'>{r['mismatch_pct']}%</td></tr>"
        for r in appid_rows[:30]
    )

    flow_html = "".join(
        f'<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #f1f5f9">'
        f'<div style="flex:1;font-size:12px;background:#eff6ff;border-radius:6px;padding:4px 8px">'
        f'{p["survey_issue"]}</div>'
        f'<span style="color:#94a3b8;font-size:16px">→</span>'
        f'<div style="flex:1;font-size:12px;background:#f8fafc;border-radius:6px;padding:4px 8px">'
        f'{p["ticket_issue"] or "—"}</div>'
        f'{_badge(p["match_result"])}</div>'
        for p in flow_pairs
    )

    detail_html = "".join(
        f"<tr data-mr='{r['match_result']}' data-appid='{r['app_id']}'>"
        f"<td style='color:#64748b;font-size:11px'>...{r['uid']}</td>"
        f"<td>{r['survey_issue']}</td>"
        f"<td style='max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
        f"color:#475569' title='{r['free_comment']}'>{r['free_comment']}</td>"
        f"<td>{r['ticket_issue']}</td>"
        f"<td style='font-size:11px'>{r['app_id']}</td>"
        f"<td style='font-size:11px'>{r['doi_tac']}</td>"
        f"<td>{_badge(r['match_result'])}</td>"
        f"<td>{_align_badge(r['alignment'])}</td>"
        f"<td style='text-align:right'>{r['day_diff']}</td></tr>"
        for r in detail_rows
    )

    # Rootcause rows
    urgency_colors = {1: "#94a3b8", 2: "#3b82f6", 3: "#f59e0b", 4: "#f97316", 5: "#ef4444"}
    rc_html = ""
    for r in rc_rows:
        urg_int = min(5, max(1, int(round(r.get("avg_urgency", 1)))))
        urg_c   = urgency_colors[urg_int]
        bar_w   = min(200, round(r.get("pct", 0) * 2))
        rc_html += (
            f"<tr><td style='font-weight:600'>{r['root_cause']}</td>"
            f"<td style='text-align:right'>{r['count']}</td>"
            f"<td><div style='display:flex;align-items:center;gap:8px'>"
            f"<div style='width:200px;height:8px;background:#2563eb11;border-radius:4px;overflow:hidden'>"
            f"<div style='height:100%;width:{bar_w}px;background:#2563eb;border-radius:4px'></div></div>"
            f"<span style='font-size:12px;color:#2563eb;font-weight:600'>{r['pct']}%</span></div></td>"
            f"<td style='text-align:center'><span style='color:{urg_c};font-weight:700'>{r['avg_urgency']}★</span></td></tr>"
        )

    # Alignment rows
    align_colors = {"match": "#16a34a", "partial": "#2563eb", "mismatch": "#dc2626", "unclear": "#64748b"}
    align_vn = {"match": "Khớp", "partial": "Khớp một phần", "mismatch": "Không khớp", "unclear": "Không rõ"}
    al_html = ""
    for al in ["match", "partial", "mismatch", "unclear"]:
        if al in align_dist:
            d = align_dist[al]
            c = align_colors[al]
            bar_w = min(200, round(d["pct"] * 2))
            al_html += (
                f"<tr><td>{_align_badge(al)} <span style='margin-left:6px'>{align_vn[al]}</span></td>"
                f"<td style='text-align:right'>{d['count']}</td>"
                f"<td><div style='display:flex;align-items:center;gap:8px'>"
                f"<div style='width:200px;height:8px;background:{c}22;border-radius:4px;overflow:hidden'>"
                f"<div style='height:100%;width:{bar_w}px;background:{c};border-radius:4px'></div></div>"
                f"<span style='font-size:12px;color:{c};font-weight:600'>{d['pct']}%</span></div></td></tr>"
            )

    insight_html = "".join(
        f'<li style="margin-bottom:8px;line-height:1.6">{b.lstrip("•- ").strip()}</li>'
        for b in insight_bullets
    )

    appid_filter_opts = "".join(f'<option>{r["app_id"]}</option>' for r in appid_rows[:20])

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CSAT B6 REPORT {period}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#f8fafc;color:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;padding:24px;min-width:900px}}
h2{{font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#0f172a;margin:28px 0 12px;padding-bottom:8px;border-bottom:1.5px solid #e2e8f0}}
h3{{font-size:12px;font-weight:600;color:#475569;margin:14px 0 8px;text-transform:uppercase;letter-spacing:.4px}}
.card-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:28px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden}}
th{{padding:9px 12px;font-size:11px;font-weight:600;color:#64748b;text-align:left;background:#f8fafc;border-bottom:1.5px solid #e2e8f0}}
td{{padding:8px 12px;border-bottom:1px solid #f1f5f9;font-size:12px;vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
.flow-wrap{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;max-height:420px;overflow-y:auto}}
.insight-box{{background:linear-gradient(135deg,#1e1b4b,#312e81);border-radius:12px;padding:20px 24px;color:#e2e8f0}}
.insight-box ul{{padding-left:18px}}
.insight-box li{{color:#e2e8f0}}
select{{border:1px solid #e2e8f0;border-radius:6px;padding:4px 8px;font-size:12px;margin-right:8px;background:#fff}}
.analysis-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:4px}}
</style>
</head>
<body>

<div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:24px;padding-bottom:16px;border-bottom:1.5px solid #e2e8f0">
  <div>
    <div style="font-size:20px;font-weight:700">CSAT B6 — Freshdesk Enrichment &amp; Rootcause</div>
    <div style="color:#475569;margin-top:4px">ZaloPay Customer Service · Kỳ {period}</div>
  </div>
  <div style="text-align:right;font-size:12px;color:#94a3b8">{datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
</div>

<h2>1. KPI Summary</h2>
<div class="card-grid">{kpi_html}</div>

<h2>2. Match Rate theo Nhóm Issue</h2>
<table>
  <thead><tr><th>Primary Label (B4)</th><th style="text-align:right">Tổng</th><th style="text-align:right">Có ticket</th><th style="text-align:right">Match rate</th><th style="text-align:right">Mismatch</th></tr></thead>
  <tbody>{mr_rows_html or '<tr><td colspan="5" style="text-align:center;color:#94a3b8">Không có dữ liệu</td></tr>'}</tbody>
</table>

<h2>3. AppID Heatmap</h2>
<table>
  <thead><tr><th>AppID</th><th style="text-align:right">Tổng ticket</th><th>Top issue</th><th style="text-align:right">Mismatch %</th></tr></thead>
  <tbody>{appid_html or '<tr><td colspan="4" style="text-align:center;color:#94a3b8">Không có dữ liệu</td></tr>'}</tbody>
</table>

<h2>4. Flow Survey → Ticket (top 60 cặp)</h2>
<div class="flow-wrap">
  <div style="display:grid;grid-template-columns:1fr 24px 1fr 80px;gap:8px;padding:0 0 6px;font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase">
    <div>Survey Issue (B4)</div><div></div><div>Ticket Issue (Freshdesk)</div><div>Kết quả</div>
  </div>
  {flow_html or '<div style="color:#94a3b8;text-align:center;padding:20px">Không có cặp matched nào</div>'}
</div>

<h2>5. Detail Table</h2>
<div style="margin-bottom:10px">
  <select id="filter-mr" onchange="filterTable()">
    <option value="">Tất cả match_result</option>
    <option value="exact">Exact</option><option value="group_match">Group match</option>
    <option value="mismatch">Mismatch</option><option value="unknown">Unknown</option>
  </select>
  <select id="filter-app" onchange="filterTable()">
    <option value="">Tất cả AppID</option>{appid_filter_opts}
  </select>
  <span id="row-count" style="font-size:12px;color:#64748b"></span>
</div>
<div style="overflow-x:auto">
<table id="detail-table">
  <thead><tr><th>UID</th><th>Survey Issue</th><th>Free Comment</th><th>Ticket Issue</th><th>AppID</th><th>Đối tác</th><th>Match</th><th>Alignment</th><th style="text-align:right">Δ ngày</th></tr></thead>
  <tbody id="detail-body">{detail_html or '<tr><td colspan="9" style="text-align:center;color:#94a3b8">Không có dữ liệu</td></tr>'}</tbody>
</table>
</div>

<h2>6. Rootcause &amp; Alignment Analysis</h2>
<div class="analysis-grid">
  <div>
    <h3>Root Cause Distribution</h3>
    <table>
      <thead><tr><th>Root Cause</th><th style="text-align:right">Số lượng</th><th>Tỷ lệ</th><th style="text-align:center">Urgency TB</th></tr></thead>
      <tbody>{rc_html or '<tr><td colspan="4" style="text-align:center;color:#94a3b8">Chưa có dữ liệu LLM (không có cột Description)</td></tr>'}</tbody>
    </table>
  </div>
  <div>
    <h3>Alignment Distribution</h3>
    <table>
      <thead><tr><th>Alignment</th><th style="text-align:right">Số lượng</th><th>Tỷ lệ</th></tr></thead>
      <tbody>{al_html or '<tr><td colspan="3" style="text-align:center;color:#94a3b8">Chưa có dữ liệu LLM</td></tr>'}</tbody>
    </table>
  </div>
</div>

<h2>7. Insight Tự Động (AI)</h2>
<div class="insight-box">
  <div style="font-size:14px;font-weight:700;color:#a5b4fc;margin-bottom:12px">💡 AI Insights — Kỳ {period}</div>
  <ul>{insight_html or '<li>Không có insight</li>'}</ul>
</div>

<script>
function filterTable(){{
  const mr=document.getElementById('filter-mr').value;
  const app=document.getElementById('filter-app').value;
  const rows=document.querySelectorAll('#detail-body tr');
  let visible=0;
  rows.forEach(r=>{{
    const okMr=!mr||r.dataset.mr===mr;
    const okApp=!app||r.dataset.appid===app;
    r.style.display=(okMr&&okApp)?'':'none';
    if(okMr&&okApp)visible++;
  }});
  document.getElementById('row-count').textContent=`Đang hiển thị ${{visible}}/${{rows.length}} dòng`;
}}
filterTable();
</script>
</body>
</html>"""
