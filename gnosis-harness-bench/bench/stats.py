"""Statistics for the harness bench.

Every public function accepts a plain list of result rows as written to the results
JSONL. A row is a dict shaped like ``bench.schema.ResultRow``::

    {"case_id": str, "task": "ingestion" | "verdict", "condition": str, "rep": int,
     "status": "ok" | "truncated" | "refusal", "grades": {metric_name: value}, ...}

where ``value`` is 0/1 for a binary metric, a float in [0, 1] for a continuous metric,
or ``None`` when the metric does not apply to that case.

Conventions shared by every estimator in this module:

* The unit of inference is the *case*, not the row. A case is graded ``n_reps`` times
  per condition and its reps are correlated (same prompt, same documents), so the
  standard error is estimated by resampling cases with replacement and keeping all of
  a case's reps together. This is a cluster bootstrap with cases as clusters and it
  assumes cases are exchangeable draws from the population of cases we care about.
* Rows whose ``status`` is not ``"ok"`` are never used in a quality estimate. Their
  count is reported separately so truncation and refusal rates stay visible.
* A ``None`` grade means "not applicable" and is skipped. It is never treated as 0.
* All randomness goes through ``numpy.random.default_rng(seed)`` created inside the
  function that needs it. There is no module-level state.
"""
from __future__ import annotations

import math
from typing import Any, Hashable, Iterable, Sequence

import numpy as np
from scipy import stats as _sps

Row = dict[str, Any]

# Upper bound on the number of elements materialised by one bootstrap chunk. Keeps
# peak memory around a few tens of megabytes regardless of n_boot and n_cases.
_MAX_CHUNK_ELEMENTS = 4_000_000

_NAN = float("nan")


# --------------------------------------------------------------------------------------
# Row selection helpers
# --------------------------------------------------------------------------------------


def _select_rows(rows: Iterable[Row], condition: str, task: str | None) -> list[Row]:
    """Rows for one condition (and task, if given), regardless of status."""
    out = []
    for r in rows:
        if r.get("condition") != condition:
            continue
        if task is not None and r.get("task") != task:
            continue
        out.append(r)
    return out


def _grade(row: Row, metric: str) -> float | None:
    """The row's grade for ``metric`` as a float, or None if missing / not applicable."""
    grades = row.get("grades") or {}
    v = grades.get(metric)
    if v is None:
        return None
    return float(v)


def _count_excluded(rows: Iterable[Row], condition: str, task: str | None) -> int:
    """Number of rows for the condition whose status is not ``"ok"``."""
    return sum(1 for r in _select_rows(rows, condition, task) if r.get("status") != "ok")


def _is_binary(values: np.ndarray) -> bool:
    """True when there is at least one value and every value is exactly 0 or 1."""
    return values.size > 0 and bool(np.isin(values, (0.0, 1.0)).all())


def _z(alpha: float) -> float:
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    return float(_sps.norm.ppf(1.0 - alpha / 2.0))


# --------------------------------------------------------------------------------------
# Bootstrap core
# --------------------------------------------------------------------------------------


