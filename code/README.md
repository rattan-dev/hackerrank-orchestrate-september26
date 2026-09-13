# Buy or Wait? Financial Agent

This submission uses a hybrid, safety-first design:

1. A validated fact layer reads profiles, events, exact dated exchange rates,
   payment offers, messages, and reviewed OCR facts.
2. A recurrence layer keeps separate obligations by normalized description,
   scores recurrence confidence, resolves lifecycle evidence, and distinguishes
   stable, first-cycle, temporary, arrears, permanent, and stale income states.
3. A deterministic request-anchored 90-day simulator evaluates full, partial,
   installment, wait, and not-proceed outcomes against the user's minimum balance.
4. A constrained search evaluates at most three explicitly permitted flexible
   spending changes and removes changes that are not needed for the selected plan.
5. A separate immutable-ledger implementation independently recomputes baseline
   capacity and replays chosen payments. It does not call the planner's
   `Forecaster.trajectory` or `Forecaster.is_safe` methods.

Messages, images, and optional model output are untrusted evidence. They may
clarify facts, but cannot select a recommendation or weaken a reserve. The final
decision and validation path is deterministic.

## Exact verified environment

- Python `3.12.14` (the code supports Python 3.10+ and has no package dependency)
- Tesseract `5.3.4`, Leptonica `1.82.0` (only needed when a reviewed image-cache
  entry is absent)
- Input schema `buy-or-wait-v1`
- Output schema `buy-or-wait-output-v1`
- Image-fact cache schema `reviewed-image-facts-v2`

## Run

From the repository root:

```bash
python3 code/main.py --output output.csv
```

To print public-example field diagnostics while generating output:

```bash
python3 code/main.py --check-samples --output output.csv
```

Optional semantic extraction accepts an OpenAI-compatible chat endpoint:

```bash
export AFFORDABILITY_LLM_URL="https://provider.example/v1/chat/completions"
export AFFORDABILITY_LLM_API_KEY="..."
export AFFORDABILITY_LLM_MODEL="model-name"
python3 code/main.py --use-llm --output output.csv
```

The final submitted run did not have an endpoint configured and made zero model
calls. The guarded path is covered with malformed output, invalid-field,
injection, timeout, and deterministic-fallback tests; no live use is claimed.

## Forecast and evidence semantics

- The 90-day window is inclusive and fixed to `request_date` through
  `request_date + 90 days`. `earliest_date_for_full_payment` is the first date in
  that same window on which one full payment remains safe through the window end;
  it is not a rolling 90-day window from every candidate date.
- The current profile balance is the opening balance. Settled history trains
  recurrence but is not subtracted again.
- Pending/scheduled debits are reserved. Pending credits, unrealized investments,
  failed transactions, cancelled transactions, and stale unconfirmed income are
  excluded.
- A scheduled row replaces only a matching recurrence occurrence with the same
  date, category, and normalized description; distinct arrears and obligations
  remain separate.
- Explicit event evidence is resolved first, then the newest record per source.
  Unresolved cross-source debit conflicts use the larger amount and then earlier
  date. Diagnostics preserve each source, timestamp, action, original/resolved
  amount and date, plus the applied rule.
- Salary handling preserves distinct current household streams, but does not
  project a stream whose next expected payroll is already more than seven days
  overdue without confirmation. Temporary changes apply for one cycle and revert.
- Exact supplied exchange rates are mandatory for the resolved settlement date;
  missing pairs/dates fail closed.
- Reviewed OCR cache rows record image SHA-256, currency, selected label,
  extraction method, review status, and confidence. File hashes and currencies
  are validated before use.
- Installment schedules are copied exactly from eligible offers. Partial payment
  has exactly two payments under the challenge contract.
- Protected/fixed/disallowed expenses cannot be changed. Reported safe capacity
  is rounded down to cents.

## Test, diagnose, and audit

```bash
python3 -m unittest discover -s code/evaluation -p 'test_*.py' -v
python3 code/evaluation/run_mutation_checks.py
python3 code/evaluation/diagnose_public_examples.py
python3 code/evaluation/calibrate_forecast.py
python3 code/evaluation/generate_manifest.py
python3 code/evaluation/run_quality_checks.py --allow-partial --json-out code/evaluation/latest_quality.json
```

The strict audit intentionally returns nonzero if any check is `PARTIAL` or
`FAIL`. The `--allow-partial` flag permits `PARTIAL` for reporting but still
returns nonzero on a failure. In this version QC-05 remains `PARTIAL` because the
published accuracy targets are not met; the other 14 checks pass.

Artifacts:

- `evaluation/quality_checklists.md`: requirements, flaw prevention, and 15 checks
- `evaluation/improvement_checklist.md`: judge feedback traced to implementation
- `evaluation/public_diagnostics.json`: per-example streams, dated flows,
  provenance, candidate ranking, selection, and mismatch attribution
- `evaluation/calibration_report.json`: general statistic comparison and rejected
  unsafe label-chasing alternative
- `evaluation/final_quality.json`: frozen machine-readable final audit result
- `evaluation/source_manifest.sha256`: checksums of submitted source/config/docs
- `evaluation/quality_report.md`: final evidence, metrics, limits, and reproduction
