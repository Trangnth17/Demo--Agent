"""B3 — Filter rows with Đánh giá (sao) <= 2."""
import pandas as pd


def filter_negative(df: pd.DataFrame) -> pd.DataFrame:
    if "Đánh giá (sao)" not in df.columns:
        return df.copy()
    return df[df["Đánh giá (sao)"] <= 2].reset_index(drop=True).copy()
