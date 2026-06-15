"""B1 — Validate CSAT file: read sheet ce_chat_bot, check required columns."""
import pandas as pd
from pathlib import Path

SHEET_NAME = "ce_chat_bot"

REQUIRED_COLS = [
    "User ID (zalopayid)",
    "Đánh giá (sao)",
    "Thời gian",
    "mo_ta_them_kho_khan_cua_ban_nha",
    "minh_co_giup_ban_giai_quyet_duoc_van_de_khong_nhi",
    "dieu_gi_khien_van_de_cua_ban_chua_duoc_giai_quyet_tron_ven",
    "hai_long",
    "chua_hai_long",
]


def validate_and_read(file_path: Path) -> pd.DataFrame:
    """
    Read CSAT Excel from sheet 'ce_chat_bot'.
    Falls back to first sheet if sheet not found.
    Raises ValueError listing any missing required columns.
    """
    try:
        df = pd.read_excel(file_path, sheet_name=SHEET_NAME, engine="openpyxl")
    except Exception:
        try:
            df = pd.read_excel(file_path, engine="openpyxl")
        except Exception as exc:
            raise ValueError(f"Không đọc được file Excel: {exc}")

    df.columns = df.columns.str.strip()

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Thiếu {len(missing)} cột bắt buộc: {', '.join(missing)}")

    return df


def extract_period(filename: str) -> str:
    """'CSAT W21-22.xlsx' → 'W21-22'. Fallback: full stem."""
    stem = Path(filename).stem  # 'CSAT W21-22'
    upper = stem.strip()
    if upper.upper().startswith("CSAT "):
        return upper[5:].strip()
    return upper
