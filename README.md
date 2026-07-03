# Live Model Portfolio Tracker

A self-updating institutional-style dashboard for an Indian multi-asset portfolio
(direct equities + mutual funds). It reconstructs a **full daily value history since
inception** for both the portfolio and a **blended benchmark**, then computes the
risk/return stats a buy-side desk actually looks at.

- **Direct equities** mark **intraday** off NSE (`yfinance`).
- **Mutual funds** mark to the **latest daily NAV** (AMFI via `mfapi.in`).
- **Benchmark** = each sleeve mapped to its own **Total-Return (TRI) proxy**
  (Nifty 50 / 500 / Midcap 150 / Smallcap 250 + a gilt index for debt), re-weighted
  to the portfolio's actual allocation — so beating it means *selection* worked, not asset mix.

**Metrics:** CAGR · volatility · Sharpe · Sortino · max & current drawdown · beta ·
Jensen's alpha · tracking error · information ratio · up/down capture · R² · VaR(95%) ·
positive-day hit rate — plus **return attribution** (contribution per holding), asset/cap/sleeve
**allocation** breakdowns, concentration (top-5, effective N, HHI), and a monthly-returns view.

**Stack:** Python engine (GitHub Actions cron) → `docs/data.json` → static dashboard on GitHub Pages. No servers, no API keys, free.

```
portfolio.json        ← YOUR holdings, amounts & thesis  (the only file you edit)
analytics.py          ← risk/return maths (pure functions)
fetch.py              ← live engine: builds daily series, runs analytics, writes data.json
gen_sample.py         ← offline: simulates a path to preview the dashboard before going live
requirements.txt
.github/workflows/update.yml
docs/ index.html · data.json
```

---

## ✏️ Changing stocks, funds & amounts  (read this)

**Everything lives in `portfolio.json` → `"holdings"`.** Each entry is one line. After any
edit, run `python fetch.py` (or trigger the GitHub Action) and the dashboard updates.

### Change how much is invested in something
Edit its **`alloc`** (rupees). Then delete that holding's cached `units`, `cost`, `cost_price`
so they re-derive from the inception price:
```jsonc
{"name": "HDFC Bank", "type": "stock", "ticker": "HDFCBANK.NS", "alloc": 90000, ...}
//                                      was 55000 → now 90000; delete units/cost/cost_price
```
> Amounts do **not** need to sum to ₹10L. Invested capital = the sum of all `alloc`s, computed automatically.

### Add a stock
Copy any stock line and change the fields. `ticker` is the **Yahoo symbol** — NSE uses `.NS`, BSE uses `.BO`:
```jsonc
{"name": "Tata Motors", "type": "stock", "ticker": "TATAMOTORS.NS",
 "alloc": 40000, "sleeve": "Auto / large-cap", "sector": "Automobiles", "benchmark": "nifty50tri"}
```

### Add a mutual fund
Copy any fund line. `query` is the **full fund name incl. "Direct Growth"** — the engine
resolves it to an AMFI code automatically:
```jsonc
{"name": "Quant Small Cap", "type": "fund", "query": "Quant Small Cap Fund Direct Growth",
 "alloc": 45000, "sleeve": "Small-cap", "benchmark": "niftysmallcap250tri"}
```

### Remove a holding
Delete its whole `{ ... }` block.

### `benchmark` — how a holding is judged
Use one sleeve tag, or a weighted blend for hybrids. Tags must exist under `benchmark_proxies`:
```jsonc
"benchmark": "niftymidcap150tri"                       // single sleeve
"benchmark": {"nifty50tri": 0.6, "debtidx": 0.4}       // e.g. a balanced-advantage fund
```
Available tags: `nifty50tri`, `nifty500tri`, `niftymidcap150tri`, `niftysmallcap250tri`, `debtidx`.
(There's also a live `_edit_guide` block inside `portfolio.json` repeating this.)

### Change the whole capital base
Just scale the `alloc`s, or set them to whatever you actually want to model — the engine
reads real prices and computes everything from there. `risk_free_rate` (default 0.065) drives Sharpe/Sortino.

---

## 🌐 Edit from the website instead (no code)

Don't want to touch `portfolio.json` at all? The site ships with a **Manage page** at
`https://<user>.github.io/<repo>/manage.html` (also linked in the dashboard footer).

1. One-time: create a **fine-grained GitHub token** — [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new) → *Only select repositories* → this repo → *Permissions ▸ Repository ▸ Contents ▸ Read and write* → Generate.
2. Open the Manage page, paste your **username / repo / token**, press **Load**.
3. Add an equity or fund with the **+** buttons, edit any amount inline, press **Save**.

Saving writes `portfolio.json` back to the repo and the push **auto-triggers a data refresh** —
the dashboard updates in about a minute. The token lives in *your browser only* (session storage
by default; other visitors never see it). Treat it like a password; give it a short expiry.

## Deploy for a live URL (~10 min)

1. Push these files to a new GitHub repo.
2. **Settings ▸ Pages** → deploy from branch **main**, folder **/docs**. URL: `https://<user>.github.io/<repo>/`.
3. **Settings ▸ Actions ▸ General** → Workflow permissions → **Read and write**.
4. **Actions** tab → *Update portfolio data* → **Run workflow** (first live pull).
   The sample banner disappears once real data lands.

**Custom domain:** add `docs/CNAME` containing `portfolio.adityanair.co.in`, and point that
subdomain's CNAME at `<user>.github.io`.

## Run locally
```bash
pip install -r requirements.txt
python fetch.py                      # writes docs/data.json + caches codes/units
python -m http.server -d docs 8000   # http://localhost:8000
# preview without any network:
python gen_sample.py                 # regenerates the sample data.json
```

## Verify the funds once (important)
After the first run, open `portfolio.json` and confirm each auto-resolved `amfi_code` is the
**Direct-Growth** plan you meant (the run log prints `resolved '<query>' -> [code] <full name>`).
The **debt proxy** (`debtidx`) is the softest — a gilt index fund standing in for the debt sleeve;
swap its `query` for a CRISIL Composite Bond / target-maturity index fund if you want it tighter.

## Honest caveats
- No intraday NAV exists for mutual funds — that sleeve is only as fresh as the day's declared NAV.
- Figures are **gross** of costs, taxes and tracking error (a model/research artifact).
- Yahoo Finance is unofficial; a failed fetch marks that row *stale* instead of crashing the run.
- A holding held < ~1 month has a noisy CAGR (annualising a tiny window) — expected.
