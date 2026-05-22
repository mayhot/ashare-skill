import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def add_local_deps() -> None:
    cwd = Path.cwd()
    candidates = [
        cwd / ".deps",
        Path(__file__).resolve().parents[2] / ".deps",
        Path(__file__).resolve().parents[3] / ".deps",
    ]
    for path in candidates:
        if path.exists():
            sys.path.insert(0, str(path))


add_local_deps()

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit(
        "Missing dependency. Install with: python -m pip install --target .deps pandas"
    ) from exc

try:
    import baostock as bs
except ImportError:
    bs = None


def bs_code(code: str) -> str:
    code = normalize_code(code)
    return ("sh." if code.startswith(("6", "9")) else "sz.") + code


def qq_code(code: str) -> str:
    code = normalize_code(code)
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def normalize_code(code: str) -> str:
    code = str(code).strip()
    if code.isdigit():
        return code.zfill(6)
    return code


def ema(series: "pd.Series", span: int) -> "pd.Series":
    return series.ewm(span=span, adjust=False).mean()


def macd_label(df: "pd.DataFrame") -> tuple[str, dict]:
    close = df["close"]
    dif = ema(close, 12) - ema(close, 26)
    dea = ema(dif, 9)
    hist = (dif - dea) * 2
    last = len(df) - 1
    prev = last - 1

    if dif.iloc[last] > dea.iloc[last] and dif.iloc[prev] <= dea.iloc[prev]:
        label = "MACD零轴上金叉" if dif.iloc[last] > 0 else "MACD零轴下金叉"
    elif dif.iloc[last] < dea.iloc[last] and dif.iloc[prev] >= dea.iloc[prev]:
        label = "MACD死叉"
    elif dif.iloc[last] > dea.iloc[last] and hist.iloc[last] >= hist.iloc[prev]:
        label = "MACD多头延续"
    elif dif.iloc[last] > dea.iloc[last] and hist.iloc[last] < hist.iloc[prev]:
        label = "MACD多头但动能收敛"
    elif dif.iloc[last] < dea.iloc[last] and hist.iloc[last] < hist.iloc[prev]:
        label = "MACD空头/动能走弱"
    else:
        label = "MACD中性"

    return label, {
        "dif": round(float(dif.iloc[last]), 4),
        "dea": round(float(dea.iloc[last]), 4),
        "hist": round(float(hist.iloc[last]), 4),
    }


def kdj_label(df: "pd.DataFrame") -> tuple[str, dict]:
    low_n = df["low"].rolling(9, min_periods=9).min()
    high_n = df["high"].rolling(9, min_periods=9).max()
    rsv = (df["close"] - low_n) / (high_n - low_n) * 100
    rsv = rsv.fillna(50).replace([float("inf"), float("-inf")], 50)

    k = 50.0
    d = 50.0
    k_values = []
    d_values = []
    for value in rsv:
        k = k * 2 / 3 + float(value) / 3
        d = d * 2 / 3 + k / 3
        k_values.append(k)
        d_values.append(d)

    k_series = pd.Series(k_values, index=df.index)
    d_series = pd.Series(d_values, index=df.index)
    j_series = 3 * k_series - 2 * d_series
    last = len(df) - 1
    prev = last - 1

    if k_series.iloc[last] > d_series.iloc[last] and k_series.iloc[prev] <= d_series.iloc[prev]:
        label = "KDJ金叉偏热" if j_series.iloc[last] > 100 else "KDJ金叉"
    elif k_series.iloc[last] < d_series.iloc[last] and k_series.iloc[prev] >= d_series.iloc[prev]:
        label = "KDJ高位死叉" if k_series.iloc[last] > 70 else "KDJ死叉"
    elif j_series.iloc[last] > 100:
        label = "KDJ高位偏热"
    elif k_series.iloc[last] > d_series.iloc[last]:
        label = "KDJ多头"
    else:
        label = "KDJ中性"

    return label, {
        "k": round(float(k_series.iloc[last]), 2),
        "d": round(float(d_series.iloc[last]), 2),
        "j": round(float(j_series.iloc[last]), 2),
    }


