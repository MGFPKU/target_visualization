import os, io
import requests
import polars as pl
import json

# Dataset info ----
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = "MGFPKU/target_dataset"
LOCAL_DATA: bool = os.getenv("LOCAL_DATA", "FALSE").upper() == "TRUE"

# GitHub release asset name per language
_ASSET_NAME = {"CN": "Chinese.xlsx", "EN": "English.xlsx"}

WANTED_COLS = ["Announcement_Year", "Target_Category"]

# Chinese local file support ------------------------------------------------
CN_LOCAL_FILE = "../中国国家气候目标数据库.xlsx"

# Chinese source column name → internal English name
CN_COLUMN_MAP: dict[str, str] = {
    "公布年份": "Announcement_Year",
    "目标类别": "Target_Category",
    "计数": "Count",
}

# Per-language data cache — loaded once on first request per language
_data_cache: dict[str, pl.DataFrame] = {}


def _resolve_lang(lang: str | None) -> str:
    """Normalise a language string to CN or EN, falling back to env var."""
    if lang is None:
        lang = os.getenv("LANGUAGE", "CN")
    lang = lang.upper()
    if lang not in ("CN", "EN"):
        lang = "CN"
    return lang


def promote_header_row(df: pl.DataFrame) -> pl.DataFrame:
    """Find the real header row and promote it to column names, dropping
    everything above it.

    Some Excel sheets have metadata/description rows before the actual column
    headers.  This function scans for the first row that has values in more
    than one column (metadata rows typically only use the first column) and
    promotes it to be the DataFrame columns.  All rows above and including the
    header row are removed.
    """
    if df.height == 0:
        return df

    # Locate the header: first row with non-null values in more than one column
    header_idx: int | None = None
    for i in range(df.height):
        non_null = sum(1 for v in df.row(i) if v is not None)
        if non_null > 1:
            header_idx = i
            break

    if header_idx is None:
        return df

    header_vals = [str(v) if v is not None else "" for v in df.row(header_idx)]
    # Deduplicate: Polars requires unique column names
    seen: dict[str, int] = {}
    unique_headers: list[str] = []
    for v in header_vals:
        if v in seen:
            seen[v] += 1
            unique_headers.append(f"{v}_{seen[v]}")
        else:
            seen[v] = 0
            unique_headers.append(v)

    df = df.slice(header_idx + 1)
    df.columns = unique_headers
    return df


def fetch_raw_data(lang: str | None = None) -> io.BytesIO:
    lang = _resolve_lang(lang)
    if LOCAL_DATA:
        if lang == "CN":
            file_path = CN_LOCAL_FILE
        else:
            file_path = "../CHINA'S NATIONAL CLIMATE TARGETS DATABASE.xlsx"
        with open(file_path, "rb") as f:
            print(f"Using local data ({file_path})...")
            return io.BytesIO(f.read())
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    # 1️⃣ Get latest release metadata
    latest_url = f"https://api.github.com/repos/{REPO}/releases/latest"
    res = requests.get(latest_url, headers=headers)

    if res.status_code != 200:
        raise RuntimeError(f"Failed to fetch file: {res.status_code}\n{res.text}")

    release = res.json()

    # 2️⃣ Find the language-appropriate asset
    asset_name = _ASSET_NAME.get(lang, _ASSET_NAME["CN"])
    asset = next((a for a in release["assets"] if a["name"] == asset_name), None)

    if asset is None:
        raise RuntimeError(f"{asset_name} not found in latest release.")

    asset_id = asset["id"]

    # 3️⃣ Download asset binary
    download_headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/octet-stream",
    }

    download_url = f"https://api.github.com/repos/{REPO}/releases/assets/{asset_id}"
    file_res = requests.get(download_url, headers=download_headers)

    if file_res.status_code != 200:
        raise RuntimeError(f"Failed to download file:\n{file_res.text}")

    # 4️⃣ Load Excel into Polars
    return io.BytesIO(file_res.content)


