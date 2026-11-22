"""전략 실험용 과거 시세 내려받기 → lab 폴더에 종목별 CSV 저장
GitHub > Actions > Export prices > Run workflow 로 실행 (한 번만 돌리면 됨)"""
import os
import time

import pandas as pd
import yfinance as yf

TICKS = ["^NDX", "QQQ", "TQQQ", "QLD", "VFLO", "COWZ", "IWD", "SPY", "SGOV", "^IRX", "KRW=X"]
os.makedirs("lab", exist_ok=True)
for t in TICKS:
    df = None
    for k in range(4):
        try:
            df = yf.download(t, start="1985-01-01", auto_adjust=False, progress=False, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if len(df) > 50:
                break
        except Exception as e:  # 잠깐 막히면 다시 시도
            print(t, "오류:", e)
        time.sleep(5 * (k + 1))
    if df is None or len(df) <= 50:
        print(t, "실패 - 건너뜀")
        continue
    df.index = pd.to_datetime(df.index).tz_localize(None)
    cols = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in df.columns]
    name = t.replace("^", "").replace("=", "_")
    df[cols].round(6).to_csv(f"lab/{name}.csv", index_label="Date")
    print(f"{t}: {len(df)}일 {df.index[0].date()} ~ {df.index[-1].date()}")
