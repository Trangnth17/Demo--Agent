"""B4 — AI classify comments. Rule tier → LLM tier (GreenNode Gemma 4 31B)."""
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Callable

import httpx
import pandas as pd

API_URL = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1/chat/completions"
API_KEY = os.getenv(
    "GREENNODE_API_KEY",
    "vn-MzRcWF_ZyN550_Ui2-h2U1mWUj0a2Vc39825bdede74944bb692a02fec35fde2d1R3_6q-VtqLzUg__7mh3w_IdJSRgr",
)
MODEL = "google/gemma-4-31b-it"
CONCURRENCY = 8
CONFIDENCE_THRESHOLD = 0.7
LLM_MAX_RETRY = 2

_DATA = Path(__file__).parent.parent / "data"


def _load_json(name):
    p = _DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


KEYWORD_RULES: list[dict] = _load_json("keyword_rules.json").get("groups", [])
NONSENSE: set = set(_load_json("nonsense_list.json").get("words", []))
PROFANITY: set = set(_load_json("profanity_list.json").get("words", []))

MONEY_WORDS = {
    "tiền", "giao dịch", "thanh toán", "nạp", "rút", "hoàn",
    "chuyển khoản", "ví", "tài khoản", "số dư", "mất tiền",
    "tien", "giao dich", "thanh toan", "nap", "rut", "hoan",
    "chuyen khoan", "tai khoan", "so du", "mat tien",
}

TAXONOMY = """
NHÓM GD & TIỀN (ưu tiên cao nhất):
  1. Hoàn tiền
  2. Tự động trừ tiền
  3. Nạp tiền / Gói data
  4. Chưa nhận dịch vụ
  5. Chuyển khoản lỗi   ← KHÔNG dùng nếu comment có từ "hoàn tiền"

NHÓM CSKH:
  6. Khó kết nối nhân viên
  7. Phản hồi chậm / Chưa xử lý

NHÓM CHATBOT:
  8. Bot không giải quyết

NHÓM TÍNH NĂNG:
  9.  Xác thực / eKYC
  10. Vay tiền / Ví trả sau
  11. Bảo mật / Tài khoản
  12. Hủy dịch vụ
  13. Thay đổi thông tin
  14. Tiết kiệm / Sinh lời
  15. Ưu đãi / Voucher
  16. Tính năng app lỗi

NHÓM FEEDBACK:
  17. Feedback tiêu cực
  18. Khác / Vô nghĩa
"""

SYSTEM_PROMPT = f"""Bạn là chuyên gia phân tích phản hồi khách hàng ZaloPay.
Phân loại comment sau khi đánh giá chatbot 1 hoặc 2 sao.

TAXONOMY:{TAXONOMY}

QUY TẮC:
- Comment rỗng / <= 2 ký tự / không có nghĩa -> "Khác / Vô nghĩa", confidence = 1.0
- Telex / không dấu: đọc hiểu bình thường
- Có chửi bới + có từ tiền -> phân loại theo nhóm tài chính, sentiment_score = 5
- Có chửi bới + không có từ tiền -> "Feedback tiêu cực", sentiment_score = 5
- Ambiguous (khớp 2 nhóm rõ ràng) -> điền secondary_label
- Ưu tiên GD & Tiền hơn CSKH khi cả hai xuất hiện
- KHÔNG dùng "Chuyển khoản lỗi" nếu comment có từ "hoàn tiền"

SENTIMENT: 1=Trung lập 2=Hơi không hài lòng 3=Bức xúc 4=Rất bức xúc 5=Cực kỳ bức xúc

OUTPUT: JSON duy nhất, không có text khác:
{{
  "primary_label": "<tên nhóm>",
  "primary_confidence": <0.0-1.0>,
  "secondary_label": <"<tên nhóm>" hoặc null>,
  "secondary_confidence": <0.0-1.0 hoặc null>,
  "sentiment_score": <1-5>,
  "sentiment_label": "<Trung lập|Hơi không hài lòng|Bức xúc|Rất bức xúc|Cực kỳ bức xúc>",
  "reasoning": "<1 câu giải thích>"
}}"""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).lower().strip()) if isinstance(text, str) else ""


def _is_nonsense(text: str) -> bool:
    t = _normalize(text)
    return not t or len(t) <= 2 or t in NONSENSE or bool(re.match(r"^[\W\d\s]+$", t))


def _has_profanity(text: str) -> bool:
    t = _normalize(text)
    return any(w in t for w in PROFANITY)


def _has_money(text: str) -> bool:
    t = _normalize(text)
    return any(w in t for w in MONEY_WORDS)