def get_sheet_names(lang: str | None = None) -> list[str]:
    lang = _resolve_lang(lang)
    with open("sheets.json", "r", encoding="utf-8") as f:
        data: dict = json.load(f)
    sheets = data.get("sheets", {})
    # Support both nested {CN: [...], EN: [...]} and legacy [[...]] formats
    if isinstance(sheets, dict):
        sheet_names: list[str] = sheets.get(lang, sheets.get("CN", []))
    else:
        # Legacy format: sheets is a list of lists
        sheet_names: list[str] = sheets[0] if sheets else []
    if not sheet_names:
        raise RuntimeError("No sheet names found in sheets.json")
    return sheet_names


def _rename_cn_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Rename Chinese source column names to internal English names."""
    rename_map = {cn: en for cn, en in CN_COLUMN_MAP.items() if cn in df.columns}
    return df.rename(rename_map)


def _load_cn_data(raw_xlsx: io.BytesIO, lang: str) -> pl.DataFrame:
    """Load and process data from the Chinese Excel file.

    Differences from _load_en_data():
      - Chinese source column names are renamed to internal English names
      - No Count != "r" filter (Chinese data has no reference rows)
      - Uses fill_null("无") instead of fill_null("N/A")
    """
    sheet_names = get_sheet_names(lang)
    combined_sheet: pl.DataFrame | None = None

    for sheet_name in sheet_names:
        raw_xlsx.seek(0)
        sheet = (
            pl.read_excel(raw_xlsx, sheet_name=sheet_name)
            .with_columns(pl.all().cast(pl.Utf8))
        )
        # Rename Chinese columns → internal English names
        sheet = _rename_cn_columns(sheet)

        sheet = sheet.with_columns(
            pl.col("Target_Category").str.replace(r"\s*target$", "", literal=False)
        )
        sheet = sheet.select(WANTED_COLS)
        combined_sheet = (
            sheet if combined_sheet is None else pl.concat([combined_sheet, sheet])
        )

    if combined_sheet is None:
        raise RuntimeError(
            "No sheets were processed. Check the Chinese Excel file."
        )

    return combined_sheet.fill_null("无")


def _load_en_data(raw_xlsx: io.BytesIO, lang: str) -> pl.DataFrame:
    """Load and process data from the English Excel file."""
    sheet_names = get_sheet_names(lang)
    combined_sheet: pl.DataFrame | None = None

    for sheet_name in sheet_names:
        raw_xlsx.seek(0)
        sheet = (
            pl.read_excel(raw_xlsx, sheet_name=sheet_name)
            .with_columns(pl.all().cast(pl.Utf8))
            .filter(pl.col("Count") != "r")
        )
        sheet = sheet.with_columns(
            pl.col("Target_Category").str.replace(r"\s*target$", "", literal=False)
        )
        sheet = sheet.select(WANTED_COLS)
        combined_sheet = (
            sheet if combined_sheet is None else pl.concat([combined_sheet, sheet])
        )

    if combined_sheet is None:
        raise RuntimeError(
            "No sheets were processed. Check sheets.json and dataset.xlsx"
        )

    return combined_sheet.fill_null("N/A")


def get_data(lang: str | None = None) -> pl.DataFrame:
    """Return the full dataset for *lang*, caching it in memory.

    Call this from inside a Shiny session so ``lang`` can be driven by a
    query parameter (``?lang=cn`` / ``?lang=en``).  The first call per
    language fetches and processes the Excel file; subsequent calls hit an
    in-memory cache.
    """
    lang = _resolve_lang(lang)

    if lang in _data_cache:
        return _data_cache[lang]

    raw_xlsx = fetch_raw_data(lang)
    if lang == "CN":
        df = _load_cn_data(raw_xlsx, lang)
    else:
        df = _load_en_data(raw_xlsx, lang)

    _data_cache[lang] = df
    return df
