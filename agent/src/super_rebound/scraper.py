"""Scrape target webpage for 两融维持担保比例 + 国家队 ETF 买入监测 data.

Target URL (requires sharecode):
    https://astock-monitor-04758.app.workbuddy.host/?sharecode=N2WCQXUGR7

The page structure has two sections:
    1. Margin ratio stats (key-value cards at the top)
    2. ETF monitor HTML table (multiple header rows, many columns, final "累计" row)

If scraping fails (network / structure change), the scraper returns None and the
service layer will fall back to whatever is already in the DB.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TARGET_URL = "https://astock-monitor-04758.app.workbuddy.host/?sharecode=N2WCQXUGR7"

# Map the ETF names from the webpage to our normalised codes.
# Keys match the exact text in the table header cells (colspan=1 or subtotal col).
ETF_CODE_ALIASES: dict[str, str] = {
    # Subtotal labels (index groups) are also valid as column headers
    "中证A500ETF国泰": "中证A500ETF国泰",
    "A500ETF华泰柏瑞":  "A500ETF华泰柏瑞",
    "A500ETF南方":      "A500ETF南方",
    "A500ETF易方达":    "A500ETF易方达",
    "上证50ETF华夏":    "上证50ETF华夏",
    "上证50ETF易方达":  "上证50ETF易方达",
    "沪深300ETF华泰柏瑞": "沪深300ETF华泰柏瑞",
    "沪深300ETF易方达":  "沪深300ETF易方达",
    "沪深300ETF嘉实":    "沪深300ETF嘉实",
    "沪深300ETF华夏":    "沪深300ETF华夏",
    "中证500ETF南方":    "中证500ETF南方",
    "中证500ETF华夏":    "中证500ETF华夏",
    "中证1000ETF南方":   "中证1000ETF南方",
    "中证1000ETF华夏":   "中证1000ETF华夏",
    "中证1000ETF广发":   "中证1000ETF广发",
    "创业板ETF易方达":   "创业板ETF易方达",
    "科创50ETF华夏":     "科创50ETF华夏",
}

# Baseline period (from webpage). Used as per-column baseline when we can't scrape
# individual ETF baselines.  All ETFs share the same baseline range.
BASELINE_START = date(2026, 9, 1)
BASELINE_END = date(2026, 9, 24)


def _fetch_html(url: str = TARGET_URL, timeout: int = 30) -> str | None:
    """Download page HTML with a realistic UA."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("scraper: HTTP %d for %s", resp.status_code, url)
            return None
        return resp.text
    except requests.RequestException as exc:
        logger.warning("scraper: request failed: %s", exc)
        return None


