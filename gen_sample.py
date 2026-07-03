"""
gen_sample.py \u2014 offline. Simulates a realistic daily path for the portfolio and
its blended benchmark, then runs the REAL analytics (analytics.py) to produce a
fully-populated docs/data.json for previewing before any live run.
"""
import json
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd
import analytics

ROOT = Path(__file__).resolve().parent
cfg = json.loads((ROOT / "portfolio.json").read_text())
rng = np.random.default_rng(7)

INCEP = dt.date(2025, 1, 1)
END = dt.date(2026, 7, 2)
dates = pd.bdate_range(INCEP, END)
n = len(dates)

# --- sample holdings (per-holding returns fixed; values sum to portfolio end) ---
H = [
    ("Reliance Industries","stock","Large-cap equity","nifty50tri",70000,1489.6,0.6,0.120),
    ("HDFC Bank","stock","Large-cap equity","nifty50tri",55000,1681.2,-0.3,0.090),
    ("Larsen & Toubro","stock","Large-cap equity","nifty50tri",45000,3618.0,1.1,0.260),
    ("Bharat Electronics","stock","Defence / large-cap","nifty50tri",45000,409.8,2.2,0.340),
    ("Dixon Technologies","stock","Electronics / mid-cap","niftymidcap150tri",35000,14210.0,1.8,0.410),
    ("Parag Parikh Flexi Cap","fund","Flexi-cap","nifty500tri",130000,78.42,0.4,0.190),
    ("ICICI Prudential Bluechip","fund","Large-cap","nifty50tri",90000,104.9,0.3,0.140),
    ("HDFC Flexi Cap","fund","Flexi-cap","nifty500tri",80000,1852.4,0.5,0.210),
    ("Kotak Emerging Equity","fund","Mid-cap","niftymidcap150tri",75000,129.7,0.6,0.230),
    ("Nippon India Small Cap","fund","Small-cap","niftysmallcap250tri",60000,184.6,0.9,0.160),
    ("Mirae Asset ELSS Tax Saver","fund","ELSS / multi-cap","nifty500tri",55000,46.2,0.4,0.170),
    ("SBI Contra","fund","Value / contra","nifty500tri",50000,381.5,0.5,0.220),
    ("ICICI Prudential Balanced Advantage","fund","Dynamic asset alloc",{"nifty50tri":0.6,"debtidx":0.4},90000,72.31,0.2,0.120),
    ("HDFC Corporate Bond","fund","Debt \u2014 corporate bond","debtidx",120000,31.18,0.03,0.090),
]

days = (END - INCEP).days
sectors = {h["name"]: h.get("sector", "") for h in cfg["holdings"]}
holdings, sleeve_cost = [], {}
for name, typ, sleeve, bench, cost, price, day, ret in H:
    value = cost * (1 + ret)
    cagr = (value / cost) ** (365 / days) - 1
    holdings.append({"name": name, "type": typ, "sleeve": sleeve, "sector": sectors.get(name, ""),
                     "benchmark": bench, "cost": cost, "value": value, "price": price, "day_chg": day,
                     "ret": round(ret * 100, 2), "cagr": round(cagr * 100, 2), "stale": False})
    bm = bench if isinstance(bench, dict) else {bench: 1.0}
    for tag, frac in bm.items():
        sleeve_cost[tag] = sleeve_cost.get(tag, 0) + cost * frac

port_end = sum(h["value"] for h in holdings)   # 1,177,600
port_cost = sum(h["cost"] for h in holdings)   # 1,000,000
bench_end = 1128000                            # ~+12.8%

# --- simulate correlated daily paths, then pin the endpoints exactly ---
sig_b = 0.12 / np.sqrt(252)
beta_t = 0.92
idio = 0.075 / np.sqrt(252)
br = rng.normal(0, sig_b, n)
pr = beta_t * br + rng.normal(0, idio, n)

def pin(logr, start, end):
    logr = logr.copy(); logr[0] = 0.0
    logr[1:] += (np.log(end / start) - logr[1:].sum()) / (len(logr) - 1)
    return start * np.exp(np.cumsum(logr))  # exact at both ends

port = pd.Series(pin(pr, port_cost, port_end), index=dates)
bench = pd.Series(pin(br, port_cost, bench_end), index=dates)

# --- run the real analytics ---
summ = analytics.summary(port, bench, cfg.get("risk_free_rate", 0.065))
alloc = analytics.allocations(holdings)

bench_weights = {}
for tag, c in sleeve_cost.items():
    bench_weights[tag] = {"label": cfg["benchmark_proxies"][tag]["label"],
                          "weight": round(c / port_cost * 100, 2)}

payload = {
    "sample": True,
    "name": cfg["name"], "manager": cfg["manager"],
    "as_of": "2026-07-02T15:29:00+05:30", "market": "closed",
    "inception_date": cfg["inception_date"],
    "value": round(port_end), "invested": round(port_cost), "pnl": round(port_end - port_cost),
    "summary": summ,
    "bench_weights": dict(sorted(bench_weights.items(), key=lambda x: -x[1]["weight"])),
    "allocations": alloc,
    "holdings": sorted(holdings, key=lambda h: h["value"], reverse=True),
    "thesis": cfg.get("thesis", {}),
}
for h in payload["holdings"]:
    h["value"] = round(h["value"]); h["cost"] = round(h["cost"])

(ROOT / "docs" / "data.json").write_text(json.dumps(payload, indent=2))
print(f"Sample written. port +{summ['port_ret']}% bench +{summ['bench_ret']}% "
      f"| Sharpe {summ['sharpe_port']} Sortino {summ['sortino_port']} "
      f"maxDD {summ['max_dd_port']}% beta {summ['beta']} alpha {summ['jensen_alpha']}% "
      f"TE {summ['tracking_error']}% IR {summ['info_ratio']} "
      f"up/dn {summ['up_capture']}/{summ['down_capture']}")
