from __future__ import annotations

import copy

import pytest

from bench.adapters.null import null_output
from bench.adapters.oracle import oracle_output
from bench.cases import constraints_for_case, corpus_for_case
from bench.graders import (
    INGESTION_METRICS,
    LOWER_IS_BETTER,
    VERDICT_METRICS,
    grade_ingestion,
    grade_verdict,
    severity_rank,
    threshold_tokens,
    thresholds_equal,
)


def _grade(output, case):
    if case["task"] == "ingestion":
        return grade_ingestion(output, case, corpus_for_case(case))
    return grade_verdict(output, case, constraints_for_case(case), corpus_for_case(case))


def _perfect(metric: str) -> float:
    return 0.0 if metric in LOWER_IS_BETTER else 1.0


# ---------------------------------------------------------------------------------------
# oracle and null
# ---------------------------------------------------------------------------------------

def test_fixture_counts(ingestion_cases, verdict_cases):
    assert len(ingestion_cases) == 3
    assert len(verdict_cases) == 6
    overalls = {c["gold"]["overall"] for c in verdict_cases}
    assert overalls == {"pass", "warn", "breach", "hard_block"}
    verbs = {c["gold"]["recommendation_verb"] for c in verdict_cases}
    assert "gather-more-data" in verbs
    assert any(c["variant_kind"] == "as_of_prior_version" for c in verdict_cases)


def test_oracle_scores_perfect_on_every_case(ingestion_cases, verdict_cases):
    for case in ingestion_cases + verdict_cases:
        grades = _grade(oracle_output(case, case["task"]), case)
        expected_keys = set(INGESTION_METRICS if case["task"] == "ingestion" else VERDICT_METRICS)
        assert set(grades) == expected_keys, case["case_id"]
        for metric, value in grades.items():
            if value is None:
                continue
            assert value == _perfect(metric), (case["case_id"], metric, value)


def test_oracle_none_only_where_not_applicable(verdict_cases):
    for case in verdict_cases:
        g = _grade(oracle_output(case, "verdict"), case)
        is_hard = case["gold"]["overall"] == "hard_block"
        assert (g["hard_block_correct"] is None) == (not is_hard)
        assert (g["hard_block_false_alarm"] is None) == is_hard
        multi = len({d["doc_id"] for d in case["documents"]}) < len(case["documents"])
        assert (g["version_in_force_respected"] is not None) == multi
        if case["gold"]["citable_constraint_ids"]:
            assert g["citable_coverage"] == 1.0 and g["citations_present"] == 1.0
        else:
            assert g["citable_coverage"] is None and g["citations_present"] is None


def test_null_scores_zero_where_it_should(ingestion_cases, verdict_cases):
    for case in verdict_cases:
        g = _grade(null_output("verdict"), case)
        if case["gold"]["overall"] != "pass":
            assert g["overall_correct"] == 0.0, case["case_id"]
            assert g["rules_hit_f1"] == 0.0
            assert g["citable_coverage"] == 0.0
            assert g["citations_present"] == 0.0
        else:
            assert g["overall_correct"] == 1.0
        assert g["causal_clean"] == 1.0
    for case in ingestion_cases:
        g = _grade(null_output("ingestion"), case)
        assert g["constraint_recall"] == 0.0
        assert g["constraint_f1"] == 0.0
        assert g["constraint_precision"] is None  # nothing extracted: precision not applicable


def test_wrong_but_plausible_output_fails_the_right_metrics(verdict_case_by_id):
    case = verdict_case_by_id["GTF-S03-breach"]
    out = copy.deepcopy(oracle_output(case, "verdict"))
    out["approval_path"] = ["PM", "Compliance"]  # wrong sequence
    out["citations"][0]["quote"] = "Technology exposure is capped at 35% under all circumstances."  # fabricated
    g = _grade(out, case)
    assert g["overall_correct"] == 1.0
    assert g["verb_correct"] == 1.0
    assert g["approval_path_correct"] == 0.0
    assert g["citation_grounded"] == 0.0
    assert g["citable_coverage"] == 0.0
    assert g["citation_relevant"] is None  # no grounded citation to judge


