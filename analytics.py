"""
analytics.py \u2014 portfolio risk/return maths.

Pure functions over two daily value series (portfolio, benchmark), both pandas
Series indexed by date and starting on the same inception date. Kept separate
from data-fetching so the exact same code runs on live data and on the sample
generator (which is how the maths gets tested offline).

Conventions: 252 trading days/yr, calendar-day CAGR, daily risk-free derived
from an annual rate. Everything is gross of costs and taxes (model portfolio).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _daily_rf(annual_rf: float) -> float:
    return (1 + annual_rf) ** (1 / TRADING_DAYS) - 1


def cagr(series: pd.Series) -> float:
    days = (series.index[-1] - series.index[0]).days
    if days <= 0:
        return 0.0
    return (series.iloc[-1] / series.iloc[0]) ** (365.0 / days) - 1


def total_return(series: pd.Series) -> float:
    return series.iloc[-1] / series.iloc[0] - 1


def ann_vol(rets: pd.Series) -> float:
    return float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS))


def sharpe(rets: pd.Series, annual_rf: float) -> float:
    rf = _daily_rf(annual_rf)
    sd = rets.std(ddof=1)
    if sd == 0:
        return 0.0
    return float((rets.mean() - rf) / sd * np.sqrt(TRADING_DAYS))


def sortino(rets: pd.Series, annual_rf: float) -> float:
    rf = _daily_rf(annual_rf)
    downside = np.minimum(rets - rf, 0.0)
    dd = np.sqrt((downside ** 2).mean())
    if dd == 0:
        return 0.0
    return float((rets.mean() - rf) / dd * np.sqrt(TRADING_DAYS))


def drawdown_series(series: pd.Series) -> pd.Series:
    return series / series.cummax() - 1


def max_drawdown(series: pd.Series) -> float:
    return float(drawdown_series(series).min())


def beta(port_rets: pd.Series, bench_rets: pd.Series) -> float:
    var = bench_rets.var(ddof=1)
    if var == 0:
        return 0.0
    return float(port_rets.cov(bench_rets) / var)


def jensen_alpha_ann(port_rets, bench_rets, annual_rf, b) -> float:
    rf = _daily_rf(annual_rf)
    daily = (port_rets.mean() - rf) - b * (bench_rets.mean() - rf)
    return float(daily * TRADING_DAYS)


def tracking_error(port_rets: pd.Series, bench_rets: pd.Series) -> float:
    return float((port_rets - bench_rets).std(ddof=1) * np.sqrt(TRADING_DAYS))


def capture(port_rets: pd.Series, bench_rets: pd.Series, up: bool) -> float:
    mask = bench_rets > 0 if up else bench_rets < 0
    if mask.sum() == 0:
        return 0.0
    p = (1 + port_rets[mask]).prod() - 1
    b = (1 + bench_rets[mask]).prod() - 1
    if b == 0:
        return 0.0
    return float(p / b * 100)


def r_squared(port_rets: pd.Series, bench_rets: pd.Series) -> float:
    return float(port_rets.corr(bench_rets) ** 2)


def var_95(rets: pd.Series) -> float:
    return float(rets.quantile(0.05))


def monthly_returns(series: pd.Series) -> pd.Series:
    m = series.resample("ME").last()
    return m.pct_change().dropna()


def summary(port: pd.Series, bench: pd.Series, annual_rf: float) -> dict:
    """All portfolio-vs-benchmark statistics + the series needed to chart them."""
    port, bench = port.dropna(), bench.dropna()
    idx = port.index.intersection(bench.index)
    port, bench = port.loc[idx], bench.loc[idx]
    pr, br = port.pct_change().dropna(), bench.pct_change().dropna()
    b = beta(pr, br)

    dd_p = drawdown_series(port)
    mp, mb = monthly_returns(port), monthly_returns(bench)
    months = sorted(set(mp.index) | set(mb.index))

    days = (port.index[-1] - port.index[0]).days

    return {
        "days": days,
        "years": round(days / 365.25, 2),
        "risk_free": annual_rf,
        # returns
        "port_ret": round(total_return(port) * 100, 2),
        "bench_ret": round(total_return(bench) * 100, 2),
        "excess_ret": round((total_return(port) - total_return(bench)) * 100, 2),
        "cagr_port": round(cagr(port) * 100, 2),
        "cagr_bench": round(cagr(bench) * 100, 2),
        # risk
        "vol_port": round(ann_vol(pr) * 100, 2),
        "vol_bench": round(ann_vol(br) * 100, 2),
        "sharpe_port": round(sharpe(pr, annual_rf), 2),
        "sharpe_bench": round(sharpe(br, annual_rf), 2),
        "sortino_port": round(sortino(pr, annual_rf), 2),
        "sortino_bench": round(sortino(br, annual_rf), 2),
        "max_dd_port": round(max_drawdown(port) * 100, 2),
        "max_dd_bench": round(max_drawdown(bench) * 100, 2),
        "cur_dd_port": round(dd_p.iloc[-1] * 100, 2),
        "var95": round(var_95(pr) * 100, 2),
        # vs benchmark
        "beta": round(b, 2),
        "jensen_alpha": round(jensen_alpha_ann(pr, br, annual_rf, b) * 100, 2),
        "tracking_error": round(tracking_error(pr, br) * 100, 2),
        "info_ratio": round((cagr(port) - cagr(bench)) / (tracking_error(pr, br) or 1e-9), 2),
        "up_capture": round(capture(pr, br, True), 1),
        "down_capture": round(capture(pr, br, False), 1),
        "r2": round(r_squared(pr, br), 2),
        # behaviour
        "positive_days": round((pr > 0).mean() * 100, 1),
        "best_day": round(pr.max() * 100, 2),
        "worst_day": round(pr.min() * 100, 2),
        # series for charts
        "series": [
            {"date": d.strftime("%Y-%m-%d"),
             "port": round(float(port.loc[d])),
             "bench": round(float(bench.loc[d])),
             "dd": round(float(dd_p.loc[d]) * 100, 2)}
            for d in port.index
        ],
        "monthly": [
            {"m": m.strftime("%b %y"),
             "port": round(float(mp.get(m, np.nan)) * 100, 2) if m in mp.index else None,
             "bench": round(float(mb.get(m, np.nan)) * 100, 2) if m in mb.index else None}
            for m in months
        ],
    }


# --------------------------------------------------------------------------- #
#  Allocation / attribution over holdings
# --------------------------------------------------------------------------- #
_CAP = {"nifty50tri": "Large cap", "nifty500tri": "Multi cap",
        "niftymidcap150tri": "Mid cap", "niftysmallcap250tri": "Small cap",
        "debtidx": "Debt"}


def _bench_map(benchmark) -> dict:
    return {benchmark: 1.0} if isinstance(benchmark, str) else dict(benchmark)


def allocations(holdings: list[dict]) -> dict:
    """holdings: dicts with keys type, sleeve, benchmark, cost, value, name, ret."""
    total_v = sum(h["value"] for h in holdings) or 1
    total_c = sum(h["cost"] for h in holdings) or 1

    asset, cap, sleeve, kind = {}, {}, {}, {}
    for h in holdings:
        w = h["value"] / total_v * 100
        bm = _bench_map(h["benchmark"])
        for tag, frac in bm.items():
            a = "Debt" if tag == "debtidx" else "Equity"
            asset[a] = asset.get(a, 0) + w * frac
            c = _CAP.get(tag, "Other")
            cap[c] = cap.get(c, 0) + w * frac
        sleeve[h["sleeve"]] = sleeve.get(h["sleeve"], 0) + w
        k = "Direct equity" if h["type"] == "stock" else "Mutual funds"
        kind[k] = kind.get(k, 0) + w

    weights = sorted((h["value"] / total_v for h in holdings), reverse=True)
    hhi = sum((x) ** 2 for x in weights)  # x already in %, so /100^2
    hhi_frac = sum((h["value"] / total_v) ** 2 for h in holdings)

    # contribution to portfolio return, in percentage points of cost
    contrib = sorted(
        [{"name": h["name"], "type": h["type"],
          "contrib": round((h["value"] - h["cost"]) / total_c * 100, 2)}
         for h in holdings],
        key=lambda x: x["contrib"], reverse=True)

    rnd = lambda d: {k: round(v, 1) for k, v in sorted(d.items(), key=lambda x: -x[1])}
    return {
        "asset": rnd(asset), "cap": rnd(cap), "sleeve": rnd(sleeve), "kind": rnd(kind),
        "concentration": {
            "top5": round(sum(weights[:5]) * 100, 1),
            "effective_n": round(1 / hhi_frac, 1),
            "hhi": round(hhi_frac * 10000),  # 0\u201310000 scale
        },
        "attribution": contrib,
    }