def _to_float(text: str | None) -> float | None:
    """Extract a float from strings like '259.34%', '-14.55%', '7,696亿', '2,309.13'."""
    if not text:
        return None
    cleaned = text.strip().replace("%", "").replace("亿", "").replace(",", "").replace(" ", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_int(text: str | None) -> int | None:
    f = _to_float(text)
    return int(f) if f is not None else None


# ---------------------------------------------------------------------------
# Margin ratio parsing
# ---------------------------------------------------------------------------

_MARGIN_KEYWORDS = {
    "latest": ["最新"],
    "six_year": ["近6年分位", "近6年"],
    "ten_year": ["近十年分位", "近十年"],
    "vs_high": ["较区间高点"],
    "range_high": ["区间高", "区间最高"],
    "range_low": ["区间低", "区间最低"],
    "sample": ["样本"],
}


def _extract_margin_ratio(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Parse the margin-ratio section from the page.

    The page renders metric cards. We locate them by looking for the Chinese keywords
    within the visible text, then pull the numbers that follow.
    """
    text = soup.get_text("\n")

    def find_value(keyword_list: list[str]) -> str | None:
        for kw in keyword_list:
            # Look for 'keyword' followed by a number/percentage in next 100 chars
            pattern = rf"{kw}[^\d\-\n]*([\-\d.,%亿 ]+)"
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return None

    latest_val = _to_float(find_value(_MARGIN_KEYWORDS["latest"]))
    if latest_val is None:
        logger.warning("scraper: could not find margin ratio latest value")
        return None

    range_high = _to_float(find_value(_MARGIN_KEYWORDS["range_high"]))
    range_low = _to_float(find_value(_MARGIN_KEYWORDS["range_low"]))

    # Detect the date range displayed (e.g. "2020-11-05 ~ 2026-11-04")
    date_range_match = re.search(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", text)
    sample_text = find_value(_MARGIN_KEYWORDS["sample"])
    sample_count = _to_int(sample_text)

    # Use the END of the range as the trade date (the ratio is "as of" that day)
    trade_date = None
    if date_range_match:
        try:
            trade_date = datetime.strptime(date_range_match.group(2), "%Y-%m-%d").date()
        except ValueError:
            trade_date = date.today() - timedelta(days=1)

    if trade_date is None:
        trade_date = date.today() - timedelta(days=1)

    return {
        "trade_date": trade_date,
        "margin_ratio": latest_val,
        "range_high": range_high,
        "range_low": range_low,
        "sample_count": sample_count,
    }


# ---------------------------------------------------------------------------
# ETF monitor table parsing
# ---------------------------------------------------------------------------

def _extract_etf_table(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Parse the ETF monitoring table from the page.

    Returns:
        {
            "etf_codes": [...],           # column ETF names (excluding 小计/总买入)
            "daily_rows": [
                {"trade_date": date, "values": {etf_code: turnover_bn, ...}}
            ],
            "index_group_subtotals": [...]  # computed subtotal per group per day
        }
    """
    tables = soup.find_all("table")
    target_table = None
    for tbl in tables:
        tbl_text = tbl.get_text(" ")
        if "中证A500" in tbl_text and "沪深300" in tbl_text and "科创50" in tbl_text:
            target_table = tbl
            break

    if target_table is None:
        logger.warning("scraper: ETF table not found on page")
        return None

    rows = target_table.find_all("tr")
    if len(rows) < 3:
        logger.warning("scraper: ETF table too short (%d rows)", len(rows))
        return None

    # --- Parse header rows to build column map ---
    # The table has 2 header rows (colspan structure) and a body.
    # Strategy: collect ALL <td>/<th> texts from the first 2 non-body rows,
    # treat the first non-date cell as an ETF code candidate.
    header_rows: list[list[str]] = []
    body_start_idx = 0
    for idx, row in enumerate(rows):
        cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        if not cells:
            continue
        if any("中证" in c or "上证50" in c or "沪深300" in c for c in cells):
            header_rows.append(cells)
        elif header_rows and idx > 1:
            # First body row detected (has a date in col 0)
            body_start_idx = idx
            break
        if len(header_rows) >= 2:
            body_start_idx = idx + 1
            break

    if not header_rows:
        # Fallback: treat every row as potential data if first cell looks like a date
        body_start_idx = 0

    # Build ETF column names from header
    # Heuristic: walk header cells left-to-right, skipping "日期" and group/subtotal labels
    etf_columns: list[str] = []
    if len(header_rows) >= 1:
        # Use last header row (most specific column names)
        candidates = header_rows[-1]
        seen_total = False
        for cell in candidates:
            # Skip date column
            if "日期" in cell:
                continue
            # Skip subtotal / group labels like "小计"
            if "小计" in cell:
                continue
            # Skip final "总买入" column
            if "总买入" in cell:
                seen_total = True
                break
            # Skip pure group labels (no ETF-specific text)
            if cell and not cell.isspace():
                etf_columns.append(cell)

    if not etf_columns:
        logger.warning("scraper: failed to identify ETF columns from headers")
        return None

    logger.info("scraper: identified %d ETF columns: %s", len(etf_columns), etf_columns[:4])

    # --- Parse body rows ---
    daily_rows: list[dict[str, Any]] = []
    for row in rows[body_start_idx:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        if len(cells) < 2:
            continue

        date_str = cells[0]
        values = cells[1:]

        # Detect cumulative row (last row in table)
        is_cumulative = "累计" in date_str
        if is_cumulative:
            # Skip cumulative — we compute from daily rows
            continue

        # Detect non-date / non-data rows
        # Valid date patterns: YYYY-MM-DD, MM-DD, or numeric-only short form
        if not re.match(r"^\d{4}-\d{2}-\d{2}$|^\d{2}-\d{2}$", date_str):
            continue

        # Normalise date
        trade_date: date
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            trade_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            # MM-DD → guess year from context (use current year)
            now_year = date.today().year
            trade_date = datetime.strptime(f"{now_year}-{date_str}", "%Y-%m-%d").date()
            # If this date is in the future, roll back a year
            if trade_date > date.today():
                trade_date = trade_date.replace(year=now_year - 1)

        row_values: dict[str, float] = {}
        for i, col_name in enumerate(etf_columns):
            if i >= len(values):
                break
            row_values[col_name] = _to_float(values[i]) or 0.0

        if any(v > 0 for v in row_values.values()):
            daily_rows.append({
                "trade_date": trade_date,
                "values": row_values,
            })

    if not daily_rows:
        logger.warning("scraper: no daily rows parsed from ETF table")
        return None

    return {
        "etf_columns": etf_columns,
        "daily_rows": daily_rows,
        "source": TARGET_URL,
        "fetched_at": datetime.now(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_target_page() -> dict[str, Any] | None:
    """Top-level scraper entry. Returns combined margin + ETF data or None."""
    html = _fetch_html()
    if html is None:
        return None

    soup = BeautifulSoup(html, "html.parser")

    margin = _extract_margin_ratio(soup)
    etf = _extract_etf_table(soup)

    if margin is None and etf is None:
        logger.warning("scraper: both margin ratio and ETF table failed to parse")
        return None

    return {
        "margin_ratio": margin,
        "etf_monitor": etf,
    }