# ---------------------------------------------------------------------------------------
# helpers and normalisations
# ---------------------------------------------------------------------------------------

def test_threshold_tokens_surface_forms(dataset):
    c = dataset.constraints_by_id["GTF-guidelines-v1-C01"]
    toks = threshold_tokens(c)
    for form in ("8%", "8 per cent", "8 percent", "8.0%", "8"):
        assert form in toks
    band = dataset.constraints_by_id["CBF-guidelines-v1-C02"]
    assert "3 years" in threshold_tokens(band) and "7 years" in threshold_tokens(band)
    restricted = dataset.constraints_by_id["GTF-guidelines-v1-C04"]
    assert threshold_tokens(restricted) == ["Compliance Restricted List"]


def test_pct_fraction_normalisation():
    assert thresholds_equal(0.08, 8, "pct_nav", rescale=True)
    assert not thresholds_equal(0.08, 8, "pct_nav", rescale=False)
    assert not thresholds_equal(0.08, 8, "years", rescale=True)
    assert thresholds_equal([3, 7.0000000001], [3, 7], "years")
    assert thresholds_equal("compliance restricted list", "Compliance Restricted List")
    assert thresholds_equal("8%", 8, "pct_nav")


def test_fraction_threshold_counts_as_match_but_not_exact(ingestion_cases):
    case = next(c for c in ingestion_cases if c["case_id"] == "GTF-guidelines-v1-canonical")
    out = copy.deepcopy(oracle_output(case, "ingestion"))
    for c in out["constraints"]:
        if c["type"] == "single_name_max":
            c["threshold"] = 0.08
    g = _grade(out, case)
    assert g["constraint_f1"] == 1.0
    assert g["threshold_exact"] == pytest.approx(3 / 4)


def test_distractor_extraction_is_penalised(ingestion_cases):
    case = next(c for c in ingestion_cases if c["case_id"] == "GTF-guidelines-v1-canonical")
    out = copy.deepcopy(oracle_output(case, "ingestion"))
    distractor = case["distractors"][0]
    out["constraints"].append(
        {
            "type": distractor["type"],
            "scope": dict(distractor["scope"]),
            "comparator": distractor["comparator"],
            "threshold": distractor["threshold"],
            "unit": distractor["unit"],
            "effective_from": "2024-01-01",
            "evidence": {"rendering_id": case["rendering_id"], "quote": distractor["canonical_text"], "claims_constraint": None},
        }
    )
    g = _grade(out, case)
    assert g["distractor_excluded"] == 0.0
    assert g["constraint_recall"] == 1.0
    assert g["constraint_precision"] == pytest.approx(4 / 5)
    assert g["evidence_grounded"] == 1.0
    # the distractor quote is grounded but matched to nothing, so it is misgrounded
    assert g["evidence_misgrounded_rate"] == pytest.approx(1 / 5)


def test_evidence_ungrounded_and_misgrounded(ingestion_cases):
    case = next(c for c in ingestion_cases if c["case_id"] == "CBF-guidelines-v1-canonical")
    out = copy.deepcopy(oracle_output(case, "ingestion"))
    out["constraints"][0]["evidence"]["quote"] = "This sentence is not in the document."
    out["constraints"][1]["evidence"]["quote"] = "All waivers require four-eyes control."  # grounded, no limit token
    g = _grade(out, case)
    assert g["evidence_ungrounded_rate"] == pytest.approx(0.5)
    assert g["evidence_misgrounded_rate"] == pytest.approx(0.5)
    assert g["evidence_relevant"] == 0.0
    assert g["constraint_f1"] == 1.0  # structure still right


def test_role_synonyms_and_verb_normalisation(verdict_case_by_id):
    case = verdict_case_by_id["GTF-S03-breach"]
    out = copy.deepcopy(oracle_output(case, "verdict"))
    out["approval_path"] = ["Portfolio Manager", "chief investment officer", "Compliance Officer"]
    out["recommendation_verb"] = "Request Exception"
    g = _grade(out, case)
    assert g["approval_path_correct"] == 1.0
    assert g["verb_correct"] == 1.0


