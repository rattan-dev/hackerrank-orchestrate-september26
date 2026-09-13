# Buy or Wait? Final Quality Report

## Outcome

The hardened submission has **14 PASS, 1 PARTIAL, and 0 FAIL** across the 15
defined checks. It generates and validates all 250 decisions, passes 47 tests and
six deliberate output-mutation checks, produces 250 distinct grounded
explanations, and is deterministic. QC-05 is intentionally `PARTIAL`: the stated
public-example accuracy targets are not met. The strict audit therefore exits
nonzero; `--allow-partial` is required only to report that known partial result.

This is a safety result, not a claim of perfect hidden-label accuracy. Public
answers are used only by offline diagnostics and never by prediction modules.

## Final metrics

| Metric | Result |
| --- | ---: |
| Unit/contract/property tests | 47/47 PASS |
| Output mutation checks | 6/6 rejected as expected |
| Evaluation requests / valid rows | 250 / 250 |
| Independent arithmetic ledger replays | 250/250 PASS |
| Unique explanations | 250/250 |
| Maximum explanation length | 872 characters |
| Deterministic regeneration | PASS |
| Output CSV SHA-256 | `90d83a7af413644b3d6405a0a40975d2d6e8739f0ee534ff91c942776e77d59e` |
| Canonical decision-row SHA-256 | `8a0ecc471e8d76a7f46fb6c46c5e2dc1577f5e321b1a771e0a73c1586a569b69` |
| Final-run model calls / tokens / cost | 0 / 0 / USD 0 |

Decision distribution: 69 full payment, 11 partial payment, 61 installments, 50
wait, and 59 not recommended. All five required outcomes are exercised.

### Public-example diagnostics (25 examples)

| Field | Actual | Published target | Result |
| --- | ---: | ---: | --- |
| Affordability status | 20/25 | 23/25 | PARTIAL |
| Recommended method | 21/25 | 23/25 | PARTIAL |
| Payment plan | 20/25 | 23/25 | PARTIAL |
| Earliest full-payment date | 19/25 | 22/25 | PARTIAL |
| Spending changes | 21/25 | 23/25 | PARTIAL |
| Safe amount exact | 3/25 | diagnostic only | reported |
| Safe amount within 2% of request | 14/25 | 22/25 | PARTIAL |
| Safe amount within 5% of request | 21/25 | diagnostic only | reported |

Mean absolute safe-amount error is 3.087% of requested amount. Five public cases
change status or method (06, 08, 11, 13, 21); request 19 additionally changes the
two-part plan because its safe-today estimate differs. `public_diagnostics.json`
contains every opening balance/reserve, stream, confidence score, dated flow,
evidence trace, candidate rank key, projected low, selected row, and mismatch.

The calibration audit compared mean, median, lower quartile, and upper quartile
for non-salary recurring amounts. Lower-quartile estimation raised method accuracy
to 23/25 and date accuracy to 22/25, but worsened mean safe-amount error from
3.087% to 4.007% and systematically under-reserved observed essentials. It was
rejected as unsafe public-label chasing. Mean remains the general, lowest-error
conservative choice. Because no label is fitted or read by prediction code,
removing any one public answer leaves every prediction unchanged.

## Quality-check evaluation

| Check | Result | Evidence |
| --- | --- | --- |
| QC-01 Contract traceability | PASS | The three checklists and judge checklist map contract items to modules, tests, diagnostics, and this report. |
| QC-02 Dataset validation | PASS | Required files, schema versions, unique keys, references, dates, enums, raw nonnegative amounts, options, currencies, image hashes, and cross-user links validate or fail closed. |
| QC-03 Full-run contract | PASS | Exactly 250 ordered rows pass strict schema and cross-field validation. |
| QC-04 Independent ledger replay | PASS | Immutable ledger arithmetic independently recomputes capacity and replays plans without calling planner trajectory/safety functions. |
| QC-05 Public-example regression | **PARTIAL** | All metrics and targets are reported above; none of the six published target thresholds is hidden or relabeled. |
| QC-06 Cash-state tests | PASS | Pending/settled/failed/cancelled/reversed, retry, lifecycle, scheduled-instance, distinct arrears, and same-day behavior pass. |
| QC-07 Forecast tests | PASS | Confidence, separate streams, salary state, stale income, variable spend, month-end/leap dates, and fixed 90-day boundary pass. |
| QC-08 Plan tests | PASS | All five outcomes, preference gates, deadlines, exact offers, fee totals, partial sums, minimal changes, and ranking pass. |
| QC-09 Evidence security | PASS | Injection, ambiguous numbers, malformed/invalid/failed model output, missing images, future messages, OCR labels, and provenance pass. |
| QC-10 Currency | PASS | Exact resolved-date conversions pass; absent rate/pair fails closed; an amended cross-source conflict fixture uses the winning date's exact rate. |
| QC-11 Output consistency | PASS | Enums, precision, chronology, status/method/plan/date relationships, changes, and explanation limits pass. |
| QC-12 Determinism | PASS | Repeated full runs yield byte-identical rows and output. |
| QC-13 Leakage/security | PASS | No expected-answer read, request-ID prediction branch, credential, or unsafe network dependency occurs in the decision path or archive. |
| QC-14 Packaging | PASS | Archive CRC/content allowlist and clean-extraction tests/output regeneration pass; dataset/log/cache/credential files are absent. |
| QC-15 Efficiency/usage | PASS | Audit runtime is recorded in machine JSON; final generation makes no network, model, or OCR calls and has zero token cost. |

