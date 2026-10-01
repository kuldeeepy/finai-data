# finai-data

Public data behind [finai](https://financeai-tech.vercel.app)'s free tools. Everything here is public information, refreshed automatically. No LLMs, no paid services.

| File | What | Source | Refreshed by |
|---|---|---|---|
| `data/funds.json` | Equity holdings of popular Indian mutual funds | Each fund house's SEBI-mandated monthly portfolio disclosure | `scripts/run-holdings.sh`, cron on a Mumbai VPS, 11th and 15th of each month |
| `data/holdings-status.json` | Outcome of the last holdings run | — | same |
| `data/sbi-usd-ttbr.csv` | SBI USD/INR TT buying rates since 2020 | [sbi-fx-ratekeeper](https://github.com/sahilgupta/sbi-fx-ratekeeper) | GitHub Action, daily |

Checks: `scripts/check_rates.py` rejects bad rate files; `scripts/amc.py` refuses to write when fewer than half the funds parse fresh (failed funds keep last month's data and are flagged); the weekly **Freshness** workflow fails (and GitHub emails the owner) when data goes stale or the monthly job fails. A **Tax rules reminder** issue opens on 2 Feb and 1 Apr.

Run the holdings job by hand: `python3 -m venv .venv && .venv/bin/pip install pandas openpyxl xlrd && scripts/run-holdings.sh [--month 2026-09]`.