def test_rationale_language_and_reference_binding(verdict_case_by_id):
    case = verdict_case_by_id["GTF-S02-warn"]
    out = copy.deepcopy(oracle_output(case, "verdict"))
    out["rationale"] = "The warn is driven by momentum in the Technology sector."
    g = _grade(out, case)
    assert g["causal_clean"] == 0.0
    out["rationale"] = "See GTF-guidelines-v2-C01 and precedent DEC-42."
    g = _grade(out, case)
    assert g["causal_clean"] == 1.0
    assert g["references_bound"] == 0.0  # DEC-42 is not a known id
    out["rationale"] = "See GTF-guidelines-v2-C01 in scenario GTF-S02-warn."
    assert _grade(out, case)["references_bound"] == 1.0


def test_version_in_force_respected_uses_rule_limits(verdict_case_by_id):
    case = verdict_case_by_id["GTF-S02-warn-prior"]  # v1 in force: limit 8, other version says 10
    out = copy.deepcopy(oracle_output(case, "verdict"))
    assert _grade(out, case)["version_in_force_respected"] == 1.0
    out["rules_hit"][0]["limit"] = 10
    assert _grade(out, case)["version_in_force_respected"] == 0.0
    out["rules_hit"][0]["limit"] = None  # no limit given: fall back to overall_correct
    assert _grade(out, case)["version_in_force_respected"] == 1.0
    out["overall"] = "warn"
    assert _grade(out, case)["version_in_force_respected"] == 0.0


def test_severity_distance_and_hard_block_metrics(verdict_case_by_id):
    case = verdict_case_by_id["GTF-S04-hardblock"]
    out = copy.deepcopy(oracle_output(case, "verdict"))
    out["overall"] = "warn"
    g = _grade(out, case)
    assert g["overall_correct"] == 0.0
    assert g["severity_distance"] == pytest.approx(1 - 2 / 3)
    assert g["hard_block_correct"] == 0.0
    assert g["hard_block_false_alarm"] is None

    case2 = verdict_case_by_id["GTF-S01-pass"]
    out2 = copy.deepcopy(oracle_output(case2, "verdict"))
    out2["overall"] = "hard_block"
    g2 = _grade(out2, case2)
    assert g2["hard_block_false_alarm"] == 1.0
    assert g2["hard_block_no_false_alarm"] == 0.0
    assert g2["severity_distance"] == 0.0


def test_rule_hit_matching_ignores_pass_entries_and_wildcard_targets(verdict_case_by_id):
    case = verdict_case_by_id["GTF-S02-warn"]
    out = copy.deepcopy(oracle_output(case, "verdict"))
    out["rules_hit"][0]["scope"]["target"] = "NVDA"  # gold scope has no target: still a match
    out["rules_hit"].append({"type": "sector_max", "scope": {"level": "sector", "target": "Technology"}, "verdict": "pass"})
    g = _grade(out, case)
    assert g["rules_hit_precision"] == 1.0 and g["rules_hit_recall"] == 1.0
    out["rules_hit"][0]["verdict"] = "breach"
    g = _grade(out, case)
    assert g["rule_verdict_accuracy"] == 0.0
    assert g["rules_hit_f1"] == 1.0


def test_malformed_output_grades_instead_of_crashing(verdict_case_by_id, ingestion_cases):
    case = verdict_case_by_id["GTF-S02-warn"]
    g = grade_verdict({"overall": None, "rules_hit": "nope", "citations": [None, 3]}, case, constraints_for_case(case), corpus_for_case(case))
    assert g["overall_correct"] == 0.0 and g["citation_grounded"] == 0.0
    case_i = ingestion_cases[0]
    gi = grade_ingestion({"constraints": [{"type": "cash_min"}]}, case_i, corpus_for_case(case_i))
    assert gi["constraint_recall"] == 0.0 and gi["evidence_grounded"] == 0.0


def test_severity_rank_export():
    assert severity_rank == {"pass": 0, "warn": 1, "breach": 2, "hard_block": 3}
