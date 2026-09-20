"""Tests for bench.stats.

Every simulation uses a fixed seed through numpy.random.default_rng so results are
reproducible. Bootstrap sizes inside simulation loops are kept small (n_boot=400) to
bound the total runtime to well under a minute.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import integrate
from scipy import stats as sps

from bench import stats as S

METRIC = "correct"


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def rows_from_matrix(
    matrix: np.ndarray,
    condition: str,
    metric: str = METRIC,
    task: str = "verdict",
    status: str = "ok",
    prefix: str = "c",
) -> list[dict]:
    """One row per (case, rep) from a (n_cases, n_reps) matrix of grades."""
    rows = []
    for i, reps in enumerate(matrix):
        cid = f"{prefix}{i}"
        for r, v in enumerate(reps):
            rows.append(
                {
                    "case_id": cid,
                    "task": task,
                    "condition": condition,
                    "rep": r,
                    "status": status,
                    "grades": {metric: float(v)},
                }
            )
    return rows


def row(case_id: str, condition: str, value, rep: int = 0, status: str = "ok", task: str = "verdict") -> dict:
    return {
        "case_id": case_id,
        "task": task,
        "condition": condition,
        "rep": rep,
        "status": status,
        "grades": {METRIC: value},
    }


def beta_params(mean: float, concentration: float) -> tuple[float, float]:
    return mean * concentration, (1.0 - mean) * concentration


# --------------------------------------------------------------------------------------
# 1. Wilson
# --------------------------------------------------------------------------------------


class TestWilson:
    def test_zero_successes(self):
        p, lo, hi = S.wilson_interval(0, 10)
        assert p == 0.0
        assert lo == 0.0
        assert 0.0 < hi < 0.35

    def test_all_successes(self):
        p, lo, hi = S.wilson_interval(10, 10)
        assert p == 1.0
        assert hi == 1.0
        assert 0.65 < lo < 1.0

    def test_n_zero_is_nan(self):
        assert all(math.isnan(x) for x in S.wilson_interval(0, 0))

    def test_symmetry(self):
        _, lo, hi = S.wilson_interval(5, 10)
        assert abs((0.5 - lo) - (hi - 0.5)) < 1e-12
        _, lo3, hi3 = S.wilson_interval(3, 10)
        _, lo7, hi7 = S.wilson_interval(7, 10)
        assert abs(lo3 - (1.0 - hi7)) < 1e-12
        assert abs(hi3 - (1.0 - lo7)) < 1e-12

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            S.wilson_interval(11, 10)
        with pytest.raises(ValueError):
            S.wilson_interval(-1, 10)
        with pytest.raises(ValueError):
            S.wilson_interval(1, 10, alpha=1.5)

    @pytest.mark.parametrize("p", [0.1, 0.5, 0.9])
    def test_coverage(self, p):
        rng = np.random.default_rng(42)
        n, n_draws = 50, 3000
        draws = rng.binomial(n, p, size=n_draws)
        covered = 0
        for s in draws:
            _, lo, hi = S.wilson_interval(int(s), n)
            covered += lo <= p <= hi
        coverage = covered / n_draws
        assert 0.93 <= coverage <= 0.985, coverage


# --------------------------------------------------------------------------------------
# 2/3. case_scores and condition_estimate
# --------------------------------------------------------------------------------------


class TestConditionEstimate:
    def test_case_scores_filters_and_sorts(self):
        rows = [
            row("b", "H0", 1, rep=0),
            row("a", "H0", 0, rep=0),
            row("a", "H0", 1, rep=1),
            row("a", "H1", 1, rep=0),
            row("a", "H0", 1, rep=2, status="truncated"),
            row("a", "H0", None, rep=3),
            row("z", "H0", 1, rep=0, task="ingestion"),
        ]
        assert S.case_scores(rows, "H0", METRIC) == {"a": [0.0, 1.0], "b": [1.0], "z": [1.0]}
        assert S.case_scores(rows, "H0", METRIC, task="verdict") == {"a": [0.0, 1.0], "b": [1.0]}
        assert S.case_scores(rows, "H1", METRIC) == {"a": [1.0]}
        assert S.case_scores(rows, "G", METRIC) == {}

    def test_excluded_rows_counted_not_averaged(self):
        rows = [
            row("c0", "H0", 1, rep=0),
            row("c0", "H0", 1, rep=1),
            row("c0", "H0", 0, rep=2, status="truncated"),
            row("c1", "H0", 0, rep=0, status="refusal"),
        ]
        est = S.condition_estimate(rows, "H0", METRIC, n_boot=100)
        assert est["mean"] == 1.0
        assert est["n_cases"] == 1
        assert est["n_rows_ok"] == 2
        assert est["n_rows_excluded"] == 2
        assert est["n_reps_min"] == est["n_reps_max"] == 2

    def test_none_grades_skipped(self):
        rows = [
            row("c0", "H0", 1, rep=0),
            row("c0", "H0", None, rep=1),
            row("c1", "H0", None, rep=0),
            row("c2", "H0", 0.5, rep=0),
        ]
        est = S.condition_estimate(rows, "H0", METRIC, n_boot=100)
        assert est["n_cases"] == 2
        assert est["mean"] == pytest.approx(0.75)
        assert est["n_rows_ok"] == 2
        assert est["n_rows_na"] == 2
        assert est["n_rows_excluded"] == 0
        assert est["binary"] is False
        assert est["wilson_lo"] is None and est["wilson_hi"] is None

    def test_binary_metric_gets_wilson(self):
        rows = rows_from_matrix(np.array([[1, 1, 0], [0, 1, 1], [1, 1, 1]]), "H0")
        est = S.condition_estimate(rows, "H0", METRIC, n_boot=100)
        assert est["binary"] is True
        _, lo, hi = S.wilson_interval(7, 9)
        assert est["wilson_lo"] == pytest.approx(lo)
        assert est["wilson_hi"] == pytest.approx(hi)
        assert est["mean"] == pytest.approx(7 / 9)

    def test_empty_condition(self):
        est = S.condition_estimate([], "H0", METRIC, n_boot=10)
        assert est["n_cases"] == 0 and est["n_rows_ok"] == 0
        assert math.isnan(est["mean"]) and math.isnan(est["ci_lo"])
        assert est["wilson_lo"] is None

    def test_deterministic_seed(self):
        rng = np.random.default_rng(3)
        rows = rows_from_matrix((rng.random((30, 4)) < 0.6).astype(float), "H0")
        a = S.condition_estimate(rows, "H0", METRIC, n_boot=500, seed=7)
        b = S.condition_estimate(rows, "H0", METRIC, n_boot=500, seed=7)
        c = S.condition_estimate(rows, "H0", METRIC, n_boot=500, seed=8)
        assert (a["ci_lo"], a["ci_hi"]) == (b["ci_lo"], b["ci_hi"])
        assert (a["ci_lo"], a["ci_hi"]) != (c["ci_lo"], c["ci_hi"])
        assert a["ci_lo"] <= a["mean"] <= a["ci_hi"]

    def test_bootstrap_coverage_and_bias(self):
        """60 cases x 5 reps, per-case p ~ Beta(mean 0.6, concentration 4)."""
        rng = np.random.default_rng(2024)
        n_sim, n_cases, n_reps, true_mean = 2000, 60, 5, 0.6
        a, b = beta_params(true_mean, 4.0)
        p_case = rng.beta(a, b, size=(n_sim, n_cases))
        grades = (rng.random((n_sim, n_cases, n_reps)) < p_case[..., None]).astype(float)
        covered = 0
        estimates = np.empty(n_sim)
        for i in range(n_sim):
            rows = rows_from_matrix(grades[i], "H0")
            est = S.condition_estimate(rows, "H0", METRIC, n_boot=400, seed=i)
            estimates[i] = est["mean"]
            covered += est["ci_lo"] <= true_mean <= est["ci_hi"]
        coverage = covered / n_sim
        assert 0.92 <= coverage <= 0.98, coverage
        assert abs(estimates.mean() - true_mean) < 0.01


# --------------------------------------------------------------------------------------
# 4. paired_diff
# --------------------------------------------------------------------------------------


class TestPairedDiff:
    def test_identical_conditions(self):
        rng = np.random.default_rng(5)
        m = (rng.random((40, 3)) < 0.5).astype(float)
        rows = rows_from_matrix(m, "H0") + rows_from_matrix(m, "H1")
        res = S.paired_diff(rows, "H0", "H1", METRIC, n_boot=500)
        assert res["diff"] == 0.0
        assert res["ci_lo"] == 0.0 and res["ci_hi"] == 0.0
        assert res["p_boot"] == 1.0
        assert res["n_cases"] == 40
        assert res["mcnemar"]["p"] == 1.0

    def test_only_shared_cases_used(self):
        rows = [
            row("a", "H0", 1),
            row("a", "H1", 0),
            row("b", "H0", 1),
            row("b", "H1", 1),
            row("only_h0", "H0", 0),
            row("only_h1", "H1", 1),
        ]
        res = S.paired_diff(rows, "H0", "H1", METRIC, n_boot=200)
        assert res["n_cases"] == 2
        assert res["diff"] == pytest.approx(0.5)
        assert res["mean_a"] == pytest.approx(1.0)
        assert res["mean_b"] == pytest.approx(0.5)

    def test_no_shared_cases(self):
        rows = [row("a", "H0", 1), row("b", "H1", 1)]
        res = S.paired_diff(rows, "H0", "H1", METRIC, n_boot=50)
        assert res["n_cases"] == 0
        assert math.isnan(res["diff"]) and math.isnan(res["p_boot"])

    def test_continuous_metric_has_no_mcnemar(self):
        rows = [row("a", "H0", 0.4), row("a", "H1", 0.9), row("b", "H0", 0.2), row("b", "H1", 0.3)]
        res = S.paired_diff(rows, "H1", "H0", METRIC, n_boot=100)
        assert res["mcnemar"] is None
        assert res["diff"] == pytest.approx(0.3)

    def test_paired_bootstrap_coverage_and_bias(self):
        """A: p ~ Beta(mean 0.6, conc 4); B: clip(p + 0.15). 60 cases x 5 reps.

        Clipping at 1 lowers the true marginal difference below the nominal 0.15, so
        the truth is computed exactly by quadrature over the Beta density.
        """
        rng = np.random.default_rng(99)
        n_sim, n_cases, n_reps, shift = 2000, 60, 5, 0.15
        a, b = beta_params(0.6, 4.0)
        excess, _ = integrate.quad(lambda p: max(p + shift - 1.0, 0.0) * sps.beta.pdf(p, a, b), 0.0, 1.0)
        true_diff = shift - excess
        assert 0.14 < true_diff < 0.15

        p_case = rng.beta(a, b, size=(n_sim, n_cases))
        p_b = np.minimum(p_case + shift, 1.0)
        grades_a = (rng.random((n_sim, n_cases, n_reps)) < p_case[..., None]).astype(float)
        grades_b = (rng.random((n_sim, n_cases, n_reps)) < p_b[..., None]).astype(float)
        covered = 0
        diffs = np.empty(n_sim)
        for i in range(n_sim):
            rows = rows_from_matrix(grades_a[i], "A") + rows_from_matrix(grades_b[i], "B")
            res = S.paired_diff(rows, "B", "A", METRIC, n_boot=400, seed=i)
            diffs[i] = res["diff"]
            covered += res["ci_lo"] <= true_diff <= res["ci_hi"]
        coverage = covered / n_sim
        assert 0.92 <= coverage <= 0.98, coverage
        assert abs(diffs.mean() - true_diff) < 0.01

    def test_detects_real_effect(self):
        rng = np.random.default_rng(7)
        n_sim, n_cases, n_reps = 200, 100, 5
        a, b = beta_params(0.6, 4.0)
        p_case = rng.beta(a, b, size=(n_sim, n_cases))
        p_b = np.minimum(p_case + 0.15, 1.0)
        grades_a = (rng.random((n_sim, n_cases, n_reps)) < p_case[..., None]).astype(float)
        grades_b = (rng.random((n_sim, n_cases, n_reps)) < p_b[..., None]).astype(float)
        excludes_zero = 0
        for i in range(n_sim):
            rows = rows_from_matrix(grades_a[i], "A") + rows_from_matrix(grades_b[i], "B")
            res = S.paired_diff(rows, "B", "A", METRIC, n_boot=400, seed=i)
            excludes_zero += res["ci_lo"] > 0.0
            assert res["mcnemar"] is not None
        assert excludes_zero / n_sim >= 0.95


# --------------------------------------------------------------------------------------
# 5. McNemar
# --------------------------------------------------------------------------------------


class TestMcNemar:
    @staticmethod
    def _rows(b: int, c: int, both_correct: int = 5, both_wrong: int = 3) -> list[dict]:
        rows = []
        i = 0
        for _ in range(b):  # A correct (2 of 3), B wrong (1 of 3)
            rows += [row(f"c{i}", "A", v, rep=r) for r, v in enumerate([1, 1, 0])]
            rows += [row(f"c{i}", "B", v, rep=r) for r, v in enumerate([0, 0, 1])]
            i += 1
        for _ in range(c):
            rows += [row(f"c{i}", "A", v, rep=r) for r, v in enumerate([0, 1, 0])]
            rows += [row(f"c{i}", "B", v, rep=r) for r, v in enumerate([1, 1, 1])]
            i += 1
        for _ in range(both_correct):
            rows += [row(f"c{i}", "A", 1), row(f"c{i}", "B", 1)]
            i += 1
        for _ in range(both_wrong):
            rows += [row(f"c{i}", "A", 0), row(f"c{i}", "B", 0)]
            i += 1
        return rows

    def test_known_counts(self):
        res = S.mcnemar_exact(self._rows(8, 2), "A", "B", METRIC)
        assert (res["b"], res["c"]) == (8, 2)
        assert res["n_cases"] == 18
        assert res["both_correct"] == 5 and res["both_wrong"] == 3
        assert res["p"] == pytest.approx(sps.binomtest(2, 10, 0.5).pvalue)

    def test_balanced_discordance_is_one(self):
        res = S.mcnemar_exact(self._rows(4, 4), "A", "B", METRIC)
        assert res["p"] == 1.0

    def test_no_discordance_is_one(self):
        res = S.mcnemar_exact(self._rows(0, 0), "A", "B", METRIC)
        assert (res["b"], res["c"], res["p"]) == (0, 0, 1.0)

    def test_tie_counts_as_zero(self):
        rows = [row("x", "A", 1, rep=0), row("x", "A", 0, rep=1), row("x", "B", 1, rep=0), row("x", "B", 1, rep=1)]
        res = S.mcnemar_exact(rows, "A", "B", METRIC)
        assert (res["b"], res["c"]) == (0, 1)

    def test_aggregate_modes(self):
        rows = [row("x", "A", 1, rep=0), row("x", "A", 0, rep=1), row("x", "B", 0, rep=0), row("x", "B", 0, rep=1)]
        assert S.mcnemar_exact(rows, "A", "B", METRIC, aggregate="any")["b"] == 1
        assert S.mcnemar_exact(rows, "A", "B", METRIC, aggregate="all")["b"] == 0
        with pytest.raises(ValueError):
            S.mcnemar_exact(rows, "A", "B", METRIC, aggregate="median")

    def test_rejects_continuous(self):
        rows = [row("x", "A", 0.5), row("x", "B", 1)]
        with pytest.raises(ValueError):
            S.mcnemar_exact(rows, "A", "B", METRIC)


# --------------------------------------------------------------------------------------
# 6. pass_k
# --------------------------------------------------------------------------------------


class TestPassK:
    def test_analytic(self):
        matrix = np.array([[1, 1, 1, 0, 0]] * 12)
        rows = rows_from_matrix(matrix, "H0")
        assert S.pass_k(rows, "H0", METRIC, 2, n_boot=100)["estimate"] == pytest.approx(0.3)
        assert S.pass_k(rows, "H0", METRIC, 4, n_boot=100)["estimate"] == 0.0
        assert S.pass_k(rows, "H0", METRIC, 1, n_boot=100)["estimate"] == pytest.approx(0.6)
        res = S.pass_k(rows, "H0", METRIC, 5, n_boot=100)
        assert res["estimate"] == 0.0 and res["n_cases"] == 12 and res["n_cases_skipped"] == 0

    def test_skips_short_cases(self):
        rows = rows_from_matrix(np.array([[1, 1, 1]]), "H0") + [row("short", "H0", 1)]
        res = S.pass_k(rows, "H0", METRIC, 2, n_boot=50)
        assert res["n_cases"] == 1 and res["n_cases_skipped"] == 1
        assert res["estimate"] == 1.0
        assert S.pass_k(rows, "H0", METRIC, 2, n_boot=50, mode="any")["estimate"] == 1.0

    def test_pass_at_k_any_mode(self):
        rows = rows_from_matrix(np.array([[1, 0, 0, 0]]), "H0")
        # 1 - comb(3, 2) / comb(4, 2) = 1 - 3/6
        assert S.pass_k(rows, "H0", METRIC, 2, n_boot=50, mode="any")["estimate"] == pytest.approx(0.5)

    def test_invalid_k(self):
        rows = rows_from_matrix(np.array([[1, 0]]), "H0")
        with pytest.raises(ValueError):
            S.pass_k(rows, "H0", METRIC, 0)
        with pytest.raises(ValueError):
            S.pass_k(rows, "H0", METRIC, 2, mode="most")

    def test_unbiased_by_simulation(self):
        rng = np.random.default_rng(11)
        p, R, k, n_cases = 0.7, 6, 3, 3000
        matrix = (rng.random((n_cases, R)) < p).astype(float)
        res = S.pass_k(rows_from_matrix(matrix, "H0"), "H0", METRIC, k, n_boot=500)
        assert abs(res["estimate"] - p**k) < 0.02
        assert res["ci_lo"] <= res["estimate"] <= res["ci_hi"]
        assert res["n_cases"] == n_cases


# --------------------------------------------------------------------------------------
# 7. Cohen's kappa
# --------------------------------------------------------------------------------------


class TestKappa:
    def test_identical_labels(self):
        labels = ["pass", "warn", "breach", "pass", "hard_block", "warn"]
        res = S.cohens_kappa(labels, list(labels), n_boot=200)
        assert res["kappa"] == 1.0
        assert res["po"] == 1.0
        assert res["n"] == 6

    def test_independent_labels_near_zero(self):
        rng = np.random.default_rng(21)
        a = rng.integers(0, 4, size=4000)
        b = rng.integers(0, 4, size=4000)
        res = S.cohens_kappa(list(a), list(b), n_boot=2000)
        assert abs(res["kappa"]) < 0.05
        assert res["ci_lo"] < 0.0 < res["ci_hi"]
        assert abs(res["pe"] - 0.25) < 0.02

    def test_hand_computed_2x2(self):
        # n11=5, n10=1, n01=2, n00=2 -> po=7/10, pa=6/10, pb=7/10
        a = [1, 1, 1, 1, 1, 1, 0, 0, 0, 0]
        b = [1, 1, 1, 1, 1, 0, 1, 1, 0, 0]
        po = 7 / 10
        pe = 0.6 * 0.7 + 0.4 * 0.3
        res = S.cohens_kappa(a, b, n_boot=100)
        assert abs(res["kappa"] - (po - pe) / (1 - pe)) < 1e-9
        assert abs(res["po"] - po) < 1e-12
        assert abs(res["pe"] - pe) < 1e-12

    def test_length_mismatch_and_empty(self):
        with pytest.raises(ValueError):
            S.cohens_kappa([1, 2], [1])
        res = S.cohens_kappa([], [], n_boot=10)
        assert res["n"] == 0 and math.isnan(res["kappa"])


# --------------------------------------------------------------------------------------
# 8. Holm-Bonferroni
# --------------------------------------------------------------------------------------


class TestHolm:
    def test_manual_example(self):
        # sorted: 0.01*3=0.03, 0.03*2=0.06, 0.04*1=0.04 -> running max lifts it to 0.06
        assert S.holm_bonferroni([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])

    def test_largest_may_equal_raw(self):
        assert S.holm_bonferroni([0.01, 0.02, 0.5]) == pytest.approx([0.03, 0.04, 0.5])

    def test_capped_and_monotone(self):
        assert S.holm_bonferroni([0.5, 0.6]) == [1.0, 1.0]
        p = [0.2, 0.001, 0.03, 0.03, 0.9]
        adj = S.holm_bonferroni(p)
        order = np.argsort(p)
        assert all(adj[order[i]] <= adj[order[i + 1]] for i in range(len(p) - 1))
        assert all(0.0 <= x <= 1.0 for x in adj)
        assert all(a >= r for a, r in zip(adj, p))

    def test_single_and_empty(self):
        assert S.holm_bonferroni([0.2]) == [0.2]
        assert S.holm_bonferroni([]) == []
        with pytest.raises(ValueError):
            S.holm_bonferroni([0.1, 1.5])


# --------------------------------------------------------------------------------------
# 9. noise_floor
# --------------------------------------------------------------------------------------


class TestNoiseFloor:
    def test_known_values(self):
        assert S.noise_floor(200, 5, rho=0.0) == pytest.approx(0.031, abs=0.001)
        assert S.noise_floor(200, 5, rho=1.0) == pytest.approx(0.069, abs=0.001)
        # rho=1 collapses to n_eff = n_cases: same as one rep per case
        assert S.noise_floor(200, 5, rho=1.0) == pytest.approx(S.noise_floor(200, 1))

    def test_monotone_in_rho(self):
        values = [S.noise_floor(200, 5, rho=r) for r in np.linspace(0.0, 1.0, 11)]
        assert all(values[i] < values[i + 1] for i in range(len(values) - 1))

    def test_validation(self):
        with pytest.raises(ValueError):
            S.noise_floor(0, 5)
        with pytest.raises(ValueError):
            S.noise_floor(10, 5, rho=1.2)


# --------------------------------------------------------------------------------------
# 10. mde_paired
# --------------------------------------------------------------------------------------


class TestMDE:
    def test_fast_mode_range_and_ordering(self):
        mde_200 = S.mde_paired(200, 5, 0.7, fast=True)
        mde_400 = S.mde_paired(400, 5, 0.7, fast=True)
        mde_100 = S.mde_paired(100, 5, 0.7, fast=True)
        assert 0.02 <= mde_200 <= 0.20
        assert mde_400 < mde_100
        assert mde_400 <= mde_200 <= mde_100

    def test_bootstrap_mode_agrees_with_fast(self):
        fast = S.mde_paired(200, 5, 0.7, fast=True, n_sim=1000)
        boot = S.mde_paired(200, 5, 0.7, fast=False, n_sim=1000, n_boot_inner=500)
        assert abs(fast - boot) <= 0.02

    def test_null_rejection_rate_near_alpha(self):
        size = S.simulate_paired_power(100, 5, 0.7, 0.0, n_sim=1000, fast=True)
        assert 0.02 <= size <= 0.09

    def test_validation(self):
        with pytest.raises(ValueError):
            S.mde_paired(1, 5, 0.7, fast=True)
        with pytest.raises(ValueError):
            S.mde_paired(100, 5, 1.7, fast=True)
        with pytest.raises(ValueError):
            S.mde_paired(100, 5, 0.7, power=1.0, fast=True)


# --------------------------------------------------------------------------------------
# 11/12. summarize and to_markdown_table
# --------------------------------------------------------------------------------------


class TestSummary:
    @staticmethod
    def _rows() -> list[dict]:
        rng = np.random.default_rng(13)
        rows = []
        for cond, p in (("H0", 0.5), ("H1", 0.7)):
            m = (rng.random((20, 3)) < p).astype(float)
            rows += rows_from_matrix(m, cond)
            rows += rows_from_matrix(rng.random((20, 3)), cond, metric="citation_f1")
        rows.append(row("c0", "H0", 0, rep=9, status="truncated"))
        rows.append(row("c1", "H1", 0, rep=9, status="refusal"))
        rows.append(row("c2", "H1", 0, rep=9, status="truncated"))
        return rows

    def test_summarize_structure(self):
        rows = self._rows()
        metrics, conditions = [METRIC, "citation_f1"], ["H0", "H1"]
        summary = S.summarize(rows, metrics, conditions)
        assert set(summary) == {METRIC, "citation_f1", "_excluded"}
        assert summary["_excluded"] == {"H0": 1, "H1": 2}
        for metric in metrics:
            for cond in conditions:
                est = summary[metric][cond]
                assert est["n_cases"] == 20
                assert est["n_boot"] == 2000
                assert est["ci_lo"] <= est["mean"] <= est["ci_hi"]
        assert summary[METRIC]["H0"]["n_rows_excluded"] == 1
        assert summary[METRIC]["H1"]["n_rows_excluded"] == 2
        assert summary[METRIC]["H0"]["binary"] is True
        assert summary["citation_f1"]["H0"]["binary"] is False

    def test_markdown_table(self):
        rows = self._rows()
        metrics, conditions = [METRIC, "citation_f1"], ["H0", "H1", "G"]
        summary = S.summarize(rows, metrics, conditions, n_boot=200)
        table = S.to_markdown_table(summary, metrics, conditions)
        lines = table.splitlines()
        assert lines[0] == "| metric | H0 | H1 | G |"
        assert lines[1] == "|---|---|---|---|"
        assert len(lines) == 2 + len(metrics)
        for line, metric in zip(lines[2:], metrics):
            assert line.startswith(f"| {metric} |")
            cells = [c.strip() for c in line.strip("|").split("|")][1:]
            assert len(cells) == 3
            assert cells[2] == "n/a (n=0)"
            assert "[" in cells[0] and "(n=20)" in cells[0]
        est = summary[METRIC]["H0"]
        assert f"{est['mean']:.3f} [{est['ci_lo']:.3f}, {est['ci_hi']:.3f}] (n=20)" in table