## Material defects found and fixed

- Explicit future-debit amounts could be overwritten by a category average. Each
  explicit row now retains its resolved amount; one-for-one debit monotonicity is
  tested.
- Same-category obligations could be merged. Recurrence grouping now includes a
  normalized description, while a matching scheduled instance replaces only its
  own projected occurrence.
- Message conflict handling was implicit. Diagnostics now retain structured source,
  timestamp, action, original/resolved amount/date, and rule. The newest state per
  source wins; unresolved debit sources choose the larger amount then earlier date.
- A rent receipt cache used the gross receipt rather than unpaid balance, and a
  grocery cache used a misread item figure. Reviewed label-based facts were fixed,
  hashed, versioned, and validated.
- A single scheduled/confirmed salary could erase another household salary, while
  a missing historical paycheck could be projected indefinitely. Distinct current
  streams are retained; overdue unconfirmed streams are not projected; temporary
  changes revert after one cycle.
- Linked rows risked being discarded by link presence alone. Lifecycle state and
  meaning now govern supersession, retries, refunds, and corrections.
- Negative raw values could be absolutized before validation; cross-user evidence
  could be joined; future messages could affect current decisions; and upward cent
  rounding could overstate safety. All now fail closed or are date-gated.
- Selected spending changes could include unnecessary actions. Each action is now
  removed in turn and the plan replayed; a property test proves every retained
  action is individually necessary.
- Explanations were generic. They now identify a material obligation/date, counted
  confirmed inflow and excluded pending credit when relevant, installment count/
  fee/total/ranking, wait-triggering inflow, authorized savings/actions, priorities,
  projected low, and forecast uncertainty.

## Independence and remaining limitations

1. The verifier's balance arithmetic and capacity calculation are independent of
   the planning trajectory/safety methods, but both consume the same normalized
   cash-flow facts from `Forecaster.daily_cashflows`. A fully independent second
   parser/forecast model would add defense in depth but also duplicate complex
   semantics and was not represented as completed.
2. Variable essential spending and recurrence from short histories remain the main
   accuracy risk. Public safe amounts demonstrate residual calibration error. The
   implementation refuses to lower essential estimates or relax minimum balances
   merely to match examples.
3. The 16 supplied images have reviewed, hash-bound cache facts. Unseen document
   layouts still depend on Tesseract label extraction and fail closed if no isolated
   payable amount is found.
4. No optional model endpoint was configured. Adversarial mocks verify schema and
   fallback logic, but live provider latency/format behavior was not exercised and
   is not claimed.
5. The chosen earliest-date interpretation uses one fixed request-anchored 90-day
   window, as the safe plan must preserve that horizon. A rolling 90 days from each
   future candidate date was considered but rejected because it changes the stated
   capacity contract and requires unsupported cash flows beyond the supplied window.

## Reproduction

```bash
python3 -m unittest discover -s code/evaluation -p 'test_*.py' -v
python3 code/evaluation/run_mutation_checks.py
python3 code/evaluation/diagnose_public_examples.py
python3 code/evaluation/calibrate_forecast.py
python3 code/main.py --check-samples --output output.csv
python3 code/evaluation/generate_manifest.py
python3 code/evaluation/run_quality_checks.py --allow-partial --json-out code/evaluation/latest_quality.json
```

Run `python3 code/evaluation/run_quality_checks.py` without `--allow-partial` to
confirm mandatory partial results correctly cause a nonzero exit.
