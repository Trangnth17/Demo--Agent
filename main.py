import asyncio
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

_API_URL = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1/chat/completions"
_API_KEY = os.getenv(
    "GREENNODE_API_KEY",
    "vn-MzRcWF_ZyN550_Ui2-h2U1mWUj0a2Vc39825bdede74944bb692a02fec35fde2d1R3_6q-VtqLzUg__7mh3w_IdJSRgr",
)
_MODEL = "google/gemma-4-31b-it"

load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()

import sys
sys.path.insert(0, str(BASE_DIR))

from pipeline.b1_validate import validate_and_read, extract_period
from pipeline.b2_clean import clean_data
from pipeline.b3_filter import filter_negative
from pipeline.b4_classify import classify_all
from pipeline.b5_report import generate_csat_report
from pipeline.b6_ticket import enrich_tickets

UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR   = BASE_DIR / "data"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

FRESHDESK_DEFAULT_PATH = DATA_DIR / "freshdesk_default.xlsx"

jobs: dict[str, dict] = {}

app = FastAPI(title="CSAT Chatbot Analysis Agent", version="2.0.0")
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=(BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8"))


@app.post("/api/run-local")
async def run_pipeline_local(background_tasks: BackgroundTasks, data: dict):
    """Run pipeline using files already present in BASE_DIR (no upload needed)."""
    csat_name   = data.get("csat_file", "")
    ticket_name = data.get("ticket_file", "")

    if not csat_name:
        raise HTTPException(400, "csat_file required")

    # Resolve paths — only allow files inside BASE_DIR for safety
    csat_src = BASE_DIR / csat_name
    if not csat_src.exists():
        raise HTTPException(404, f"File not found: {csat_name}")

    job_id = str(uuid.uuid4())[:8].upper()
    period = extract_period(csat_name)

    csat_path = UPLOAD_DIR / f"{job_id}_csat{csat_src.suffix}"
    shutil.copy2(csat_src, csat_path)

    ticket_path = None
    freshdesk_source = None
    if ticket_name:
        ticket_src = BASE_DIR / ticket_name
        if not ticket_src.exists():
            raise HTTPException(404, f"File not found: {ticket_name}")
        ticket_path = UPLOAD_DIR / f"{job_id}_ticket{ticket_src.suffix}"
        shutil.copy2(ticket_src, ticket_path)
        freshdesk_source = "local"
    elif FRESHDESK_DEFAULT_PATH.exists():
        ticket_path = FRESHDESK_DEFAULT_PATH
        freshdesk_source = "default"

    jobs[job_id] = {
        "status": "running",
        "period": period,
        "steps": {
            "B1": "pending", "B2": "pending", "B3": "pending",
            "B4": "pending", "B5": "pending",
            "B6": "pending" if ticket_path else "skipped",
        },
        "outputs": [],
        "errors": [],
        "progress": [],
        "review_queue": [],
        "stats": {},
    }

    background_tasks.add_task(_run_pipeline, job_id, csat_path, ticket_path, period, freshdesk_source)
    return {"job_id": job_id, "period": period, "csat_file": csat_name}


@app.get("/api/local-files")
async def list_local_files():
    """Return XLSX/XLS/CSV files available in BASE_DIR for run-local."""
    exts = {".xlsx", ".xls", ".csv"}
    files = [
        f.name for f in BASE_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in exts
    ]
    return {"files": sorted(files)}


@app.post("/api/run")
async def run_pipeline(
    background_tasks: BackgroundTasks,
    csat_file: UploadFile = File(...),
    ticket_file: UploadFile = File(None),
):
    job_id = str(uuid.uuid4())[:8].upper()
    period = extract_period(csat_file.filename)

    csat_path = UPLOAD_DIR / f"{job_id}_csat{Path(csat_file.filename).suffix}"
    with open(csat_path, "wb") as f:
        shutil.copyfileobj(csat_file.file, f)

    ticket_path = None
    freshdesk_source = None
    if ticket_file and ticket_file.filename:
        ticket_path = UPLOAD_DIR / f"{job_id}_ticket{Path(ticket_file.filename).suffix}"
        with open(ticket_path, "wb") as f:
            shutil.copyfileobj(ticket_file.file, f)
        freshdesk_source = "upload"
    elif FRESHDESK_DEFAULT_PATH.exists():
        ticket_path = FRESHDESK_DEFAULT_PATH
        freshdesk_source = "default"

    jobs[job_id] = {
        "status": "running",
        "period": period,
        "steps": {
            "B1": "pending", "B2": "pending", "B3": "pending",
            "B4": "pending", "B5": "pending",
            "B6": "pending" if ticket_path else "skipped",
        },
        "outputs": [],
        "errors": [],
        "progress": [],
        "review_queue": [],
        "stats": {},
    }

    background_tasks.add_task(_run_pipeline, job_id, csat_path, ticket_path, period, freshdesk_source)
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.get("/api/download/{filename:path}")
async def download_file(filename: str):
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(str(path), filename=path.name)


@app.post("/api/review/submit")
async def submit_review(data: dict):
    examples_path = BASE_DIR / "data" / "few_shot_examples.json"
    examples = json.loads(examples_path.read_text(encoding="utf-8")) if examples_path.exists() else []
    for c in data.get("corrections", []):
        examples.append({"text": c["text"], "label": c["label"],
                         "source": "human_review", "date": datetime.now().isoformat()})
    examples_path.write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": len(data.get("corrections", []))}


@app.get("/api/freshdesk-status")
async def freshdesk_status():
    if FRESHDESK_DEFAULT_PATH.exists():
        stat = FRESHDESK_DEFAULT_PATH.stat()
        return {
            "exists": True,
            "filename": FRESHDESK_DEFAULT_PATH.name,
            "size_kb": round(stat.st_size / 1024, 1),
            "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
        }
    return {"exists": False}


@app.post("/api/update-freshdesk")
async def update_freshdesk(freshdesk_file: UploadFile = File(...)):
    suffix = Path(freshdesk_file.filename).suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        raise HTTPException(400, "Chỉ chấp nhận .xlsx hoặc .xls")
    dest = DATA_DIR / f"freshdesk_default{suffix}"
    # Remove old file(s) regardless of extension
    for old in DATA_DIR.glob("freshdesk_default.*"):
        old.unlink(missing_ok=True)
    with open(dest, "wb") as f:
        shutil.copyfileobj(freshdesk_file.file, f)
    global FRESHDESK_DEFAULT_PATH
    FRESHDESK_DEFAULT_PATH = dest
    stat = dest.stat()
    return {
        "ok": True,
        "filename": freshdesk_file.filename,
        "size_kb": round(stat.st_size / 1024, 1),
        "saved_as": dest.name,
    }


@app.get("/api/jobs")
async def list_jobs():
    return [{"job_id": jid, "status": j["status"], "period": j.get("period", ""),
             "outputs": len(j["outputs"])} for jid, j in reversed(list(jobs.items()))]


@app.post("/api/chat")
async def chat_with_agent(data: dict):
    job_id  = data.get("job_id", "")
    message = data.get("message", "").strip()
    history = data.get("history", [])

    if not message:
        raise HTTPException(400, "message required")

    job   = jobs.get(job_id) or {}
    stats = job.get("stats", {})
    period = job.get("period", "N/A")
    outputs = [o["name"] for o in job.get("outputs", [])]

    context = "\n".join([
        f"Kỳ báo cáo: {period}",
        f"Tổng dòng đầu vào: {stats.get('input_rows', 'N/A')}",
        f"Dòng sau làm sạch: {stats.get('clean_rows', 'N/A')}",
        f"Dòng negative (1-2★): {stats.get('negative_rows', 'N/A')}",
        f"Số dòng cần human review: {stats.get('review_count', 'N/A')}",
        f"Outputs: {', '.join(outputs)}" if outputs else "Chưa có outputs",
    ])

    system_msg = (
        f"Bạn là AI assistant phân tích CSAT ZaloPay, trả lời ngắn gọn bằng tiếng Việt.\n"
        f"Thông tin báo cáo kỳ {period}:\n{context}\n"
        "Nếu câu hỏi nằm ngoài dữ liệu trên, đề nghị người dùng xem báo cáo HTML."
    )

    messages = [{"role": "system", "content": system_msg}]
    for h in history[-8:]:
        if h.get("role") in ("user", "assistant"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"},
                json={"model": _MODEL, "messages": messages, "max_tokens": 400, "temperature": 0.3},
            )
            resp.raise_for_status()
            reply = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        reply = f"Xin lỗi, không thể kết nối AI: {exc}"

    return {"reply": reply}


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def _run_pipeline(job_id: str, csat_path: Path, ticket_path: Path | None, period: str, freshdesk_source: str | None = None):
    job = jobs[job_id]

    def log(msg: str, step: str | None = None, status: str = "running"):
        ts = datetime.now().strftime("%H:%M:%S")
        job["progress"].append({"time": ts, "msg": msg})
        if step:
            job["steps"][step] = status

    try:
        # B1 — Validate
        log("B1: Đọc và validate file CSAT...", "B1")
        df_raw = await asyncio.to_thread(validate_and_read, csat_path)
        job["stats"]["input_rows"] = len(df_raw)
        log(f"B1: ✓ {len(df_raw):,} dòng, kỳ: {period}", "B1", "done")

        # B2 — Clean
        log("B2: Làm sạch và chuẩn hoá dữ liệu...", "B2")
        df_clean = await asyncio.to_thread(clean_data, df_raw)
        job["stats"]["clean_rows"] = len(df_clean)
        b2_path = OUTPUT_DIR / f"CSAT CLEAN {period}.xlsx"
        await asyncio.to_thread(lambda: df_clean.to_excel(b2_path, index=False))
        job["outputs"].append({"name": "📋 B2 — CSAT CLEAN", "file": b2_path.name, "type": "excel"})
        log(f"B2: ✓ {len(df_clean):,} dòng — {b2_path.name}", "B2", "done")

        # B3 — Filter
        log("B3: Lọc rating ≤ 2★...", "B3")
        df_neg = await asyncio.to_thread(filter_negative, df_clean)
        job["stats"]["negative_rows"] = len(df_neg)
        log(f"B3: ✓ {len(df_neg):,} dòng negative", "B3", "done")

        # B4 — Classify
        log("B4: Phân loại AI (rule + Gemma 4 31B)...", "B4")
        df_classified, review_queue = await classify_all(df_neg, job_id, log)

        b4_path = OUTPUT_DIR / f"CSAT B4 {period}.xlsx"
        summary_df = df_classified["primary_label"].value_counts().reset_index()
        summary_df.columns = ["primary_label", "count"]
        await asyncio.to_thread(_write_b4_excel, b4_path, df_classified, summary_df)

        job["outputs"].append({"name": "📊 B4 — Classification", "file": b4_path.name, "type": "excel"})
        job["review_queue"] = review_queue
        job["stats"]["review_count"] = len(review_queue)

        top3 = " | ".join(f"{r['primary_label']} ({r['count']})" for _, r in summary_df.head(3).iterrows())
        log(f"B4: ✓ Phân loại xong — {len(review_queue):,} cần review | Top: {top3}", "B4", "done")

        # B5 — HTML Report
        log("B5: Tạo báo cáo HTML...", "B5")
        b5_path = await asyncio.to_thread(generate_csat_report, df_classified, df_clean, job_id, period)
        job["outputs"].append({"name": "📈 B5 — CSAT REPORT", "file": b5_path.name, "type": "html"})
        log(f"B5: ✓ {b5_path.name}", "B5", "done")

        # B6 — Ticket enrichment (optional)
        if ticket_path:
            src_label = "file upload" if freshdesk_source == "upload" else "file mặc định đã lưu"
            log(f"B6: Đối chiếu Freshdesk ({src_label}) + rootcause analysis...", "B6")
            b6_xlsx, b6_html = await enrich_tickets(
                df_classified, ticket_path, job_id, period
            )
            job["outputs"].append({"name": "🔗 B6 — Matched Pairs", "file": b6_xlsx.name, "type": "excel"})
            job["outputs"].append({"name": "📋 B6 — Ticket Report", "file": b6_html.name, "type": "html"})
            log(f"B6: ✓ {b6_xlsx.name}", "B6", "done")

        job["status"] = "done"
        log(f"✅ Hoàn thành! Kỳ [{period}] — {len(job['outputs'])} files xuất.")

    except ValueError as exc:
        job["status"] = "error"
        job["errors"].append(str(exc))
        log(f"❌ Lỗi: {exc}")
    except Exception as exc:
        import traceback
        job["status"] = "error"
        job["errors"].append(str(exc))
        log(f"❌ Lỗi: {exc}")
        print(traceback.format_exc())


def _write_b4_excel(path: Path, df_classified, summary_df):
    import pandas as pd
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df_classified.to_excel(w, sheet_name="classified", index=False)
        summary_df.to_excel(w, sheet_name="summary", index=False)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
