"""Case loading.

Reads the dataset layout

    <data>/specs/constraints.json      list[Constraint]
    <data>/specs/documents.json        list[Document]   (Rendering.path is relative to <data>/corpus)
    <data>/corpus/<path>               rendered documents (markdown)
    <data>/scenarios/scenarios.jsonl   one Scenario per line

and turns it into self-contained case dicts for the two tasks. A case carries everything
the adapters and graders need, so a trajectory file that stores the case is a complete
record of the grader inputs.

Ingestion case (one per rendering)::

    {"case_id": rendering_id, "task": "ingestion", "rendering_id", "doc_id", "fund",
     "doc_type", "title", "version", "variant_kind", "style", "effective_from",
     "text", "constraint_ids", "gold": [Constraint, ...] (non-distractor rows),
     "distractors": [Constraint, ...]}

Verdict case (one per scenario)::

    {"case_id": scenario_id, "task": "verdict", "scenario_id", "fund", "decision_type",
     "as_of", "proposal", "portfolio", "variant_kind", "variant_of", "tags",
     "documents": [{"rendering_id", "doc_id", "version", "effective_from", "variant_kind",
                    "constraint_ids", "text"}, ...],
     "constraints": {constraint_id: Constraint, ...},   # every rule of every supplied document
     "gold": Gold}
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from bench.schema import validate_constraint, validate_scenario

TASKS = ("ingestion", "verdict")


@dataclass
class Dataset:
    root: Path
    constraints: list[dict]
    documents: list[dict]
    scenarios: list[dict]
    corpus: dict[str, str] = field(default_factory=dict)  # rendering_id -> text

    @property
    def constraints_by_id(self) -> dict[str, dict]:
        return {c["id"]: c for c in self.constraints}

    @property
    def renderings_by_id(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for doc in self.documents:
            for r in doc["renderings"]:
                out[r["rendering_id"]] = r
        return out

    @property
    def documents_by_id(self) -> dict[str, dict]:
        return {d["doc_id"]: d for d in self.documents}


def _read_json(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_dataset(data_dir: str | Path, validate: bool = True, skip_invalid: bool = False) -> Dataset:
    """Load the dataset. With ``validate`` the specs are checked against schema.py and every
    reference (constraint ids, rendering ids) must resolve; ``skip_invalid`` drops scenarios
    and renderings with dangling references (printing a warning) instead of raising."""
    root = Path(data_dir)
    constraints = _read_json(root / "specs" / "constraints.json")
    documents = _read_json(root / "specs" / "documents.json")
    scenarios_path = root / "scenarios" / "scenarios.jsonl"
    scenarios = _read_jsonl(scenarios_path) if scenarios_path.exists() else []
    ds = Dataset(root=root, constraints=constraints, documents=documents, scenarios=scenarios)
    missing_files: list[str] = []
    for doc in documents:
        kept = []
        for r in doc["renderings"]:
            path = root / "corpus" / r["path"]
            if not path.exists():
                missing_files.append(f"{r['rendering_id']} -> {path}")
                if skip_invalid:
                    continue
            else:
                ds.corpus[r["rendering_id"]] = path.read_text(encoding="utf-8")
            kept.append(r)
        doc["renderings"] = kept
    if missing_files and not skip_invalid:
        raise FileNotFoundError("missing corpus files: " + "; ".join(missing_files))
    if validate:
        for c in constraints:
            validate_constraint(c)
        for s in scenarios:
            validate_scenario(s)
        problems = _check_references(ds)
        if problems and not skip_invalid:
            raise ValueError("dataset references do not resolve:\n  " + "\n  ".join(problems))
        if problems:
            bad = _scenarios_with_problems(ds)
            ds.scenarios = [s for s in ds.scenarios if s["scenario_id"] not in bad]
            sys.stderr.write(f"[cases] skipped {len(bad)} scenarios with dangling references; "
                             f"{len(problems)} problems, first: {problems[0]}\n")
    return ds


def _check_references(ds: Dataset) -> list[str]:
    cbi = ds.constraints_by_id
    rbi = ds.renderings_by_id
    problems: list[str] = []
    for doc in ds.documents:
        for v in doc["versions"]:
            for cid in v["constraint_ids"]:
                if cid not in cbi:
                    problems.append(f"{doc['doc_id']} v{v['version']} references unknown constraint {cid}")
    for s in ds.scenarios:
        for rid in s["documents"]:
            if rid not in rbi:
                problems.append(f"{s['scenario_id']} references unknown rendering {rid}")
        for cid in s["gold"]["rules_hit"] + s["gold"]["citable_constraint_ids"]:
            if cid not in cbi:
                problems.append(f"{s['scenario_id']} gold references unknown constraint {cid}")
    return problems


def _scenarios_with_problems(ds: Dataset) -> set[str]:
    cbi = ds.constraints_by_id
    rbi = ds.renderings_by_id
    bad: set[str] = set()
    for s in ds.scenarios:
        if any(rid not in rbi for rid in s["documents"]):
            bad.add(s["scenario_id"])
        if any(cid not in cbi for cid in s["gold"]["rules_hit"] + s["gold"]["citable_constraint_ids"]):
            bad.add(s["scenario_id"])
        for rid in s["documents"]:
            r = rbi.get(rid)
            if r is None:
                continue
            doc = ds.documents_by_id[r["doc_id"]]
            ver = next((v for v in doc["versions"] if v["version"] == r["version"]), None)
            if ver is None or any(cid not in cbi for cid in ver["constraint_ids"]):
                bad.add(s["scenario_id"])
    return bad


def _version_record(doc: dict, version: int) -> dict:
    for v in doc["versions"]:
        if v["version"] == version:
            return v
    raise KeyError(f"{doc['doc_id']} has no version {version}")


def build_ingestion_cases(ds: Dataset) -> list[dict]:
    cbi = ds.constraints_by_id
    cases = []
    for doc in ds.documents:
        for r in doc["renderings"]:
            ver = _version_record(doc, r["version"])
            rows = [cbi[cid] for cid in ver["constraint_ids"]]
            gold = [c for c in rows if not c.get("distractor")]
            distractors = [c for c in rows if c.get("distractor")]
            cases.append(
                {
                    "case_id": r["rendering_id"],
                    "task": "ingestion",
                    "rendering_id": r["rendering_id"],
                    "doc_id": doc["doc_id"],
                    "fund": doc["fund"],
                    "doc_type": doc["doc_type"],
                    "title": doc["title"],
                    "version": r["version"],
                    "variant_kind": r["variant_kind"],
                    "style": r.get("style"),
                    "effective_from": ver["effective_from"],
                    "text": ds.corpus[r["rendering_id"]],
                    "constraint_ids": list(ver["constraint_ids"]),
                    "gold": gold,
                    "distractors": distractors,
                }
            )
    return cases


def build_verdict_cases(ds: Dataset) -> list[dict]:
    cbi = ds.constraints_by_id
    rbi = ds.renderings_by_id
    dbi = ds.documents_by_id
    cases = []
    for s in ds.scenarios:
        docs = []
        constraints: dict[str, dict] = {}
        for rid in s["documents"]:
            r = rbi[rid]
            doc = dbi[r["doc_id"]]
            ver = _version_record(doc, r["version"])
            docs.append(
                {
                    "rendering_id": rid,
                    "doc_id": doc["doc_id"],
                    "version": r["version"],
                    "effective_from": ver["effective_from"],
                    "variant_kind": r["variant_kind"],
                    "constraint_ids": list(ver["constraint_ids"]),
                    "text": ds.corpus[rid],
                }
            )
            for cid in ver["constraint_ids"]:
                constraints[cid] = cbi[cid]
        cases.append(
            {
                "case_id": s["scenario_id"],
                "task": "verdict",
                "scenario_id": s["scenario_id"],
                "fund": s["fund"],
                "decision_type": s["decision_type"],
                "as_of": s["as_of"],
                "proposal": s["proposal"],
                "portfolio": s["portfolio"],
                "variant_kind": s["variant_kind"],
                "variant_of": s.get("variant_of"),
                "tags": list(s.get("tags", [])),
                "documents": docs,
                "constraints": constraints,
                "gold": s["gold"],
            }
        )
    return cases


def build_cases(ds: Dataset, task: str) -> list[dict]:
    if task == "ingestion":
        return build_ingestion_cases(ds)
    if task == "verdict":
        return build_verdict_cases(ds)
    raise ValueError(f"unknown task {task!r}")


def corpus_for_case(case: dict) -> dict[str, str]:
    """rendering_id -> text for the renderings a case supplies (grader input)."""
    if case["task"] == "ingestion":
        return {case["rendering_id"]: case["text"]}
    return {d["rendering_id"]: d["text"] for d in case["documents"]}


def constraints_for_case(case: dict) -> dict[str, dict]:
    if case["task"] == "ingestion":
        out = {c["id"]: c for c in case["gold"]}
        out.update({c["id"]: c for c in case.get("distractors", [])})
        return out
    return dict(case["constraints"])


def data_file_hashes(data_dir: str | Path) -> dict[str, str]:
    """sha256 of every dataset file, keyed by path relative to the data dir."""
    root = Path(data_dir)
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out
