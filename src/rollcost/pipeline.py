"""What commodity exposure actually delivered: futures-based funds versus the spot price they track.

Steps: load pinned sources -> daily total returns (split-adjusted closes + cash distributions)
-> month-end returns -> roll gap versus spot and T-bills -> switching rule test -> figures + metrics.json.
"""
import json
import sys
from pathlib import Path

import duckdb
import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

COL = {"USO": "#c0392b", "USL": "#1f5fbf", "DBO": "#e08e0b", "UNG": "#c0392b", "UNL": "#1f5fbf",
       "GSG": "#c0392b", "DBC": "#e08e0b", "USCI": "#1f5fbf", "GLD": "#b8962e", "SPY": "#555555",
       "WTI": "#111111", "HH": "#111111"}


# ---------------------------------------------------------------- data
def daily_total_returns(prices_path, div_path, symbols, end):
    q = f"select symbol, report_date d, close::double c from '{prices_path}' where symbol in {tuple(symbols)} and report_date <= '{end}'"
    px = duckdb.sql(q).df()
    px["d"] = pd.to_datetime(px["d"])
    px = px.pivot(index="d", columns="symbol", values="c").sort_index()
    tr = px.pct_change()
    dv = duckdb.sql(f"select symbol, report_date d, amount::double a from '{div_path}' where symbol in {tuple(symbols)}").df()
    dv["d"] = pd.to_datetime(dv["d"])
    for _, r in dv.iterrows():  # add each cash distribution back on its ex-date
        if r.d in px.index and r.d > px[r.symbol].first_valid_index():
            i = px.index.get_loc(r.d)
            tr.iloc[i, tr.columns.get_loc(r.symbol)] = (px[r.symbol].iloc[i] + r.a) / px[r.symbol].iloc[i - 1] - 1
    return px, tr


def spot_monthly(path, end):
    s = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")["Price"].sort_index()
    s = s.loc[:end]
    return s.resample("ME").last()


def bill_monthly(path, end):
    y = duckdb.sql(f"select report_date d, bc_3month::double y from '{path}'").df()
    y["d"] = pd.to_datetime(y["d"])
    y = y.set_index("d")["y"].sort_index().loc[:end].ffill()
    daily = (1 + y.shift(1).fillna(0) / 252)
    return daily.resample("ME").prod() - 1


def monthly(tr):
    return (1 + tr).resample("ME").prod() - 1


# ---------------------------------------------------------------- stats
def cagr(r):
    r = r.dropna()
    return float((1 + r).prod() ** (12 / len(r)) - 1)


def vol(r):
    return float(r.std() * np.sqrt(12))


def max_dd(r):
    w = (1 + r.dropna()).cumprod()
    return float((w / w.cummax() - 1).min())


def gap(fund, spot_ret, bill):
    """Annualised gap between a fund and (spot price change + T-bill income).

    The fund holds T-bills as collateral, so fund ~= spot change + bill income + roll + fees.
    Measured in log terms so volatility does not bias the comparison."""
    x = pd.concat([fund, spot_ret, bill], axis=1).dropna()
    g = np.log1p(x.iloc[:, 0]) - np.log1p(x.iloc[:, 1]) - np.log1p(x.iloc[:, 2])
    return float(np.expm1(g.mean() * 12)), g


def beta_r2(fund, spot_ret):
    x = pd.concat([fund, spot_ret], axis=1).dropna()
    b = np.polyfit(x.iloc[:, 1], x.iloc[:, 0], 1)[0]
    return float(b), float(x.corr().iloc[0, 1] ** 2)


def switch_rule(front, deferred, front_gap, lookback, cost_bps):
    """Hold the front-month fund next month only if its trailing realised gap was positive
    (a backwardation signal known at month-end); otherwise hold the deferred fund."""
    sig = front_gap.rolling(lookback).sum().shift(1) > 0
    r = pd.Series(np.where(sig, front, deferred), index=front.index)
    switches = sig.astype(int).diff().abs().fillna(0)
    return r - switches * cost_bps / 1e4, sig


def by_year(r):
    return (1 + r).groupby(r.index.year).prod() - 1


# ---------------------------------------------------------------- figures
pct = FuncFormatter(lambda v, _: f"{v:.0%}")