def _rule_classify(text: str) -> dict | None:
    if _is_nonsense(text):
        return {"primary_label": "Khác / Vô nghĩa", "primary_confidence": 1.0,
                "secondary_label": None, "secondary_confidence": None,
                "sentiment_score": 1, "sentiment_label": "Trung lập", "reasoning": "nonsense"}

    if _has_profanity(text) and not _has_money(text):
        return {"primary_label": "Feedback tiêu cực", "primary_confidence": 0.95,
                "secondary_label": "Chửi bới", "secondary_confidence": 0.95,
                "sentiment_score": 5, "sentiment_label": "Cực kỳ bức xúc", "reasoning": "profanity"}

    t = _normalize(text)
    matches, seen = [], set()
    for rule in sorted(KEYWORD_RULES, key=lambda r: r["priority"]):
        if rule["label"] in seen:
            continue
        if any(kw.lower() in t for kw in rule.get("keywords", [])):
            matches.append(rule)
            seen.add(rule["label"])

    if len(matches) == 1:
        m = matches[0]
        return {"primary_label": m["label"], "primary_confidence": 0.9,
                "secondary_label": None, "secondary_confidence": None,
                "sentiment_score": 2, "sentiment_label": "Hơi không hài lòng", "reasoning": "rule"}

    return None


async def _call_llm(text: str, few_shots: list[dict]) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex in few_shots[-6:]:
        messages.append({"role": "user", "content": f"Phân loại: {ex['text']}"})
        messages.append({"role": "assistant", "content": json.dumps(
            {"primary_label": ex["label"], "primary_confidence": 0.95,
             "secondary_label": None, "secondary_confidence": None,
             "sentiment_score": 2, "sentiment_label": "Bức xúc", "reasoning": "few-shot"},
            ensure_ascii=False)})
    messages.append({"role": "user", "content": f"Phân loại: {text}"})

    for attempt in range(LLM_MAX_RETRY + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    API_URL,
                    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                    json={"model": MODEL, "messages": messages, "max_tokens": 300,
                          "temperature": 0.1, "top_p": 0.7},
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                m = re.search(r"\{.*\}", content, re.DOTALL)
                if m:
                    return json.loads(m.group())
        except Exception:
            if attempt == LLM_MAX_RETRY:
                break

    return {"primary_label": "Khác / Vô nghĩa", "primary_confidence": 0.0,
            "secondary_label": None, "secondary_confidence": None,
            "sentiment_score": 1, "sentiment_label": "Trung lập", "reasoning": "LLM error"}


async def classify_all(
    df: pd.DataFrame,
    job_id: str,
    log: Callable,
) -> tuple[pd.DataFrame, list[dict]]:
    texts = df["Free_Comment"].fillna("").astype(str).tolist() if "Free_Comment" in df.columns else [""] * len(df)

    few_shots_path = _DATA / "few_shot_examples.json"
    few_shots = json.loads(few_shots_path.read_text(encoding="utf-8")) if few_shots_path.exists() else []

    results: list[dict | None] = [None] * len(texts)
    llm_indices = []

    for i, t in enumerate(texts):
        r = _rule_classify(t)
        if r:
            results[i] = r
        else:
            llm_indices.append(i)

    log(f"B4: Rule: {len(texts) - len(llm_indices):,} | LLM: {len(llm_indices):,}", "B4")

    if llm_indices:
        sem = asyncio.Semaphore(CONCURRENCY)
        async def _one(i: int):
            async with sem:
                results[i] = await _call_llm(texts[i], few_shots)
        await asyncio.gather(*[_one(i) for i in llm_indices])

    df = df.copy()
    df["primary_label"]        = [r["primary_label"] for r in results]
    df["primary_confidence"]   = [float(r.get("primary_confidence", 0.0)) for r in results]
    df["secondary_label"]      = [r.get("secondary_label") for r in results]
    df["secondary_confidence"] = [r.get("secondary_confidence") for r in results]
    df["sentiment_score"]      = [r.get("sentiment_score", 1) for r in results]
    df["sentiment_label"]      = [r.get("sentiment_label", "") for r in results]
    df["reasoning"]            = [r.get("reasoning", "") for r in results]
    df["source"]               = ["rule" if i not in set(llm_indices) else "llm" for i in range(len(texts))]
    df["needs_review"]         = df["primary_confidence"] < CONFIDENCE_THRESHOLD

    review_queue = [
        {"index": int(i), "text": texts[i],
         "predicted_label": df.at[i, "primary_label"],
         "confidence": round(float(df.at[i, "primary_confidence"]), 3)}
        for i in df.index[df["needs_review"]]
    ]

    return df, review_queue
