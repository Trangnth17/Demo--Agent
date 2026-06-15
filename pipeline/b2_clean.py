"""B2 — Clean and normalize CSAT data per spec."""
import pandas as pd


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip()

    # 2a — Coalesce Tính năng from hai_long + chua_hai_long
    col_a = df.get("hai_long", pd.Series([""] * len(df))).fillna("").astype(str).str.strip()
    col_b = df.get("chua_hai_long", pd.Series([""] * len(df))).fillna("").astype(str).str.strip()
    df["Tính năng"] = [_coalesce(a, b) for a, b in zip(col_a, col_b)]

    # 2b — Rename columns
    df = df.rename(columns={
        "mo_ta_them_kho_khan_cua_ban_nha":                           "Free_Comment",
        "minh_co_giup_ban_giai_quyet_duoc_van_de_khong_nhi":         "Giải quyết vấn đề",
        "dieu_gi_khien_van_de_cua_ban_chua_duoc_giai_quyet_tron_ven": "Vấn đề chưa giải quyết",
    })

    # 2c — Fix data types
    if "User ID (zalopayid)" in df.columns:
        df["User ID (zalopayid)"] = df["User ID (zalopayid)"].apply(_fix_uid)

    if "Đánh giá (sao)" in df.columns:
        df["Đánh giá (sao)"] = pd.to_numeric(df["Đánh giá (sao)"], errors="coerce")

    if "Thời gian" in df.columns:
        df["Thời gian"] = pd.to_datetime(df["Thời gian"], errors="coerce", dayfirst=True)

    # 2d — Add time columns (Tuần = ISO week − 1 per spec)
    if "Thời gian" in df.columns:
        dt = df["Thời gian"]
        df["date"] = dt.dt.strftime("%Y-%m-%d").where(dt.notna(), None)
        df["Tuần"] = (dt.dt.isocalendar().week.astype("Int64") - 1).where(dt.notna(), pd.NA)
        df["Month"] = dt.dt.month.astype("Int64").where(dt.notna(), pd.NA)
        df["Năm"] = dt.dt.year.astype("Int64").where(dt.notna(), pd.NA)

    # 2e — Select 11 columns in spec order
    ordered = [
        "User ID (zalopayid)", "Đánh giá (sao)", "Free_Comment", "Tính năng",
        "Giải quyết vấn đề", "Vấn đề chưa giải quyết",
        "Thời gian", "date", "Tuần", "Month", "Năm",
    ]
    df = df[[c for c in ordered if c in df.columns]].copy()

    # 2f — Drop rows missing User ID or rating
    if "User ID (zalopayid)" in df.columns:
        df = df[df["User ID (zalopayid)"].notna() & (df["User ID (zalopayid)"] != "")]
    if "Đánh giá (sao)" in df.columns:
        df = df[df["Đánh giá (sao)"].notna()]

    return df.reset_index(drop=True)


def _coalesce(a: str, b: str) -> str:
    src = a if a and a != "nan" else b
    if not src or src == "nan":
        return ""
    return "; ".join(t.strip() for t in src.split(";") if t.strip())


def _fix_uid(val) -> str:
    if pd.isna(val):
        return ""
    s = str(val).strip()
    return s[:-2] if s.endswith(".0") else s