def fetch_daily(code: str, start_date: str, end_date: str, adjustflag: str) -> "pd.DataFrame":
    if bs is None:
        raise RuntimeError("baostock not installed")
    rs = bs.query_history_k_data_plus(
        bs_code(code),
        "date,open,high,low,close,volume,amount,tradestatus,pctChg",
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag=adjustflag,
    )
    if rs.error_code != "0":
        raise RuntimeError(rs.error_msg)

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    df = pd.DataFrame(rows, columns=rs.fields)
    if df.empty:
        raise RuntimeError("empty data")
    df = df[df["tradestatus"] == "1"].copy()
    for col in ["open", "high", "low", "close", "volume", "amount", "pctChg"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) < 60:
        raise RuntimeError(f"not enough daily rows: {len(df)}")
    return df


def fetch_tencent_daily(code: str, start_date: str, end_date: str) -> "pd.DataFrame":
    qcode = qq_code(code)
    # Tencent returns latest N daily bars. Request enough rows, then filter by date.
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
        + urllib.parse.urlencode({"param": f"{qcode},day,,,700,qfq"})
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("msg") or "Tencent API error")
    stock = (payload.get("data") or {}).get(qcode) or {}
    rows = stock.get("qfqday") or stock.get("day") or []
    if not rows:
        raise RuntimeError("Tencent returned empty daily data")

    rows = [row[:6] for row in rows if len(row) >= 6]
    df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) < 60:
        raise RuntimeError(f"not enough Tencent daily rows: {len(df)}")
    return df


def fetch_with_source(code: str, start_date: str, end_date: str, adjustflag: str, source: str) -> tuple["pd.DataFrame", str]:
    errors = []
    if source in ("auto", "tencent"):
        try:
            return fetch_tencent_daily(code, start_date, end_date), "Tencent qfqday"
        except Exception as exc:
            errors.append(f"Tencent: {exc}")
            if source == "tencent":
                raise
    if source in ("auto", "baostock"):
        login = None
        try:
            if bs is None:
                raise RuntimeError("baostock not installed")
            login = bs.login()
            if login.error_code != "0":
                raise RuntimeError(login.error_msg)
            return fetch_daily(code, start_date, end_date, adjustflag), "BaoStock"
        except Exception as exc:
            errors.append(f"BaoStock: {exc}")
            raise RuntimeError("; ".join(errors))
        finally:
            if bs is not None and login is not None and login.error_code == "0":
                bs.logout()
    raise RuntimeError("; ".join(errors) or f"unsupported source: {source}")


def calculate(code: str, start_date: str, end_date: str, adjustflag: str, source: str) -> dict:
    code = normalize_code(code)
    df, actual_source = fetch_with_source(code, start_date, end_date, adjustflag, source)
    macd, macd_values = macd_label(df)
    kdj, kdj_values = kdj_label(df)
    last = df.iloc[-1]
    return {
        "code": code,
        "date": str(last["date"]),
        "close": round(float(last["close"]), 2),
        "macd": macd,
        "macd_values": macd_values,
        "kdj": kdj,
        "kdj_values": kdj_values,
        "rows": int(len(df)),
        "adjustflag": adjustflag,
        "source": actual_source,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calculate A-share MACD/KDJ using BaoStock daily K-lines.")
    parser.add_argument("--codes", required=True, help="Comma-separated stock codes, e.g. 000988,300274,688012")
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output", help="Optional JSON output path for temporary analysis. Avoid writing process data under runs/.")
    parser.add_argument(
        "--source",
        default="auto",
        choices=["auto", "tencent", "baostock"],
        help="Data source priority. auto tries Tencent first, then BaoStock.",
    )
    parser.add_argument(
        "--adjustflag",
        default="2",
        choices=["1", "2", "3"],
        help="BaoStock adjustment flag: 1=后复权, 2=前复权, 3=不复权",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    codes = [normalize_code(code) for code in args.codes.split(",") if code.strip()]
    results = []
    for code in codes:
        try:
            results.append(calculate(code, args.start_date, args.end_date, args.adjustflag, args.source))
        except Exception as exc:
            results.append({"code": code, "error": str(exc)})
    try:
        payload = {
            "source": args.source,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "adjustflag": args.adjustflag,
            "adjustment_note": {"1": "后复权", "2": "前复权", "3": "不复权"}[args.adjustflag],
            "indicators": results,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(text + "\n", encoding="utf-8")
        print(text)
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