def fig_growth(series, title, path, ylabel="Value of $1 (log scale)", spot_label=None):
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for k, r in series.items():
        w = (1 + r.dropna()).cumprod()
        ax.plot(w.index, w.values, lw=2.2 if k in ("WTI", "HH") else 1.8, color=COL.get(k, None),
                ls="--" if k in ("WTI", "HH") else "-", label=spot_label if (k in ("WTI", "HH") and spot_label) else k)
    ax.set_yscale("log")
    lo, hi = ax.get_ylim()
    ticks = [t for t in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 3, 5, 10) if lo <= t <= hi]
    ax.set_yticks(ticks); ax.minorticks_off()
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:g}"))
    ax.set_title(title, fontsize=12, loc="left")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=.3)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def fig_gap_by_year(gu, gl, path):
    yu = np.expm1(gu.groupby(gu.index.year).sum()); yl = np.expm1(gl.groupby(gl.index.year).sum())
    yrs = yu.index.values
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    ax.bar(yrs - .2, yu.values, .4, color=COL["USO"], label="Front month (USO)")
    ax.bar(yrs + .2, yl.values, .4, color=COL["USL"], label="12-month strip (USL)")
    ax.axhline(0, color="black", lw=.8)
    ax.yaxis.set_major_formatter(pct)
    ax.set_xticks(yrs); ax.set_xticklabels([str(y) if y < 2026 else "2026\nYTD" for y in yrs], fontsize=8)
    ax.set_title("Oil: fund return minus spot change minus T-bill income, by year", fontsize=12, loc="left")
    ax.set_ylabel("Gap to spot + bills")
    ax.grid(axis="y", alpha=.3); ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def fig_switch(curves, path):
    fig, ax = plt.subplots(figsize=(9, 4.6))
    sty = {"USL": ("-", COL["USL"], 2.2), "USO": ("-", COL["USO"], 1.6)}
    for k, r in curves.items():
        ls, c, lw = sty.get(k, (":", "#6b5fbf", 1.6))
        w = (1 + r).cumprod(); ax.plot(w.index, w.values, ls=ls, color=c if k in sty else None, lw=lw, label=k)
    ax.set_yscale("log"); lo, hi = ax.get_ylim()
    ax.set_yticks([t for t in (0.02, 0.05, 0.1, 0.2, 0.5, 1, 2) if lo <= t <= hi]); ax.minorticks_off()
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:g}"))
    ax.set_title("Switching to the front month when the curve looks backwardated did not beat holding the strip", fontsize=11, loc="left")
    ax.set_ylabel("Value of $1 (log scale)"); ax.grid(alpha=.3); ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


