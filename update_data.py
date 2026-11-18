"""TQQQ 7:3 대시보드용 시세 파일(data.json) 만들기 - GitHub Actions에서 하루 몇 번 실행
앱은 이 파일을 먼저 읽고, 파일이 최신이 아니거나 비어 있는 항목만 예전 방식(무료 프록시)으로 조회합니다.
- 종가: Yahoo 차트의 일반 종가(배당 미반영, 분할 반영) = 앱이 쓰던 값과 같은 기준
- 장중에 실행되면 오늘 봉은 빼고 전날 종가까지만 기록
- 어떤 종목이 실패하면 이전 파일의 값을 남기고 fails 목록에 적음 → 앱이 그 종목만 다시 조회"""
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

NY = ZoneInfo("America/New_York")
OUT = os.environ.get("OUT_FILE", "data.json")
SYMS = ["TQQQ", "QLD", "VFLO", "GPIQ", "QQQ"]
HIST_START = "2020-01-01"          # QLD 비교 페이지용 일별 종가 시작일


def now_ny():
    return datetime.now(NY)


def to_series(df):
    """yfinance 결과 → 날짜 문자열(미국 날짜) 인덱스의 종가 시리즈. 장중이면 오늘 봉 제외"""
    s = df["Close"].dropna()
    s = s[s > 0]
    idx = [d.strftime("%Y-%m-%d") for d in s.index]
    s = pd.Series(s.values.astype(float), index=idx)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    n = now_ny()
    if len(s) and s.index[-1] == n.strftime("%Y-%m-%d") and (n.hour, n.minute) < (16, 20):
        s = s.iloc[:-1]
    return s


def yahoo(sym, **kw):
    import yfinance as yf
    last = None
    for i in range(3):
        try:
            df = yf.Ticker(sym).history(interval="1d", auto_adjust=False, actions=True, **kw)
            if df is not None and len(df) > 5:
                return df
        except Exception as e:          # 일시적 차단·네트워크 오류 → 잠시 뒤 재시도
            last = e
        time.sleep(4 * (i + 1))
    raise RuntimeError(f"{sym} 야후 조회 실패: {last}")


def stooq(sym):
    r = requests.get(f"https://stooq.com/q/d/l/?s={sym.lower()}.us&i=d", timeout=20,
                     headers={"User-Agent": "Mozilla/5.0"})
    if not r.text.startswith("Date"):
        raise RuntimeError(f"{sym} stooq 응답 이상")
    df = pd.read_csv(io.StringIO(r.text))
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")[["Close"]]


def closes(sym, **kw):
    try:
        return to_series(yahoo(sym, **kw)), "yahoo"
    except Exception as e:
        print("  ", e, "→ stooq 시도")
        s = to_series(stooq(sym))
        if "start" in kw:
            s = s[s.index >= kw["start"]]
        return s, "stooq"


def daily_ok(s, min_len=20):
    """일봉이 맞는지(간격 중앙값 3일 이하), 너무 오래된 자료가 아닌지(8일 이내)"""
    if len(s) < min_len:
        return False
    d = pd.to_datetime(pd.Series(s.index[-15:]))
    gap = d.diff().dt.days.dropna().median()
    age = (pd.Timestamp(now_ny().date()) - d.iloc[-1]).days
    return gap <= 3 and age <= 8


def main():
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            old = {}
    out = {"v": 1, "px": dict(old.get("px", {})), "hist": dict(old.get("hist", {}))}
    for k in ("s20", "ath", "gdiv", "fx"):
        if k in old:
            out[k] = old[k]
    fails, src = [], {}

    for sym in SYMS:
        try:
            if sym == "QQQ":
                s, src[sym] = closes(sym, period="10y")
                if not daily_ok(s, 60):
                    raise RuntimeError("QQQ 일봉 이상")
                out["s20"] = round(float(s.iloc[-20:].mean()), 4)
                out["ath"] = round(float(s.max()), 4)          # 10년 종가 최고치(앱의 주 1회 10년 점검과 같은 기준)
            elif sym == "QLD":
                s, src[sym] = closes(sym, start=HIST_START)
                if not daily_ok(s):
                    raise RuntimeError("QLD 일봉 이상")
                out["hist"]["QLD"] = [[d, round(float(c), 4)] for d, c in s.items()]
            elif sym == "GPIQ":
                df = yahoo(sym, period="1y")
                src[sym] = "yahoo"
                s = to_series(df)
                if not daily_ok(s):
                    raise RuntimeError("GPIQ 일봉 이상")
                dv = df["Dividends"] if "Dividends" in df else pd.Series(dtype=float)
                lim = pd.Timestamp(datetime.now(timezone.utc) - timedelta(days=365))
                dv = dv[(dv > 0) & (dv.index.tz_convert("UTC") >= lim)]
                out["gdiv"] = {"sum": round(float(dv.sum()), 4), "n": int(len(dv))}
            else:
                s, src[sym] = closes(sym, period="3mo")
                if not daily_ok(s):
                    raise RuntimeError(f"{sym} 일봉 이상")
            out["px"][sym] = [s.index[-1], round(float(s.iloc[-1]), 4)]
            print(f"{sym}: {s.index[-1]} {s.iloc[-1]:.2f} ({src[sym]})")
        except Exception as e:
            fails.append(sym)
            print(f"{sym}: 실패 - {e}")

    try:                                                    # 환율: 앱이 쓰던 것과 같은 곳
        j = requests.get("https://open.er-api.com/v6/latest/USD", timeout=20).json()
        d = datetime.fromtimestamp(j["time_last_update_unix"], timezone.utc).strftime("%Y-%m-%d")
        out["fx"] = [d, round(float(j["rates"]["KRW"]), 2)]
        print(f"환율: {out['fx']}")
    except Exception as e:
        fails.append("FX")
        print(f"환율: 실패 - {e}")

    if len(fails) >= len(SYMS):
        raise SystemExit("모든 종목 조회 실패 - 파일을 바꾸지 않습니다")
    t = datetime.now(timezone.utc)
    out["updated_utc"] = t.strftime("%Y-%m-%dT%H:%M:%SZ")
    out["updated_ny"] = t.astimezone(NY).strftime("%Y-%m-%d %H:%M")
    out["fails"] = fails
    out["src"] = src
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("저장:", OUT, os.path.getsize(OUT), "bytes / 실패:", fails or "없음")


if __name__ == "__main__":
    main()
