"""Atomic, pure graders for the two tasks.

Every metric returns 0/1, a float in [0, 1], or None when it does not apply to the case.
The stats layer treats None as "not applicable" and excludes it from averages, so a None
must never be used to mean "wrong".

Normalisation rules (documented here because they define what "correct" means):

* Text grounding: a quote is grounded if, after collapsing whitespace, folding case and
  straightening curly quotes and dashes, it is a substring of the rendering text.
* Scope targets are compared case-insensitively with whitespace collapsed; a gold scope
  without a target matches any model target (the rule applies at that level generally).
* Thresholds: numbers are compared with tolerance 1e-6; lists elementwise; strings
  case-insensitively. For the constraint match used by precision/recall/F1 one extra
  rescale is allowed: when the unit is ``pct_nav`` and the model gave a value <= 1 while
  the gold value is > 1, the model value is multiplied by 100 first (so 0.05 and 5 are the
  same number). ``threshold_exact`` does NOT apply that rescale.
* Approval-path roles: case-insensitive, with the synonyms "compliance officer" ->
  Compliance, "portfolio manager" -> PM, "chief investment officer" -> CIO,
  "valuation committee" -> ValuationCommittee (plus "head of risk" -> Risk).
* Rule hits are matched to gold constraints by type, scope level (when both sides give one)
  and normalised scope target (when the gold constraint has one). Model hits whose verdict
  is "pass" are informational and ignored by the rules_hit metrics, because gold rules_hit
  only lists rules whose verdict is not pass.
* Threshold relevance: a quote is relevant to a constraint if it contains one of the
  surface forms returned by ``threshold_tokens`` (for a ``between`` band, either edge).
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Iterable

severity_rank: dict[str, int] = {"pass": 0, "warn": 1, "breach": 2, "hard_block": 3}

ID_REGEXES = (
    re.compile(r"\b[A-Z]{2,4}-[A-Za-z_]+-v\d+-C\d{2}\b"),
    re.compile(r"\bDEC-\d+\b"),
)

_DEFAULT_BANNED = ("driven by", "caused by", "because of the market", "as a result of", "led to", "due to the")


def _load_banned_phrases() -> tuple[str, ...]:
    """Read the banned phrases from policy_semantics.md so the grader tracks the reference."""
    path = Path(__file__).with_name("policy_semantics.md")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _DEFAULT_BANNED
    m = re.search(r"Banned phrases:\s*(.+)", text)
    if not m:
        return _DEFAULT_BANNED
    phrases = tuple(p.strip().lower() for p in re.findall(r'"([^"]+)"', m.group(1)))
    return phrases or _DEFAULT_BANNED


BANNED_PHRASES: tuple[str, ...] = _load_banned_phrases()

ROLE_SYNONYMS = {
    "pm": "PM",
    "portfolio manager": "PM",
    "cio": "CIO",
    "chief investment officer": "CIO",
    "compliance": "Compliance",
    "compliance officer": "Compliance",
    "risk": "Risk",
    "head of risk": "Risk",
    "chief risk officer": "Risk",
    "valuation committee": "ValuationCommittee",
    "valuationcommittee": "ValuationCommittee",
}

NUM_TOL = 1e-6


# ---------------------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------------------

_QUOTE_MAP = str.maketrans(
    {
        chr(0x2018): "'", chr(0x2019): "'", chr(0x201A): "'", chr(0x201B): "'",   # curly single quotes
        chr(0x201C): '"', chr(0x201D): '"', chr(0x201E): '"',                     # curly double quotes
        chr(0x2013): "-", chr(0x2014): "-", chr(0x2212): "-", chr(0x00A0): " ",   # en/em dash, minus, nbsp
    }
)


def normalize_text(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).translate(_QUOTE_MAP)
    return " ".join(s.split()).casefold()


def is_grounded(quote: Any, text: Any) -> bool:
    q = normalize_text(quote)
    if not q:
        return False
    return q in normalize_text(text)


def norm_target(t: Any) -> str:
    return normalize_text(t)


def norm_role(r: Any) -> str:
    key = " ".join(str(r or "").replace("_", " ").split()).casefold()
    if key in ROLE_SYNONYMS:
        return ROLE_SYNONYMS[key]
    compact = key.replace(" ", "")
    if compact in ROLE_SYNONYMS:
        return ROLE_SYNONYMS[compact]
    return str(r or "").strip()


def norm_verb(v: Any) -> str:
    return str(v or "").strip().casefold().replace("_", "-").replace(" ", "-")


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _to_number(x: Any) -> float | None:
    if _is_number(x):
        return float(x)
    if isinstance(x, str):
        s = x.strip().replace(",", "")
        s = re.sub(r"\s*(%|per\s*cent|percent|years?|bps|days|x)\s*$", "", s, flags=re.I)
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _num_equal(a: float, b: float) -> bool:
    return abs(a - b) <= NUM_TOL * max(1.0, abs(a), abs(b))


def thresholds_equal(model_val: Any, gold_val: Any, unit: str | None = None, rescale: bool = False) -> bool:
    """Compare thresholds after normalisation. See module docstring for the rescale rule."""
    if gold_val is None:
        return model_val is None or model_val == "" or model_val == []
    if isinstance(gold_val, list):
        if not isinstance(model_val, (list, tuple)) or len(model_val) != len(gold_val):
            return False
        return all(thresholds_equal(m, g, unit, rescale) for m, g in zip(model_val, gold_val))
    if _is_number(gold_val):
        mv = _to_number(model_val)
        if mv is None:
            return False
        g = float(gold_val)
        if rescale and unit == "pct_nav" and mv <= 1.0 and g > 1.0:
            mv = mv * 100.0
        return _num_equal(mv, g)
    # string threshold
    return normalize_text(model_val) == normalize_text(gold_val)


def _fmt_num(x: float) -> list[str]:
    forms = []
    if float(x).is_integer():
        i = int(x)
        forms += [str(i), f"{i}.0"]
    else:
        s = repr(float(x))
        forms.append(s)
        forms.append(s.rstrip("0") if "." in s else s)
        if s.startswith("0."):
            forms.append(s[1:])
    # keep order, drop duplicates
    seen: list[str] = []
    for f in forms:
        if f not in seen:
            seen.append(f)
    return seen


def _numeric_forms(value: float, unit: str | None, canonical_text: str) -> list[str]:
    forms: list[str] = []
    bare = _fmt_num(value)
    forms += bare
    if unit == "pct_nav" or unit == "bps" or unit is None:
        pass
    if unit == "pct_nav":
        for b in bare:
            forms += [f"{b}%", f"{b} %", f"{b} per cent", f"{b} percent", f"{b}pct", f"{b} pct"]
        if value > 1.0:
            frac = value / 100.0
            forms += _fmt_num(round(frac, 10))
        elif 0 < value <= 1.0:
            pct = value * 100.0
            forms += [f"{b}%" for b in _fmt_num(round(pct, 10))]
    elif unit == "years":
        for b in bare:
            forms += [f"{b} years", f"{b} year", f"{b}y", f"{b} yrs"]
    elif unit == "bps":
        for b in bare:
            forms += [f"{b} bps", f"{b}bps", f"{b} bp", f"{b} basis points"]
    elif unit == "days":
        for b in bare:
            forms += [f"{b} days", f"{b} day", f"{b} business days"]
    elif unit == "x":
        for b in bare:
            forms += [f"{b}x", f"{b} x", f"{b} times"]
    # the number as it appears in the canonical text (e.g. "8.00%")
    for m in re.finditer(r"\d+(?:\.\d+)?\s*(%|per\s*cent|percent)?", canonical_text or ""):
        num = _to_number(m.group(0))
        if num is None:
            continue
        if _num_equal(num, value) or (unit == "pct_nav" and (_num_equal(num * 100.0, value) or _num_equal(num, value * 100.0))):
            forms.append(m.group(0).strip())
            forms.append(re.match(r"\d+(?:\.\d+)?", m.group(0)).group(0))
    seen: list[str] = []
    for f in forms:
        if f and f not in seen:
            seen.append(f)
    return seen


def threshold_tokens(constraint: dict) -> list[str]:
    """Surface forms of a constraint's limit that make a quote relevant.

    Numeric limits yield the bare number, unit-decorated forms ("8%", "8 per cent",
    "8 percent", "8.0%", ...) and the number exactly as it appears in canonical_text.
    ``between`` bands yield the forms of both edges. String limits (restricted lists,
    ratings) yield the string itself. A ``prohibited`` rule with no string limit yields the
    scope target (the prohibited item).
    """
    thr = constraint.get("threshold")
    unit = constraint.get("unit")
    ctext = constraint.get("canonical_text") or ""
    tokens: list[str] = []
    if isinstance(thr, list):
        for v in thr:
            if _is_number(v):
                tokens += _numeric_forms(float(v), unit, ctext)
            elif isinstance(v, str) and v.strip():
                tokens.append(v.strip())
    elif _is_number(thr):
        tokens += _numeric_forms(float(thr), unit, ctext)
    elif isinstance(thr, str) and thr.strip():
        tokens.append(thr.strip())
    if constraint.get("comparator") in ("prohibited", "required") or thr is None:
        target = (constraint.get("scope") or {}).get("target")
        if isinstance(target, str) and target.strip():
            tokens.append(target.strip())
    seen: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
    return seen


def _token_in_text(token: str, norm_quote: str) -> bool:
    t = normalize_text(token)
    if not t:
        return False
    if re.fullmatch(r"\.?\d+(?:\.\d+)?", t):
        pat = r"(?<!\d)(?<!\d\.)" + re.escape(t) + r"(?!\d)(?!\.\d)"
        return re.search(pat, norm_quote) is not None
    return t in norm_quote


def contains_threshold_token(quote: Any, constraint: dict) -> bool:
    nq = normalize_text(quote)
    if not nq:
        return False
    return any(_token_in_text(tok, nq) for tok in threshold_tokens(constraint))


def _norm_date(d: Any) -> str | None:
    if d is None:
        return None
    s = str(d).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%d %b %Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return _dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s.casefold()


# ---------------------------------------------------------------------------------------
# generic coercion so malformed outputs grade rather than crash
# ---------------------------------------------------------------------------------------

def _as_dict(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _as_list(x: Any) -> list:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _scope(x: Any) -> dict:
    s = _as_dict(_as_dict(x).get("scope"))
    return {"level": s.get("level"), "target": s.get("target")}


def _scope_match(model_scope: dict, gold_scope: dict) -> bool:
    gl, gt = gold_scope.get("level"), gold_scope.get("target")
    ml, mt = model_scope.get("level"), model_scope.get("target")
    if gl and ml and normalize_text(gl) != normalize_text(ml):
        return False
    if gt not in (None, ""):
        return norm_target(gt) == norm_target(mt)
    return True


def _type_scope_match(model_item: dict, gold_c: dict) -> bool:
    if normalize_text(model_item.get("type")) != normalize_text(gold_c.get("type")):
        return False
    return _scope_match(_scope(model_item), _scope(gold_c))


def _full_match(model_item: dict, gold_c: dict) -> bool:
    if not _type_scope_match(model_item, gold_c):
        return False
    if normalize_text(model_item.get("comparator")) != normalize_text(gold_c.get("comparator")):
        return False
    return thresholds_equal(model_item.get("threshold"), gold_c.get("threshold"), gold_c.get("unit"), rescale=True)


def _mean(vals: Iterable[float]) -> float | None:
    vals = list(vals)
    return sum(vals) / len(vals) if vals else None


# ---------------------------------------------------------------------------------------
# ingestion
# ---------------------------------------------------------------------------------------

def _match_extracted(extracted: list[dict], gold: list[dict]) -> dict[int, tuple[int, bool]]:
    """Greedy one-to-one matching. Returns ext_idx -> (gold_idx, is_full_match)."""
    assigned: dict[int, tuple[int, bool]] = {}
    used_gold: set[int] = set()
    for ei, e in enumerate(extracted):
        for gi, g in enumerate(gold):
            if gi in used_gold:
                continue
            if _full_match(e, g):
                assigned[ei] = (gi, True)
                used_gold.add(gi)
                break
    for ei, e in enumerate(extracted):
        if ei in assigned:
            continue
        for gi, g in enumerate(gold):
            if gi in used_gold:
                continue
            if _type_scope_match(e, g):
                assigned[ei] = (gi, False)
                used_gold.add(gi)
                break
    return assigned


def grade_ingestion(output: dict, case: dict, corpus_text_by_rendering: dict[str, str]) -> dict[str, float | None]:
    extracted = [_as_dict(x) for x in _as_list(_as_dict(output).get("constraints"))]
    gold = [c for c in _as_list(case.get("gold")) if isinstance(c, dict)]
    distractors = [c for c in _as_list(case.get("distractors")) if isinstance(c, dict)]
    case_text = case.get("text") or corpus_text_by_rendering.get(case.get("rendering_id", ""), "")

    n_ext, n_gold = len(extracted), len(gold)
    assigned = _match_extracted(extracted, gold)
    full = {ei: gi for ei, (gi, is_full) in assigned.items() if is_full}
    scoped = {ei: gi for ei, (gi, _) in assigned.items()}
    tp = len(full)

    precision = (tp / n_ext) if n_ext else None
    recall = (tp / n_gold) if n_gold else None
    if n_ext == 0 and n_gold == 0:
        f1 = None
    else:
        f1 = (2 * tp) / (n_ext + n_gold)

    # among type+scope matches
    exact_flags = []
    date_flags = []
    for ei, gi in scoped.items():
        e, g = extracted[ei], gold[gi]
        exact = (
            normalize_text(e.get("comparator")) == normalize_text(g.get("comparator"))
            and normalize_text(e.get("unit")) == normalize_text(g.get("unit"))
            and thresholds_equal(e.get("threshold"), g.get("threshold"), g.get("unit"), rescale=False)
        )
        exact_flags.append(1.0 if exact else 0.0)
        date_flags.append(1.0 if _norm_date(e.get("effective_from")) == _norm_date(g.get("effective_from")) else 0.0)
    threshold_exact = _mean(exact_flags)
    effective_date_exact = _mean(date_flags)
    scope_attribution = (len(set(scoped.values())) / n_gold) if n_gold else None

    if distractors:
        hit_distractor = False
        for ei, e in enumerate(extracted):
            if ei in full:
                continue
            if any(_full_match(e, d) for d in distractors):
                hit_distractor = True
                break
        distractor_excluded = 0.0 if hit_distractor else 1.0
    else:
        distractor_excluded = None

    grounded_flags: list[bool] = []
    relevant_flags: list[bool] = []
    for ei, e in enumerate(extracted):
        ev = _as_dict(e.get("evidence"))
        rid = ev.get("rendering_id")
        text = corpus_text_by_rendering.get(rid, "") if isinstance(rid, str) else ""
        if not text:
            text = case_text
        grounded = is_grounded(ev.get("quote"), text)
        grounded_flags.append(grounded)
        if grounded:
            gi = scoped.get(ei)
            relevant = gi is not None and contains_threshold_token(ev.get("quote"), gold[gi])
            relevant_flags.append(relevant)
    n_grounded = sum(grounded_flags)
    n_relevant = sum(relevant_flags)
    evidence_grounded = (n_grounded / n_ext) if n_ext else None
    evidence_relevant = (n_relevant / n_grounded) if n_grounded else None
    evidence_misgrounded_rate = ((n_grounded - n_relevant) / n_ext) if n_ext else None
    evidence_ungrounded_rate = ((n_ext - n_grounded) / n_ext) if n_ext else None

    return {
        "constraint_precision": precision,
        "constraint_recall": recall,
        "constraint_f1": f1,
        "threshold_exact": threshold_exact,
        "scope_attribution": scope_attribution,
        "effective_date_exact": effective_date_exact,
        "distractor_excluded": distractor_excluded,
        "evidence_grounded": evidence_grounded,
        "evidence_relevant": evidence_relevant,
        "evidence_misgrounded_rate": evidence_misgrounded_rate,
        "evidence_ungrounded_rate": evidence_ungrounded_rate,
    }


# ---------------------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------------------

def _match_rule_hits(hits: list[dict], gold_constraints: list[dict]) -> dict[int, str]:
    """Greedy one-to-one matching of model rule hits to gold constraints. hit_idx -> cid."""
    assigned: dict[int, str] = {}
    used: set[str] = set()
    # first pass: exact target equality preferred
    for hi, h in enumerate(hits):
        for g in gold_constraints:
            if g["id"] in used:
                continue
            gt = (g.get("scope") or {}).get("target")
            if gt not in (None, "") and _type_scope_match(h, g):
                assigned[hi] = g["id"]
                used.add(g["id"])
                break
    for hi, h in enumerate(hits):
        if hi in assigned:
            continue
        for g in gold_constraints:
            if g["id"] in used:
                continue
            if _type_scope_match(h, g):
                assigned[hi] = g["id"]
                used.add(g["id"])
                break
    return assigned


def _known_ids(case: dict, constraints_by_id: dict[str, dict]) -> set[str]:
    ids = set(constraints_by_id.keys())
    for d in _as_list(case.get("documents")):
        ids.update(_as_list(_as_dict(d).get("constraint_ids")))
    ids.update(_as_list(_as_dict(case.get("gold")).get("rules_in_scope")))
    for k in ("scenario_id", "case_id", "variant_of"):
        v = case.get(k)
        if isinstance(v, str) and v:
            ids.add(v)
    return ids


def grade_verdict(
    output: dict,
    case: dict,
    constraints_by_id: dict[str, dict],
    corpus_text_by_rendering: dict[str, str],
) -> dict[str, float | None]:
    out = _as_dict(output)
    gold = _as_dict(case.get("gold"))
    all_constraints = dict(constraints_by_id)
    all_constraints.update(_as_dict(case.get("constraints")))

    gold_overall = str(gold.get("overall", "")).strip().casefold()
    model_overall = str(out.get("overall", "") or "").strip().casefold()
    overall_correct = 1.0 if model_overall == gold_overall else 0.0
    if model_overall in severity_rank and gold_overall in severity_rank:
        dist = abs(severity_rank[model_overall] - severity_rank[gold_overall]) / 3.0
        severity_distance = 1.0 - dist
    else:
        severity_distance = 0.0

    if gold_overall == "hard_block":
        hard_block_correct: float | None = 1.0 if model_overall == "hard_block" else 0.0
        hard_block_false_alarm: float | None = None
        hard_block_no_false_alarm: float | None = None
    else:
        hard_block_correct = None
        hard_block_false_alarm = 1.0 if model_overall == "hard_block" else 0.0
        hard_block_no_false_alarm = 1.0 - hard_block_false_alarm

    # rule hits
    gold_hit_ids = [cid for cid in _as_list(gold.get("rules_hit")) if cid in all_constraints]
    gold_hit_constraints = [all_constraints[cid] for cid in gold_hit_ids]
    hits_all = [_as_dict(h) for h in _as_list(out.get("rules_hit"))]
    hits = [h for h in hits_all if normalize_text(h.get("verdict")) != "pass"]
    assigned = _match_rule_hits(hits, gold_hit_constraints)
    tp = len(assigned)
    n_model, n_gold = len(hits), len(gold_hit_ids)
    rules_hit_precision = (tp / n_model) if n_model else None
    rules_hit_recall = (tp / n_gold) if n_gold else None
    rules_hit_f1 = None if (n_model == 0 and n_gold == 0) else (2 * tp) / (n_model + n_gold)
    gold_verdicts = _as_dict(gold.get("verdicts"))
    rv_flags = [
        1.0 if normalize_text(hits[hi].get("verdict")) == normalize_text(gold_verdicts.get(cid)) else 0.0
        for hi, cid in assigned.items()
    ]
    rule_verdict_accuracy = _mean(rv_flags)

    # approval path and verb
    model_path = [norm_role(r) for r in _as_list(out.get("approval_path"))]
    gold_path = [norm_role(r) for r in _as_list(gold.get("approval_path"))]
    approval_path_correct = 1.0 if model_path == gold_path else 0.0
    verb_correct = 1.0 if norm_verb(out.get("recommendation_verb")) == norm_verb(gold.get("recommendation_verb")) else 0.0

    # citations
    citable_ids = [cid for cid in _as_list(gold.get("citable_constraint_ids")) if cid in all_constraints]
    citable = [all_constraints[cid] for cid in citable_ids]
    citations = [_as_dict(c) for c in _as_list(out.get("citations"))]
    grounded_cits: list[dict] = []
    for c in citations:
        rid = c.get("rendering_id")
        text = corpus_text_by_rendering.get(rid, "") if isinstance(rid, str) else ""
        if is_grounded(c.get("quote"), text):
            grounded_cits.append(c)
    n_cit = len(citations)
    citation_grounded = (len(grounded_cits) / n_cit) if n_cit else None
    if grounded_cits and citable:
        rel = [1.0 if any(contains_threshold_token(c.get("quote"), g) for g in citable) else 0.0 for c in grounded_cits]
        citation_relevant: float | None = _mean(rel)
    else:
        citation_relevant = None
    if citable:
        covered = [
            1.0 if any(contains_threshold_token(c.get("quote"), g) for c in grounded_cits) else 0.0
            for g in citable
        ]
        citable_coverage: float | None = _mean(covered)
        citations_present: float | None = 1.0 if n_cit > 0 else 0.0
    else:
        citable_coverage = None
        citations_present = None

    # rationale
    rationale = str(out.get("rationale") or "")
    rl = normalize_text(rationale)
    causal_clean = 0.0 if any(normalize_text(p) in rl for p in BANNED_PHRASES) else 1.0
    known = _known_ids(case, all_constraints)
    found_ids: set[str] = set()
    for rx in ID_REGEXES:
        found_ids.update(rx.findall(rationale))
    references_bound = 1.0 if all(tok in known for tok in found_ids) else 0.0

    version_in_force_respected = _version_in_force_respected(case, all_constraints, hits, assigned, gold, overall_correct)

    return {
        "overall_correct": overall_correct,
        "severity_distance": severity_distance,
        "hard_block_correct": hard_block_correct,
        "hard_block_false_alarm": hard_block_false_alarm,
        "hard_block_no_false_alarm": hard_block_no_false_alarm,
        "rules_hit_precision": rules_hit_precision,
        "rules_hit_recall": rules_hit_recall,
        "rules_hit_f1": rules_hit_f1,
        "rule_verdict_accuracy": rule_verdict_accuracy,
        "approval_path_correct": approval_path_correct,
        "verb_correct": verb_correct,
        "citation_grounded": citation_grounded,
        "citation_relevant": citation_relevant,
        "citable_coverage": citable_coverage,
        "citations_present": citations_present,
        "causal_clean": causal_clean,
        "references_bound": references_bound,
        "version_in_force_respected": version_in_force_respected,
    }


def _version_in_force_respected(
    case: dict,
    constraints: dict[str, dict],
    hits: list[dict],
    assigned: dict[int, str],
    gold: dict,
    overall_correct: float,
) -> float | None:
    docs = [_as_dict(d) for d in _as_list(case.get("documents"))]
    versions_by_doc: dict[str, set[int]] = {}
    for d in docs:
        versions_by_doc.setdefault(str(d.get("doc_id")), set()).add(int(d.get("version", 0)))
    multi = {doc for doc, vs in versions_by_doc.items() if len(vs) > 1}
    if not multi:
        return None
    in_force = _as_dict(gold.get("version_in_force"))
    affected = [cid for cid in _as_list(gold.get("rules_hit")) if cid in constraints and constraints[cid].get("doc_id") in multi]
    if not affected:
        return overall_correct
    hit_by_cid = {cid: hits[hi] for hi, cid in assigned.items()}
    checked = 0
    ok = True
    for cid in affected:
        g = constraints[cid]
        hit = hit_by_cid.get(cid)
        if hit is None:
            continue
        limit = hit.get("limit")
        if limit is None or limit == "":
            continue
        checked += 1
        if thresholds_equal(limit, g.get("threshold"), g.get("unit"), rescale=True):
            continue
        ok = False  # either the other version's threshold or something else entirely
    if not checked:
        return overall_correct
    return 1.0 if ok else 0.0


INGESTION_METRICS = (
    "constraint_precision", "constraint_recall", "constraint_f1", "threshold_exact",
    "scope_attribution", "effective_date_exact", "distractor_excluded", "evidence_grounded",
    "evidence_relevant", "evidence_misgrounded_rate", "evidence_ungrounded_rate",
)
VERDICT_METRICS = (
    "overall_correct", "severity_distance", "hard_block_correct", "hard_block_false_alarm",
    "hard_block_no_false_alarm", "rules_hit_precision", "rules_hit_recall", "rules_hit_f1",
    "rule_verdict_accuracy", "approval_path_correct", "verb_correct", "citation_grounded",
    "citation_relevant", "citable_coverage", "citations_present", "causal_clean",
    "references_bound", "version_in_force_respected",
)
# metrics where lower is better (everything else: higher is better)
LOWER_IS_BETTER = ("evidence_misgrounded_rate", "evidence_ungrounded_rate", "hard_block_false_alarm")