# ---------------------------------------------------------------- main
def main(cfg_path="configs/default.yaml"):
    cfg = yaml.safe_load(open(cfg_path))
    out = Path(cfg["out_dir"]); (out / "figures").mkdir(parents=True, exist_ok=True)
    end = cfg["end"]
    syms = list(cfg["oil"]["vehicles"]) + list(cfg["gas"]["vehicles"]) + list(cfg["broad"]["vehicles"]) + cfg["reference"]
    px, tr = daily_total_returns(cfg["prices"], cfg["dividends"], syms, end)
    bad = tr.abs().max()
    assert (bad < 0.5).all(), f"daily move above 50% (possible unadjusted split): {bad[bad >= 0.5].to_dict()}"
    m = monthly(tr)
    m = m.loc[: pd.Timestamp(end) + pd.offsets.MonthEnd(0)]
    spot = pd.concat({"WTI": spot_monthly(cfg["wti"], end), "HH": spot_monthly(cfg["henry_hub"], end)}, axis=1).pct_change()
    bill = bill_monthly(cfg["treasury"], end)
    M = {"end": end, "notes": "Monthly returns; last month is partial (to the end date)."}

    # ---- oil and gas
    gaps = {}
    for block in ("oil", "gas"):
        b = cfg[block]; s = b["spot"]; st = b["start"]
        idx = m.loc[st:].index
        sp, bl = spot[s].loc[st:], bill.loc[st:]
        res = {"spot": s, "start": st, "months": int(len(idx)), "spot_cagr": cagr(sp), "bill_cagr": cagr(bl), "vehicles": {}}
        for v, desc in b["vehicles"].items():
            f = m[v].loc[st:]
            g, gs = gap(f, sp, bl); gaps[v] = gs
            be, r2 = beta_r2(f, sp)
            h1 = gap(f.loc[:"2016"], sp.loc[:"2016"], bl.loc[:"2016"])[0]
            h2 = gap(f.loc["2017":], sp.loc["2017":], bl.loc["2017":])[0]
            res["vehicles"][v] = {"design": desc, "cagr": cagr(f), "vol": vol(f), "max_dd": max_dd(f), "gap_ann": g,
                                  "gap_2008_2016" if block == "oil" else "gap_to_2016": h1, "gap_2017_2026": h2,
                                  "beta_to_spot": be, "r2_to_spot": r2,
                                  "growth_of_1": float((1 + f).prod()),
                                  "sleeve_end_usd": float(cfg["sleeve_usd"] * (1 + f).prod())}
        res["spot_growth_of_1"] = float((1 + sp).prod())
        M[block] = res

    # ---- broad baskets
    st = cfg["broad"]["start"]
    bb = {"start": st, "bill_cagr": cagr(bill.loc[st:]), "vehicles": {}}
    for v, desc in list(cfg["broad"]["vehicles"].items()) + [(k, "reference") for k in cfg["reference"]]:
        f = m[v].loc[st:]
        ex = f - bill.loc[st:]
        bb["vehicles"][v] = {"design": desc, "cagr": cagr(f), "vol": vol(f), "max_dd": max_dd(f),
                             "sharpe": float(ex.mean() / ex.std() * np.sqrt(12)),
                             "corr_spy": float(f.corr(m["SPY"].loc[st:])),
                             "ret_2022": float(by_year(f).get(2022, np.nan)),
                             "ret_2026_ytd": float(by_year(f).get(2026, np.nan))}
    M["broad"] = bb

    # ---- calendar-year table (oil and gas)
    years = {}
    for v in ["USO", "USL", "DBO", "UNG", "UNL", "GSG", "DBC", "USCI"]:
        st = cfg["oil"]["start"] if v in cfg["oil"]["vehicles"] else cfg["gas"]["start"] if v in cfg["gas"]["vehicles"] else cfg["broad"]["start"]
        years[v] = {int(k): float(x) for k, x in by_year(m[v].loc[st:]).items()}
    years["WTI_spot"] = {int(k): float(x) for k, x in by_year(spot["WTI"].loc[cfg["oil"]["start"]:]).items()}
    years["HH_spot"] = {int(k): float(x) for k, x in by_year(spot["HH"].loc[cfg["gas"]["start"]:]).items()}
    M["calendar_years"] = years

    # ---- switching rule (pre-specified, all lookbacks reported)
    sw = cfg["switch"]; st = cfg["oil"]["start"]
    fr, de = m[sw["front"]].loc[st:], m[sw["deferred"]].loc[st:]
    sres = {"always_front_cagr": cagr(fr), "always_deferred_cagr": cagr(de), "rules": {}}
    curves = {"USL": de, "USO": fr}
    for L in sw["lookbacks_months"]:
        r, sig = switch_rule(fr, de, gaps[sw["front"]], L, sw["cost_bps_per_switch"])
        sres["rules"][f"{L}m"] = {"cagr": cagr(r), "vol": vol(r), "max_dd": max_dd(r), "share_months_front": float(sig.mean()),
                                  "switches": int(sig.astype(int).diff().abs().sum())}
        curves[f"Switch, {L}-month signal"] = r
    # does a positive trailing gap predict the next month's front-minus-strip spread?
    s3 = gaps[sw["front"]].rolling(3).sum().shift(1)
    spread = (fr - de)
    sres["next_month_front_minus_strip_mean"] = {"after_positive_3m_gap": float(spread[s3 > 0].mean()), "n_pos": int((s3 > 0).sum()),
                                                  "after_negative_3m_gap": float(spread[s3 <= 0].mean()), "n_neg": int((s3 <= 0).sum())}
    M["switching"] = sres

    # ---- 2020 and 2026 episodes
    M["episodes"] = {
        "2020": {v: float(by_year(m[v]).get(2020)) for v in ["USO", "USL", "DBO"]} | {"WTI_spot": float(by_year(spot["WTI"].dropna()).get(2020))},
        "2026_ytd": {v: float(by_year(m[v]).get(2026)) for v in ["USO", "USL", "DBO", "UNG", "UNL"]} | {"WTI_spot": float(by_year(spot["WTI"].dropna()).get(2026)), "HH_spot": float(by_year(spot["HH"].dropna()).get(2026))},
    }

    # ---- figures
    F = out / "figures"
    st = cfg["oil"]["start"]
    fig_growth({"WTI": spot["WTI"].loc[st:], "USO": m.USO.loc[st:], "USL": m.USL.loc[st:], "DBO": m.DBO.loc[st:]},
               "Oil: what $1 became, January 2008 to October 2026", F / "growth_oil.png", spot_label="WTI spot price (no collateral income)")
    fig_gap_by_year(gaps["USO"], gaps["USL"], F / "gap_by_year_oil.png")
    st = cfg["gas"]["start"]
    fig_growth({"HH": spot["HH"].loc[st:], "UNG": m.UNG.loc[st:], "UNL": m.UNL.loc[st:]},
               "Natural gas: what $1 became, February 2010 to October 2026", F / "growth_gas.png", spot_label="Henry Hub spot price")
    st = cfg["broad"]["start"]
    fig_growth({k: m[k].loc[st:] for k in ["GSG", "DBC", "USCI", "GLD"]},
               "Broad commodity funds and physical gold, September 2010 to October 2026", F / "growth_broad.png")
    fig_switch(curves, F / "switching_rule.png")

    (out / "metrics.json").write_text(json.dumps(M, indent=2, default=float))
    m.to_csv(out / "monthly_returns.csv", float_format="%.6f")
    print(json.dumps({k: M[k] for k in ("oil", "gas")}, indent=1, default=float)[:3000])
    return M


if __name__ == "__main__":
    main(*sys.argv[1:2])
