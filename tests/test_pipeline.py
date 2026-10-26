import numpy as np
import pandas as pd

from rollcost.pipeline import gap, switch_rule, cagr, by_year


def months(n, start="2020-01-31"):
    return pd.date_range(start, periods=n, freq="ME")


def test_gap_is_zero_when_fund_equals_spot_plus_bills():
    idx = months(24)
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(0, .08, 24), idx)
    b = pd.Series(0.002, idx)
    f = (1 + s) * (1 + b) - 1
    g, _ = gap(f, s, b)
    assert abs(g) < 1e-12


def test_gap_sign_for_a_steady_roll_drag():
    idx = months(36)
    s = pd.Series(0.0, idx); b = pd.Series(0.0, idx)
    f = pd.Series(-0.01, idx)  # loses 1% a month to the roll
    g, _ = gap(f, s, b)
    assert np.isclose(g, (0.99 ** 12) - 1)


def test_switch_rule_uses_only_past_information():
    idx = months(12)
    front = pd.Series(np.arange(12) / 100, idx)
    deferred = pd.Series(0.0, idx)
    sig_source = pd.Series([1, -1] * 6, idx, dtype=float)
    r1, s1 = switch_rule(front, deferred, sig_source, 1, 0)
    # change the future: the signal for month t must not depend on month t's own gap
    altered = sig_source.copy(); altered.iloc[6:] = -5.0
    r2, s2 = switch_rule(front, deferred, altered, 1, 0)
    assert s1.iloc[:7].equals(s2.iloc[:7])
    assert not s1.iloc[0]  # no history in the first month -> deferred


def test_switch_costs_charged_only_on_changes():
    idx = months(6)
    front = pd.Series(0.0, idx); deferred = pd.Series(0.0, idx)
    g = pd.Series([1, 1, 1, -1, -1, -1], idx, dtype=float)
    r, sig = switch_rule(front, deferred, g, 1, 10)
    assert np.isclose(-r.sum() * 1e4, 10 * sig.astype(int).diff().abs().fillna(0).sum())


def test_cagr_and_calendar_years():
    idx = months(24, "2021-01-31")
    r = pd.Series(0.01, idx)
    assert np.isclose(cagr(r), 1.01 ** 12 - 1)
    y = by_year(r)
    assert list(y.index) == [2021, 2022]
