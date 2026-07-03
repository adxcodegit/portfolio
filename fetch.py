#!/usr/bin/env python3
"""
Portfolio engine (live).

Reconstructs a full daily value history since inception for both the portfolio
and its blended benchmark, then runs analytics.py to compute the institutional
risk/return stats, allocation breakdowns and return attribution. Writes docs/data.json.

Data sources (free, no key):
  Equities : Yahoo Finance via yfinance   (NSE tickers, e.g. RELIANCE.NS)
  MF NAVs  : https://api.mfapi.in          (AMFI NAV mirror, CORS-enabled)
"""
import json
import sys
import datetime as dt
from pathlib import Path

import requests
import pandas as pd
import numpy as np
import analytics

ROOT = Path(__file__).resolve().parent
CFG_PATH = ROOT / "portfolio.json"
OUT_PATH = ROOT / "docs" / "data.json"
MFAPI = "https://api.mfapi.in/mf"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UA = {"User-Agent": "portfolio-tracker/2.0"}

try:
    import yfinance as yf
except Exception:
    yf = None


def log(*a): print("[engine]", *a, flush=True)


# --------------------------------------------------------------------------- #
#  Mutual funds (mfapi.in)
# --------------------------------------------------------------------------- #
def mf_resolve(query: str):
    r = requests.get(f"{MFAPI}/search", params={"q": query}, headers=UA, timeout=20)
    r.raise_for_status()
    res = r.json()
    if not res:
        return None
    def score(it):
        n = it["schemeName"].lower(); s = 0
        s += 2 if "direct" in n else 0
        s += 2 if "growth" in n else 0
        s -= 3 if ("idcw" in n or "dividend" in n) else 0
        s -= 1 if "regular" in n else 0
        return s
    best = max(res, key=score)
    log(f"  resolved '{query}' -> [{best['schemeCode']}] {best['schemeName']}")
    return int(best["schemeCode"])


_MF = {}
def mf_series(code: int) -> pd.Series:
    if code in _MF:
        return _MF[code]
    r = requests.get(f"{MFAPI}/{code}", headers=UA, timeout=20)
    r.raise_for_status()
    data = r.json().get("data", [])
    idx = pd.to_datetime([row["date"] for row in data], format="%d-%m-%Y")
    vals = [float(row["nav"]) for row in data]
    s = pd.Series(vals, index=idx).sort_index()
    _MF[code] = s
    return s


# --------------------------------------------------------------------------- #
#  Equities (yfinance)
# --------------------------------------------------------------------------- #
_EQ = {}
def eq_series(ticker: str, start: dt.date) -> pd.Series:
    if ticker in _EQ:
        return _EQ[ticker]
    h = yf.Ticker(ticker).history(start=(start - dt.timedelta(days=7)).isoformat(), auto_adjust=True)
    s = h["Close"].copy()
    s.index = s.index.tz_localize(None).normalize()
    _EQ[ticker] = s
    return s


def eq_quote(ticker: str):
    t = yf.Ticker(ticker)
    try:
        fi = t.fast_info
        return float(fi["last_price"]), float(fi["previous_close"])
    except Exception:
        s = eq_series(ticker, dt.date.today() - dt.timedelta(days=10))
        return float(s.iloc[-1]), float(s.iloc[-2] if len(s) > 1 else s.iloc[-1])


def market_status(now):
    if now.weekday() >= 5:
        return "closed"
    o = now.replace(hour=9, minute=15, second=0, microsecond=0)
    c = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return "open" if o <= now <= c else "closed"