def _bootstrap_means(values: np.ndarray, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """``n_boot`` means of ``values`` resampled with replacement (one entry per case).

    Resampling the vector of per-case statistics with replacement is exactly the
    cluster bootstrap that resamples case_ids and keeps every rep of a case together,
    because the statistic we bootstrap is always a mean of per-case quantities.
    Work is chunked so that at most ``_MAX_CHUNK_ELEMENTS`` indices exist at once.
    """
    n = int(values.shape[0])
    out = np.empty(n_boot, dtype=float)
    if n == 0 or n_boot == 0:
        out[:] = _NAN
        return out
    chunk = max(1, _MAX_CHUNK_ELEMENTS // n)
    for start in range(0, n_boot, chunk):
        m = min(chunk, n_boot - start)
        idx = rng.integers(0, n, size=(m, n))
        out[start : start + m] = values[idx].mean(axis=1)
    return out


def _percentile_ci(boot: np.ndarray, alpha: float) -> tuple[float, float]:
    """Percentile interval of a bootstrap distribution; (nan, nan) if empty or all nan."""
    if boot.size == 0 or np.isnan(boot).all():
        return (_NAN, _NAN)
    lo, hi = np.percentile(boot, [100.0 * alpha / 2.0, 100.0 * (1.0 - alpha / 2.0)])
    return (float(lo), float(hi))


# --------------------------------------------------------------------------------------
# 1. Wilson interval
# --------------------------------------------------------------------------------------


def wilson_interval(successes: int, n: int, alpha: float = 0.05) -> tuple[float, float, float]:
    """Wilson score interval for a binomial proportion.

    Returns ``(p_hat, lo, hi)`` where ``p_hat = successes / n`` and ``[lo, hi]`` is the
    Wilson interval at confidence ``1 - alpha``. The interval is the set of p for which
    the normal-approximation score test does not reject, so unlike the Wald interval it
    stays inside [0, 1], has non-zero width at 0 and n successes, and keeps close to
    nominal coverage for small n. The endpoints are exactly 0 when ``successes == 0``
    and exactly 1 when ``successes == n``.

    Assumes the ``n`` trials are independent Bernoulli(p). Rows from the same case are
    not independent, so on pooled benchmark rows this interval is anti-conservative and
    should be read as a floor on the uncertainty; the case-level bootstrap in
    :func:`condition_estimate` is the primary interval.

    ``n == 0`` returns ``(nan, nan, nan)``.
    """
    if n < 0 or successes < 0 or successes > n:
        raise ValueError(f"need 0 <= successes <= n, got successes={successes}, n={n}")
    if n == 0:
        return (_NAN, _NAN, _NAN)
    z = _z(alpha)
    p_hat = successes / n
    z2n = z * z / n
    denom = 1.0 + z2n
    centre = (p_hat + z2n / 2.0) / denom
    half = z * math.sqrt(p_hat * (1.0 - p_hat) / n + z2n / (4.0 * n)) / denom
    lo = 0.0 if successes == 0 else max(0.0, centre - half)
    hi = 1.0 if successes == n else min(1.0, centre + half)
    return (float(p_hat), float(lo), float(hi))


# --------------------------------------------------------------------------------------
# 2. Per-case scores
# --------------------------------------------------------------------------------------


def case_scores(
    rows: Iterable[Row], condition: str, metric: str, task: str | None = None
) -> dict[str, list[float]]:
    """Map ``case_id`` to the list of rep values for one condition and metric.

    Only rows with ``status == "ok"`` and a non-None grade for ``metric`` contribute.
    Rep values keep the order in which their rows appear. Cases are returned in sorted
    ``case_id`` order so downstream bootstraps do not depend on row order.
    """
    scores: dict[str, list[float]] = {}
    for r in _select_rows(rows, condition, task):
        if r.get("status") != "ok":
            continue
        v = _grade(r, metric)
        if v is None:
            continue
        scores.setdefault(str(r.get("case_id")), []).append(v)
    return {cid: scores[cid] for cid in sorted(scores)}


def _case_means(scores: dict[str, list[float]]) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Sorted case ids, per-case mean, and per-case rep count."""
    ids = list(scores)
    means = np.array([float(np.mean(scores[c])) for c in ids], dtype=float)
    counts = np.array([len(scores[c]) for c in ids], dtype=int)
    return ids, means, counts


# --------------------------------------------------------------------------------------
# 3. Condition estimate
# --------------------------------------------------------------------------------------


def condition_estimate(
    rows: Iterable[Row],
    condition: str,
    metric: str,
    task: str | None = None,
    n_boot: int = 10000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Point estimate and interval for one metric under one condition.

    Estimator: the mean over cases of each case's mean over its ok reps. Every case
    gets equal weight regardless of how many reps it has, which is what we want when a
    case is the unit of interest and rep counts differ only because of exclusions.

    Interval: case-level percentile bootstrap. Cases are resampled with replacement
    ``n_boot`` times (all reps of a case travel together) and the estimator is
    recomputed on each resample; ``ci_lo``/``ci_hi`` are the ``alpha/2`` and
    ``1 - alpha/2`` quantiles. Assumes cases are exchangeable; does not assume anything
    about the within-case rep distribution. With fewer than about 20 cases the
    percentile interval tends to be a little too narrow.

    When the metric is binary (every pooled value is exactly 0 or 1) ``wilson_lo`` and
    ``wilson_hi`` give the Wilson interval on the pooled rows, which ignores the case
    clustering and is reported only as a reference. Otherwise they are ``None``.

    Keys: ``condition``, ``metric``, ``task``, ``mean``, ``n_cases``, ``n_reps_min``,
    ``n_reps_max``, ``n_rows_ok`` (ok rows with a grade, the rows that fed the mean),
    ``n_rows_na`` (ok rows whose grade is None), ``n_rows_excluded`` (rows with
    status != ok), ``ci_lo``, ``ci_hi``, ``wilson_lo``, ``wilson_hi``, ``binary``,
    ``alpha``, ``n_boot``. Empty inputs give ``nan`` estimates and zero counts.
    """
    rows = list(rows)
    selected = _select_rows(rows, condition, task)
    n_excluded = sum(1 for r in selected if r.get("status") != "ok")
    n_na = sum(1 for r in selected if r.get("status") == "ok" and _grade(r, metric) is None)

    scores = case_scores(selected, condition, metric, task)
    _, means, counts = _case_means(scores)
    pooled = np.array([v for vals in scores.values() for v in vals], dtype=float)
    n_cases = int(means.shape[0])

    if n_cases:
        mean = float(means.mean())
        rng = np.random.default_rng(seed)
        ci_lo, ci_hi = _percentile_ci(_bootstrap_means(means, n_boot, rng), alpha)
    else:
        mean, ci_lo, ci_hi = _NAN, _NAN, _NAN

    binary = _is_binary(pooled)
    if binary:
        _, w_lo, w_hi = wilson_interval(int(round(pooled.sum())), int(pooled.size), alpha)
    else:
        w_lo = w_hi = None

    return {
        "condition": condition,
        "metric": metric,
        "task": task,
        "mean": mean,
        "n_cases": n_cases,
        "n_reps_min": int(counts.min()) if n_cases else 0,
        "n_reps_max": int(counts.max()) if n_cases else 0,
        "n_rows_ok": int(pooled.size),
        "n_rows_na": int(n_na),
        "n_rows_excluded": int(n_excluded),
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "wilson_lo": w_lo,
        "wilson_hi": w_hi,
        "binary": binary,
        "alpha": alpha,
        "n_boot": n_boot,
    }


# --------------------------------------------------------------------------------------
# 4. Paired difference
# --------------------------------------------------------------------------------------


def _shared_case_means(
    rows: list[Row], cond_a: str, cond_b: str, metric: str, task: str | None
) -> tuple[list[str], dict[str, list[float]], dict[str, list[float]]]:
    scores_a = case_scores(rows, cond_a, metric, task)
    scores_b = case_scores(rows, cond_b, metric, task)
    shared = sorted(set(scores_a) & set(scores_b))
    return shared, scores_a, scores_b


def paired_diff(
    rows: Iterable[Row],
    cond_a: str,
    cond_b: str,
    metric: str,
    task: str | None = None,
    n_boot: int = 10000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Paired difference ``cond_a - cond_b`` on the cases both conditions graded.

    Estimator: for each shared case, ``mean_a - mean_b`` over that case's ok reps;
    ``diff`` is the mean of these per-case differences. Pairing on the case removes
    between-case difficulty variation from the comparison, which is why it is far more
    powerful than comparing two independent condition means.

    Interval: paired case-level percentile bootstrap. Shared cases are resampled with
    replacement and ``diff`` recomputed on each resample.

    ``p_boot`` is a two-sided bootstrap p-value: twice the fraction of bootstrap
    differences on the far side of zero (inclusive of zero) from the point estimate,
    capped at 1. Formally ``min(1, 2 * min(P*(diff* <= 0), P*(diff* >= 0)))``. Its
    resolution is ``2 / n_boot`` and it is 0 when no resample crosses zero. It is a
    percentile-bootstrap p-value, so it inherits the same small-sample optimism as the
    interval. Prefer ``mcnemar`` for a formally exact test on binary metrics.

    ``mcnemar`` holds :func:`mcnemar_exact` when the metric is binary on the shared
    cases, else ``None``.

    Keys: ``cond_a``, ``cond_b``, ``metric``, ``task``, ``diff``, ``mean_a``,
    ``mean_b``, ``ci_lo``, ``ci_hi``, ``p_boot``, ``n_cases``, ``mcnemar``, ``alpha``,
    ``n_boot``. With no shared cases the estimates are ``nan``.
    """
    rows = list(rows)
    shared, scores_a, scores_b = _shared_case_means(rows, cond_a, cond_b, metric, task)
    n_cases = len(shared)
    mean_a = np.array([np.mean(scores_a[c]) for c in shared], dtype=float)
    mean_b = np.array([np.mean(scores_b[c]) for c in shared], dtype=float)
    d = mean_a - mean_b

    if n_cases:
        diff = float(d.mean())
        rng = np.random.default_rng(seed)
        boot = _bootstrap_means(d, n_boot, rng)
        ci_lo, ci_hi = _percentile_ci(boot, alpha)
        if boot.size:
            frac_le = float(np.mean(boot <= 0.0))
            frac_ge = float(np.mean(boot >= 0.0))
            p_boot = min(1.0, 2.0 * min(frac_le, frac_ge))
        else:
            p_boot = _NAN
        ma, mb = float(mean_a.mean()), float(mean_b.mean())
    else:
        diff, ci_lo, ci_hi, p_boot, ma, mb = _NAN, _NAN, _NAN, _NAN, _NAN, _NAN

    pooled = np.array(
        [v for c in shared for v in scores_a[c]] + [v for c in shared for v in scores_b[c]],
        dtype=float,
    )
    mcnemar = mcnemar_exact(rows, cond_a, cond_b, metric, task) if _is_binary(pooled) else None

    return {
        "cond_a": cond_a,
        "cond_b": cond_b,
        "metric": metric,
        "task": task,
        "diff": diff,
        "mean_a": ma,
        "mean_b": mb,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "p_boot": p_boot,
        "n_cases": n_cases,
        "mcnemar": mcnemar,
        "alpha": alpha,
        "n_boot": n_boot,
    }


# --------------------------------------------------------------------------------------
# 5. Exact McNemar
# --------------------------------------------------------------------------------------


def _collapse_binary(values: Sequence[float], aggregate: str) -> int:
    """Collapse one case's binary reps to a single 0/1 label."""
    arr = np.asarray(values, dtype=float)
    if not _is_binary(arr):
        raise ValueError("mcnemar_exact needs a binary metric (every value 0 or 1)")
    n_correct = int(arr.sum())
    n = int(arr.size)
    if aggregate == "majority":
        return 1 if 2 * n_correct > n else 0  # ties count as 0
    if aggregate == "all":
        return 1 if n_correct == n else 0
    if aggregate == "any":
        return 1 if n_correct > 0 else 0
    raise ValueError(f"aggregate must be 'majority', 'all' or 'any', got {aggregate!r}")


def mcnemar_exact(
    rows: Iterable[Row],
    cond_a: str,
    cond_b: str,
    metric: str,
    task: str | None = None,
    aggregate: str = "majority",
) -> dict[str, Any]:
    """Exact McNemar test that two conditions have the same per-case pass rate.

    Each shared case's reps under a condition are collapsed to one label. With
    ``aggregate="majority"`` (default) the label is 1 when strictly more than half of
    the reps are correct, so ties count as 0. ``"all"`` requires every rep correct and
    ``"any"`` requires at least one. The 2x2 table of labels then gives the discordant
    counts ``b`` (A correct, B wrong) and ``c`` (A wrong, B correct).

    Under the null hypothesis of equal marginal pass rates each discordant case is
    equally likely to fall either way, so ``min(b, c) ~ Binomial(b + c, 1/2)`` and
    ``p`` is the exact two-sided binomial p-value (``scipy.stats.binomtest``). Only
    discordant cases carry information; concordant counts are reported for context.
    ``b + c == 0`` gives ``p = 1.0``. Assumes cases are independent.

    Keys: ``b``, ``c``, ``p``, ``n_cases``, ``both_correct``, ``both_wrong``,
    ``aggregate``.
    """
    rows = list(rows)
    shared, scores_a, scores_b = _shared_case_means(rows, cond_a, cond_b, metric, task)
    b = c = both_correct = both_wrong = 0
    for cid in shared:
        la = _collapse_binary(scores_a[cid], aggregate)
        lb = _collapse_binary(scores_b[cid], aggregate)
        if la == 1 and lb == 0:
            b += 1
        elif la == 0 and lb == 1:
            c += 1
        elif la == 1:
            both_correct += 1
        else:
            both_wrong += 1
    n_disc = b + c
    if n_disc == 0:
        p = 1.0
    else:
        p = float(_sps.binomtest(min(b, c), n_disc, 0.5, alternative="two-sided").pvalue)
    return {
        "b": b,
        "c": c,
        "p": p,
        "n_cases": len(shared),
        "both_correct": both_correct,
        "both_wrong": both_wrong,
        "aggregate": aggregate,
    }


# --------------------------------------------------------------------------------------
# 6. pass^k
# --------------------------------------------------------------------------------------


def pass_k(
    rows: Iterable[Row],
    condition: str,
    metric: str,
    k: int,
    task: str | None = None,
    n_boot: int = 10000,
    seed: int = 0,
    alpha: float = 0.05,
    mode: str = "all",
) -> dict[str, Any]:
    """Unbiased estimate of the probability that ``k`` independent runs all pass.

    For a case with ``R`` reps of which ``c`` are correct, the unbiased estimator of
    ``p_case ** k`` (the chance that k fresh draws are all correct) is
    ``comb(c, k) / comb(R, k)``: the fraction of k-subsets of the observed reps that
    are all correct. It is exactly unbiased for any R >= k because each k-subset of
    i.i.d. reps is a fair sample of k draws. Cases with ``R < k`` are skipped and
    counted in ``n_cases_skipped``. The reported ``estimate`` is the mean over cases,
    with a case-level percentile bootstrap interval.

    ``mode="all"`` (default, the "pass^k" consistency estimator) is the quantity above.
    ``mode="any"`` gives the complementary "pass@k" estimator
    ``1 - comb(R - c, k) / comb(R, k)``, the chance that at least one of k draws passes.

    Assumes a binary metric and that a case's reps are i.i.d. draws from that case's
    pass probability. Keys: ``k``, ``mode``, ``estimate``, ``ci_lo``, ``ci_hi``,
    ``n_cases``, ``n_cases_skipped``.
    """
    if not isinstance(k, (int, np.integer)) or isinstance(k, bool) or k < 1:
        raise ValueError(f"k must be a positive integer, got {k!r}")
    if mode not in ("all", "any"):
        raise ValueError(f"mode must be 'all' or 'any', got {mode!r}")
    scores = case_scores(rows, condition, metric, task)
    per_case: list[float] = []
    skipped = 0
    for vals in scores.values():
        arr = np.asarray(vals, dtype=float)
        if not _is_binary(arr):
            raise ValueError("pass_k needs a binary metric (every value 0 or 1)")
        R = int(arr.size)
        if R < k:
            skipped += 1
            continue
        c = int(arr.sum())
        total = math.comb(R, k)
        if mode == "all":
            per_case.append(math.comb(c, k) / total)
        else:
            per_case.append(1.0 - math.comb(R - c, k) / total)
    est = np.asarray(per_case, dtype=float)
    if est.size:
        estimate = float(est.mean())
        rng = np.random.default_rng(seed)
        ci_lo, ci_hi = _percentile_ci(_bootstrap_means(est, n_boot, rng), alpha)
    else:
        estimate, ci_lo, ci_hi = _NAN, _NAN, _NAN
    return {
        "k": int(k),
        "mode": mode,
        "estimate": estimate,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "n_cases": int(est.size),
        "n_cases_skipped": skipped,
    }


# --------------------------------------------------------------------------------------
# 7. Cohen's kappa
# --------------------------------------------------------------------------------------


def _kappa_from_table(table: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised kappa from contingency tables of shape (..., K, K)."""
    n = table.sum(axis=(-1, -2))
    diag = np.trace(table, axis1=-2, axis2=-1)
    row = table.sum(axis=-1)
    col = table.sum(axis=-2)
    with np.errstate(divide="ignore", invalid="ignore"):
        po = diag / n
        pe = (row * col).sum(axis=-1) / (n * n)
        kappa = np.where(pe >= 1.0, 1.0, (po - pe) / (1.0 - pe))
        kappa = np.where(po >= 1.0, 1.0, kappa)
    return kappa, po, pe


def cohens_kappa(
    labels_a: Sequence[Hashable],
    labels_b: Sequence[Hashable],
    n_boot: int = 5000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Cohen's kappa for two raters' nominal labels on the same items.

    ``kappa = (po - pe) / (1 - pe)`` where ``po`` is the observed agreement rate and
    ``pe`` the agreement expected by chance from each rater's marginal label
    frequencies. Perfect agreement gives 1 exactly; if ``pe == 1`` (both raters used a
    single identical label) kappa is defined as 1. Labels may be any hashable values;
    the category set is the union of both raters' labels.

    Interval: percentile bootstrap resampling items with replacement, keeping each
    item's pair of labels together. Because kappa depends on the data only through the
    K x K contingency table, resampling n paired items is equivalent to drawing the
    table from Multinomial(n, observed cell proportions), which is what is done here.

    Assumes items are independent. Kappa is a chance-corrected agreement statistic, not
    a validity measure: it is depressed when the marginal distributions are skewed.
    Keys: ``kappa``, ``ci_lo``, ``ci_hi``, ``po``, ``pe``, ``n``.
    """
    a = list(labels_a)
    b = list(labels_b)
    if len(a) != len(b):
        raise ValueError(f"labels_a and labels_b differ in length: {len(a)} vs {len(b)}")
    n = len(a)
    if n == 0:
        return {"kappa": _NAN, "ci_lo": _NAN, "ci_hi": _NAN, "po": _NAN, "pe": _NAN, "n": 0}

    codes: dict[Hashable, int] = {}
    for lab in a + b:
        codes.setdefault(lab, len(codes))
    K = len(codes)
    table = np.zeros((K, K), dtype=float)
    for la, lb in zip(a, b):
        table[codes[la], codes[lb]] += 1.0

    kappa, po, pe = _kappa_from_table(table)
    if n_boot > 0:
        rng = np.random.default_rng(seed)
        probs = table.ravel() / n
        counts = rng.multinomial(n, probs, size=n_boot).reshape(n_boot, K, K).astype(float)
        boot, _, _ = _kappa_from_table(counts)
        ci_lo, ci_hi = _percentile_ci(boot, alpha)
    else:
        ci_lo, ci_hi = _NAN, _NAN
    return {
        "kappa": float(kappa),
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "po": float(po),
        "pe": float(pe),
        "n": n,
    }


# --------------------------------------------------------------------------------------
# 8. Holm-Bonferroni
# --------------------------------------------------------------------------------------


def holm_bonferroni(pvalues: Sequence[float]) -> list[float]:
    """Holm step-down adjusted p-values, returned in the original order.

    Sort the m p-values ascending; the i-th smallest (1-based) is multiplied by
    ``m - i + 1``; a running maximum then enforces monotonicity (an adjusted value can
    never be smaller than the adjusted value of a smaller raw p) and everything is
    capped at 1. Rejecting every adjusted p <= alpha controls the family-wise error
    rate at alpha under arbitrary dependence, and is uniformly more powerful than plain
    Bonferroni. The largest raw p is multiplied by 1, so its adjusted value equals the
    raw value unless the monotonicity step lifts it.
    """
    p = np.asarray(list(pvalues), dtype=float)
    m = int(p.size)
    if m == 0:
        return []
    if np.isnan(p).any() or (p < 0.0).any() or (p > 1.0).any():
        raise ValueError("p-values must be numbers in [0, 1]")
    order = np.argsort(p, kind="stable")
    multipliers = m - np.arange(m)
    adj_sorted = np.minimum(1.0, np.maximum.accumulate(multipliers * p[order]))
    adj = np.empty(m, dtype=float)
    adj[order] = adj_sorted
    return [float(x) for x in adj]


# --------------------------------------------------------------------------------------
# 9. Noise floor
# --------------------------------------------------------------------------------------


def noise_floor(
    n_cases: int, n_reps: int, p: float = 0.5, alpha: float = 0.05, rho: float = 0.0
) -> float:
    """Approximate half-width of a ``1 - alpha`` interval on a clustered pass rate.

    Uses the design-effect correction for ``n_cases`` clusters of ``n_reps`` reps::

        n_eff = n_cases * n_reps / (1 + (n_reps - 1) * rho)
        half_width = z_{1 - alpha/2} * sqrt(p * (1 - p) / n_eff)

    ``rho`` is the intra-case correlation of rep outcomes: the share of outcome
    variance that sits between cases rather than between reps of one case. ``rho = 0``
    means reps are independent draws, so every rep adds information as if it were a
    new case. ``rho = 1`` means all reps of a case give the same answer, so reps add
    nothing and ``n_eff = n_cases``. Real harness runs sit in between; 0.3 to 0.7 is
    typical for graded LLM outputs. The formula is a normal approximation and is most
    useful for planning ("can this design see a 3 point gap?"), not for reporting.
    """
    if n_cases <= 0 or n_reps <= 0:
        raise ValueError("n_cases and n_reps must be positive")
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"p must be in [0, 1], got {p}")
    if not 0.0 <= rho <= 1.0:
        raise ValueError(f"rho must be in [0, 1], got {rho}")
    z = _z(alpha)
    design_effect = 1.0 + (n_reps - 1) * rho
    n_eff = n_cases * n_reps / design_effect
    return float(z * math.sqrt(p * (1.0 - p) / n_eff))


# --------------------------------------------------------------------------------------
# 10. Minimum detectable effect by simulation
# --------------------------------------------------------------------------------------


def _beta_params(mean: float, rho: float) -> tuple[float, float]:
    """Beta(a, b) with the given mean and intra-case correlation ``rho = 1/(a+b+1)``."""
    concentration = (1.0 - rho) / rho
    return mean * concentration, (1.0 - mean) * concentration


def simulate_paired_power(
    n_cases: int,
    n_reps: int,
    baseline_p: float,
    delta: float,
    alpha: float = 0.05,
    rho_case: float = 0.5,
    n_sim: int = 2000,
    seed: int = 0,
    fast: bool = False,
    n_boot_inner: int = 1000,
) -> float:
    """Simulated power of a paired two-condition comparison at effect ``delta``.

    Data-generating model (beta-binomial with a shared latent difficulty): each case
    draws ``p_case ~ Beta(a, b)`` with mean ``baseline_p`` and ``rho_case =
    1 / (a + b + 1)``, the intra-case correlation of rep outcomes under A. Condition A
    passes each rep with probability ``p_case`` and condition B with
    ``clip(p_case + delta, 0, 1)``. Reps are Bernoulli and are coupled across A and B
    through shared uniforms so that B's per-rep outcome is monotone in ``delta``
    (common random numbers). ``rho_case = 0`` makes every case ``p = baseline_p``;
    ``rho_case = 1`` makes ``p_case`` itself Bernoulli(baseline_p).

    Test applied to each simulated dataset:

    * ``fast=True``: two-sided paired t-test on the per-case mean differences at
      ``alpha``. A dataset with zero variance rejects iff its mean difference is
      non-zero.
    * ``fast=False``: reject when the paired case-level percentile bootstrap interval
      (``n_boot_inner`` resamples, level ``1 - alpha``) excludes zero. This is the
      same decision rule :func:`paired_diff` reports. Within a chunk of simulations
      the resampling weights are shared (common random numbers); each dataset's test
      is still a valid bootstrap, so the power estimate is unbiased.

    Returns the fraction of ``n_sim`` simulated datasets that reject.
    """
    if n_cases < 2 or n_reps < 1:
        raise ValueError("need n_cases >= 2 and n_reps >= 1")
    if not 0.0 <= baseline_p <= 1.0:
        raise ValueError(f"baseline_p must be in [0, 1], got {baseline_p}")
    if not 0.0 <= rho_case <= 1.0:
        raise ValueError(f"rho_case must be in [0, 1], got {rho_case}")
    if n_sim < 1:
        raise ValueError("n_sim must be positive")
    _z(alpha)  # validates alpha

    rng = np.random.default_rng(seed)
    t_crit = float(_sps.t.ppf(1.0 - alpha / 2.0, n_cases - 1))
    chunk = max(1, _MAX_CHUNK_ELEMENTS // (n_cases * n_reps))
    rejections = 0
    for start in range(0, n_sim, chunk):
        m = min(chunk, n_sim - start)
        if rho_case <= 0.0:
            p_case = np.full((m, n_cases), baseline_p)
        elif rho_case >= 1.0:
            p_case = (rng.random((m, n_cases)) < baseline_p).astype(float)
        else:
            a, b = _beta_params(baseline_p, rho_case)
            p_case = rng.beta(a, b, size=(m, n_cases))
        p_b = np.clip(p_case + delta, 0.0, 1.0)
        u_a = rng.random((m, n_cases, n_reps))
        u_b = rng.random((m, n_cases, n_reps))
        mean_a = (u_a < p_case[..., None]).mean(axis=2)
        mean_b = (u_b < p_b[..., None]).mean(axis=2)
        d = mean_b - mean_a  # (m, n_cases)

        if fast:
            dbar = d.mean(axis=1)
            sd = d.std(axis=1, ddof=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                t = dbar / (sd / math.sqrt(n_cases))
            reject = np.where(sd > 0.0, np.abs(t) > t_crit, dbar != 0.0)
        else:
            weights = rng.multinomial(
                n_cases, np.full(n_cases, 1.0 / n_cases), size=n_boot_inner
            ).astype(float)
            boot = d @ weights.T / n_cases  # (m, n_boot_inner)
            lo = np.percentile(boot, 100.0 * alpha / 2.0, axis=1)
            hi = np.percentile(boot, 100.0 * (1.0 - alpha / 2.0), axis=1)
            reject = (lo > 0.0) | (hi < 0.0)
        rejections += int(reject.sum())
    return rejections / n_sim


def mde_paired(
    n_cases: int,
    n_reps: int,
    baseline_p: float,
    power: float = 0.8,
    alpha: float = 0.05,
    rho_case: float = 0.5,
    n_sim: int = 2000,
    seed: int = 0,
    fast: bool = False,
    n_boot_inner: int = 1000,
) -> float:
    """Minimum detectable difference in pass rate for a paired two-condition design.

    Scans ``delta`` over the grid 0.01, 0.02, ..., 0.50 and returns the smallest value
    whose simulated power (see :func:`simulate_paired_power` for the beta-binomial
    model and the decision rule) reaches ``power``. The same seed is reused for every
    grid point so the power curve is evaluated on common random numbers and is
    monotone in ``delta`` up to the resolution of the test statistic. Returns ``nan``
    if no grid value reaches the target, meaning the design cannot see a 50 point gap
    at that power.

    ``fast=True`` uses the paired t-test on per-case means, which runs in well under a
    second for typical sizes; the default uses the paired bootstrap interval, the same
    rule :func:`paired_diff` reports, and takes a few seconds.
    """
    if not 0.0 < power < 1.0:
        raise ValueError(f"power must be in (0, 1), got {power}")
    grid = np.round(np.arange(1, 51) / 100.0, 2)
    for delta in grid:
        pw = simulate_paired_power(
            n_cases,
            n_reps,
            baseline_p,
            float(delta),
            alpha=alpha,
            rho_case=rho_case,
            n_sim=n_sim,
            seed=seed,
            fast=fast,
            n_boot_inner=n_boot_inner,
        )
        if pw >= power:
            return float(delta)
    return _NAN


# --------------------------------------------------------------------------------------
# 11. Summary table
# --------------------------------------------------------------------------------------


def summarize(
    rows: Iterable[Row],
    metrics: list[str],
    conditions: list[str],
    task: str | None = None,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Condition estimates for every metric x condition, plus exclusion counts.

    Returns ``{metric: {condition: condition_estimate(...)}}`` (with ``n_boot=2000``
    by default) and a ``"_excluded"`` entry mapping each condition to its number of
    rows whose status is not ``"ok"`` (under the same ``task`` filter, independent of
    metric). Every bootstrap uses the same ``seed`` so results are reproducible.
    """
    rows = list(rows)
    out: dict[str, Any] = {}
    for metric in metrics:
        out[metric] = {
            cond: condition_estimate(rows, cond, metric, task, n_boot=n_boot, seed=seed, alpha=alpha)
            for cond in conditions
        }
    out["_excluded"] = {cond: _count_excluded(rows, cond, task) for cond in conditions}
    return out


def _fmt(x: Any, digits: int) -> str:
    if x is None:
        return "n/a"
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return str(x)
    if math.isnan(xf):
        return "nan"
    return f"{xf:.{digits}f}"


def to_markdown_table(
    summary: dict[str, Any], metrics: list[str], conditions: list[str], digits: int = 3
) -> str:
    """Render a :func:`summarize` result as a markdown table.

    One row per metric and one column per condition. Each cell reads
    ``mean [ci_lo, ci_hi] (n=n_cases)`` with the bootstrap interval; a missing
    estimate or a condition with no cases renders as ``n/a (n=0)``.
    """
    header = "| metric | " + " | ".join(conditions) + " |"
    sep = "|---|" + "|".join("---" for _ in conditions) + "|"
    lines = [header, sep]
    for metric in metrics:
        cells = []
        per_cond = summary.get(metric, {}) or {}
        for cond in conditions:
            est = per_cond.get(cond)
            if not est or not est.get("n_cases"):
                n = est.get("n_cases", 0) if est else 0
                cells.append(f"n/a (n={n})")
                continue
            cells.append(
                f"{_fmt(est['mean'], digits)} "
                f"[{_fmt(est['ci_lo'], digits)}, {_fmt(est['ci_hi'], digits)}] "
                f"(n={est['n_cases']})"
            )
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


__all__ = [
    "wilson_interval",
    "case_scores",
    "condition_estimate",
    "paired_diff",
    "mcnemar_exact",
    "pass_k",
    "cohens_kappa",
    "holm_bonferroni",
    "noise_floor",
    "simulate_paired_power",
    "mde_paired",
    "summarize",
    "to_markdown_table",
]
