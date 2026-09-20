# gnosis-harness-bench

A controlled ablation that measures what a decision-ledger harness (gnosis) adds to a foundation model on two tasks, against the model vendor's own harness given the same documents:

1. **Ingestion**: extract the binding rules from an investment policy document.
2. **Verdict**: evaluate a proposed investment decision against the rules in force at a date, with grounded citations, an approval path and a recommendation verb.

Everything is paired by case, replicated, and analysed with case-level bootstrap intervals, exact McNemar tests and Holm correction. The protocol is locked in `PREREGISTRATION.md`.

## Layout

```
bench/
  schema.py              data contracts (constraints, documents, scenarios, outputs, result rows)
  policy_semantics.md    the verdict semantics used by the engine and restated in every system prompt
  generate_specs.py      seeded ground-truth rule specs: 5 funds x 8 documents, amendments, carve-outs, hard gates, distractors
  render_plan.py         which prose renderings each document needs (canonical, paraphrase, adversarial)
  verify_corpus.py       checks rendered prose against the specs (thresholds, scopes, no stray numbers)
  reference_engine.py    deterministic gold verdicts
  generate_scenarios.py  seeded scenarios with engine-asserted outcomes and variants
  cases.py               case loading for both tasks
  graders.py             atomic deterministic graders
  runner.py              replicated, resumable execution with error sidecar and model assertion
  stats.py               Wilson, case-level and paired bootstrap, McNemar, pass^k, kappa, Holm, noise floor, MDE
  report.py              report generation
  adapters/              oracle, null, mock, claude_h0, claude_h1, claude_h2, gnosis_stub
data/
  specs/                 constraints.json, documents.json, rendering_plan.json, by_fund/
  corpus/<FUND>/         rendered markdown documents (94 renderings)
  scenarios/             scenarios.jsonl (833 scenarios)
results/<run_id>/        results.jsonl, errors.jsonl, trajectories/, run_manifest.json, report.md
tests/                   instrument tests (stats coverage, graders, runner, engine)
```

## Regenerate the dataset

```bash
python3 -m bench.generate_specs --out data/specs
python3 -m bench.render_plan --specs data/specs --out data/specs/rendering_plan.json
# prose renderings are authored against the plan; verify them:
python3 -m bench.verify_corpus --specs data/specs --corpus data/corpus
python3 -m bench.generate_scenarios --specs data/specs --out data/scenarios/scenarios.jsonl
```

## Validate the instrument (no API key needed)

```bash
python3 -m pytest tests -q
python3 -m bench.runner --task verdict --conditions oracle,null,mock:p=0.7,g=0.8 --reps 5 --data data --out results/instrument
python3 -m bench.report --run results/instrument --baseline null --primary overall_correct,citable_coverage
```

## Run the vendor-harness baselines (needs ANTHROPIC_API_KEY)

```bash
python3 -m bench.runner --task ingestion --conditions H0,H1 --reps 5 --data data --out results/live-ingestion
python3 -m bench.runner --task verdict   --conditions H0,H1,H2 --reps 5 --data data --out results/live-verdict
python3 -m bench.report --run results/live-verdict --baseline H1 --primary overall_correct,citable_coverage
```

## Run the gnosis conditions (needs the gnosis repo)

`bench/adapters/gnosis_stub.py` documents the integration points: a policy-evaluation call (proposal, portfolio, as_of, documents) returning a `VerdictOutput`, an ingestion call returning an `IngestionOutput`, and four ablation flags. Map the bench's 13 decision-type ids to gnosis's real ids in `config/decision_type_map.json` before running.

## Status of execution

| Step | State |
|---|---|
| Dataset generated and engine-asserted | done |
| Corpus rendered and verified | done: 94 renderings, 71,745 words, verifier clean |
| Blind label audit (20 renderings, 130 rules, no access to specs) | done: precision 0.977, recall 0.992, kappa 0.925 (`data/labels/*_audit.txt`) |
| Statistical estimators validated by simulation | done, `tests/test_stats.py` (49 tests) |
| Oracle, null and mock instrument checks on the full dataset | done: `results/instrument-verdict/report.md`, `results/instrument-ingestion/report.md` (0 errors, 18,540 graded rows) |
| Full test suite | 103 tests pass |
| Live vendor-harness runs (H0, H1, H2) | blocked: no API credentials in this environment |
| gnosis conditions | blocked: gnosis repository not accessible to this session |