def align(s: pd.Series, master: pd.DatetimeIndex) -> pd.Series:
    return s.reindex(master.union(s.index)).ffill().reindex(master).ffill().bfill()


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    cfg = json.loads(CFG_PATH.read_text())
    incep = dt.date.fromisoformat(cfg["inception_date"])
    rf = cfg.get("risk_free_rate", 0.065)
    now = dt.datetime.now(IST)
    today = now.date()
    master = pd.bdate_range(incep, today)
    dirty = False

    log("Resolving funds & benchmark proxies...")
    for h in cfg["holdings"]:
        if h["type"] == "fund" and "amfi_code" not in h:
            c = mf_resolve(h["query"])
            if c: h["amfi_code"] = c; dirty = True
    for tag, p in cfg["benchmark_proxies"].items():
        if "amfi_code" not in p:
            c = mf_resolve(p["query"])
            if c: p["amfi_code"] = c; dirty = True

    value_frames = {}
    rows = []
    sleeve_cost = {}
    total_cost = 0.0
    alloc_holdings = []

    def add_sleeve(bench, cost):
        bm = {bench: 1.0} if isinstance(bench, str) else bench
        for tag, w in bm.items():
            sleeve_cost[tag] = sleeve_cost.get(tag, 0) + cost * w

    for h in cfg["holdings"]:
        try:
            if h["type"] == "stock":
                s = eq_series(h["ticker"], incep)
                incep_px = h.get("cost_price") or float(s[s.index >= pd.Timestamp(incep)].iloc[0])
                if "units" not in h:
                    h["units"] = h["alloc"] / incep_px
                    h["cost_price"] = incep_px
                    h["cost"] = h["units"] * incep_px
                    dirty = True
                last, prev = eq_quote(h["ticker"])
                day_chg = (last / prev - 1) * 100 if prev else 0.0
                price = last
            else:
                code = h["amfi_code"]
                s = mf_series(code)
                incep_nav = h.get("cost_price") or float(s[s.index <= pd.Timestamp(incep)].iloc[-1])
                if "units" not in h:
                    h["units"] = h["alloc"] / incep_nav
                    h["cost_price"] = incep_nav
                    h["cost"] = h["units"] * incep_nav
                    dirty = True
                price = float(s.iloc[-1])
                prev = float(s.iloc[-2]) if len(s) > 1 else price
                day_chg = (price / prev - 1) * 100 if prev else 0.0

            vseries = align(s, master) * h["units"]
            value_frames[h["name"]] = vseries
            value = h["units"] * price
            cost = h["cost"]
            days = (today - incep).days or 1
            cagr = (value / cost) ** (365 / days) - 1

            total_cost += cost
            add_sleeve(h["benchmark"], cost)
            row = {"name": h["name"], "type": h["type"], "sleeve": h["sleeve"],
                   "sector": h.get("sector", ""), "benchmark": h["benchmark"], "cost": round(cost), "value": round(value),
                   "price": round(price, 2), "day_chg": round(day_chg, 2),
                   "ret": round((value / cost - 1) * 100, 2), "cagr": round(cagr * 100, 2),
                   "stale": False}
            rows.append(row)
            alloc_holdings.append({**row, "cost": cost, "value": value})
        except Exception as e:
            log(f"  !! {h['name']}: {e}")
            cost = h.get("cost", h["alloc"]); total_cost += cost
            add_sleeve(h["benchmark"], cost)
            row = {"name": h["name"], "type": h["type"], "sleeve": h.get("sleeve", ""),
                   "sector": h.get("sector", ""), "benchmark": h["benchmark"], "cost": round(cost), "value": round(cost),
                   "price": None, "day_chg": None, "ret": None, "cagr": None, "stale": True}
            rows.append(row)
            alloc_holdings.append({**row, "cost": cost, "value": cost})

    port = pd.DataFrame(value_frames).sum(axis=1)

    bench = pd.Series(0.0, index=master)
    for tag, cost in sleeve_cost.items():
        w = cost / total_cost
        try:
            s = mf_series(cfg["benchmark_proxies"][tag]["amfi_code"])
            s = align(s, master)
            g = s / s.iloc[0]
        except Exception as e:
            log(f"  !! benchmark {tag}: {e}"); g = pd.Series(1.0, index=master)
        bench = bench + total_cost * w * g

    port.iloc[-1] = sum(r["value"] for r in rows)  # freshest intraday total

    summ = analytics.summary(port, bench, rf)
    alloc = analytics.allocations(alloc_holdings)

    bench_weights = {t: {"label": cfg["benchmark_proxies"][t]["label"],
                         "weight": round(c / total_cost * 100, 2)}
                     for t, c in sleeve_cost.items()}
    bench_weights = dict(sorted(bench_weights.items(), key=lambda x: -x[1]["weight"]))

    total_value = float(port.iloc[-1])
    payload = {
        "sample": False, "name": cfg["name"], "manager": cfg["manager"],
        "as_of": now.isoformat(timespec="seconds"), "market": market_status(now),
        "inception_date": cfg["inception_date"],
        "value": round(total_value), "invested": round(total_cost),
        "pnl": round(total_value - total_cost),
        "summary": summ, "bench_weights": bench_weights, "allocations": alloc,
        "holdings": sorted(rows, key=lambda r: r["value"], reverse=True),
        "thesis": cfg.get("thesis", {}),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    log(f"Wrote {OUT_PATH} | value \u20b9{payload['value']:,} ret {summ['port_ret']}% "
        f"bench {summ['bench_ret']}% Sharpe {summ['sharpe_port']} maxDD {summ['max_dd_port']}%")

    if dirty:
        CFG_PATH.write_text(json.dumps(cfg, indent=2))
        log("Cached codes/units into portfolio.json.")


if __name__ == "__main__":
    if yf is None:
        log("Install deps first: pip install -r requirements.txt"); sys.exit(1)
    main()
