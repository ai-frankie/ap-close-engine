# AP Reconciliation & Close Engine

An automated accounts-payable month-end close: 3-way match (PO/receipt/invoice), duplicate-payment detection, AP subledger-to-GL reconciliation, GRNI accrual identification, and vendor-statement reconciliation — plus an **independent reviewer** that re-derives the truth from raw data and catches a preparer's errors. Built by an accountant, in code.

> **Thesis:** AP fails in two expensive ways: paying for something you didn't order (match failure) and paying the same invoice twice (duplicate). This engine makes both visible *before* payment — and makes every figure traceable: invoice → PO → receipt → GL, tied and control-checked.

All data is **synthetic** (fictional vendors). No real financial data.

---

## What it does

| Script | Role | Output |
|---|---|---|
| `ap_match.py` | **3-way match** — validates every invoice against its PO (price, approval) and goods receipt (qty) | Console match/exception report |
| `ap_duplicates.py` | **Duplicate-payment detection** — flags same vendor + amount with normalized invoice# or near payment dates | Console duplicate report |
| `ap_close.py` | AP close — aging, open-AP subledger, GL AP-control reconciliation, GRNI accrual, 5 control checks | `AP_Health_Report.xlsx` |
| `ap_controls.py` | **SOX-style controls register** — 8 named controls in controller language (data integrity, manual-JE detection, cutoff, GRNI-to-GL tie, SoD) | Console controls register |
| `ap_vendor_recon.py` | **Vendor-statement reconciliation** — matches our open AP to vendor open items at the invoice level | Console vendor-by-vendor report |
| `ap_review.py` | **Independent QA reviewer** — recomputes truth from raw data, audits a prepared workbook, catches planted errors | `AP_Close_Review.xlsx` |
| `gen_data.py` | Generates deterministic synthetic data (seeded) with 5 planted breaks | CSV files |

## Internal controls

The engine performs a **SOX-style controls register** written from a controller's point of view — every control states its objective, the risk it mitigates, the financial-statement assertion it supports, and a PASS/FAIL/REVIEW result with plain-English flags. Full narrative in **[CONTROLS.md](CONTROLS.md)**.

```
[FAIL] C8 Manual / top-side JE to AP control account (subledger bypass)
        assertion: existence/occurrence | AUTOMATED | 1 manual JE(s) to acct 2000 netting +5,000.00
          - MANUAL JE TO AP CONTROL — Entry JE700381, net +5,000.00; Source='Manual JE'
            not a subledger feed; no Invoice_Ref. Obtain JE approval before sign-off.
[FAIL] C12 GRNI accrual booked to GL 2150 (unrecorded-liability check)
          - GRNI of 1,500.00 computed from receipts is NOT booked to GL 2150. Record before close.
```

The headline control is **C8 — manual / top-side journal entries to the AP control account**: a credit posted straight to acct 2000 with no invoice behind it and a non-subledger source. It's the classic management-override red flag auditors hunt for, and it's a first-class named control here, not a buried variable.

## Verified output

`ap_match.py`:
```
3-WAY MATCH: 122 matched, 2 exceptions
  [PRICE_VARIANCE] INV-3001: billed 130.0 vs PO 100.0 (unit var 30.0%, total 1,300.00 vs 1,000.00)
  [PO_NOT_APPROVED] INV-5001: PO PO-5001 status is 'Draft'
```

`ap_duplicates.py`:
```
DUPLICATE PAYMENTS: 1 suspected
  [NORMALIZED_MATCH] Acme Corp $4,321.00 ['PMT-9001', 'PMT-9002'] invoices=['INV-2001', 'INV-2001-R']
```

`ap_close.py`:
```
AP Subledger 1,186,395.48 | GL AP 1,195,037.48 | Variance 8,642.00 | Residual 8,642.00
GRNI accrual needed: 1,500.00 (1 items)

CONTROL CHECKS:
  [PASS] GL balanced (debits = credits)
  [PASS] Aging buckets sum to AP subledger
  [FAIL] AP subledger ties to GL (residual 8,642.00)
  [PASS] GRNI identified and flagged
  [PASS] No negative AP balances unresolved
```

The subledger-to-GL **FAIL is correct** — the planted breaks (duplicate invoice, unapproved PO) create real variance the control is supposed to surface, not smooth over.

## The reviewer catches planted errors

`ap_review.py` audits `AP_Close_Prepared_SAMPLE.xlsx` — a preparer's workbook with **three planted mistakes**: a doubled AP subledger, a GRNI accrual omission, and an unreported duplicate payment:

```
[FAIL] ap subledger: reported 2,372,790.96 / expected 1,186,395.48  -> ~2x double-counted
[OK]   gl ap control: 1,195,037.48
[FAIL] grni accrual: reported 0.00 / expected 1,500.00              -> omitted
[FAIL] duplicate count: reported 0.00 / expected 1.00               -> omitted
```

**Those `[FAIL]`s are the tool succeeding** — independent recomputation catching three preparer errors before they reach the GL or allow a duplicate payment through.

## Scope & limitations

Built to demonstrate AP controls logic, not as a hardened production system:

- **3-way match assumes single-line POs** with full receipts. Multi-line PO matching and partial-receipt tracking are documented future extensions.
- **Money is float, rounded to the cent** — not `decimal.Decimal`. Exact at realistic AP scale; a production system would use `Decimal`.
- **Fixed column schema** — expects specific headers. A production version needs a column-mapping layer and handling for tax, freight, and multi-currency.
- **In-memory.** Fine to hundreds of thousands of rows, not a streaming/DB design.
- **Synthetic data only**, fictional vendors. Business parameters (as-of date, price tolerance) are constants, not config.
- **Duplicate-detection pairwise comparisons are capped** per vendor+amount group (logged, never silently truncated).

## Tests

```bash
pip install -r requirements.txt pytest
pytest -v
```

`test_ap.py` — **35 tests**, run in CI on every push. They cover:
- 3-way match (price variance flagged, unapproved PO flagged, clean invoices pass)
- Duplicate detection (planted dup found, suffix normalization, no false positives)
- AP close (subledger, GL balance, aging sums, GRNI amount and PO identification)
- All 5 control checks individually (including that the subledger-GL tie *correctly fails* on planted breaks)
- Vendor-statement reconciliation (all vendors present, variances surfaced)
- Independent reviewer (planted errors caught, correct figures pass, clean workbook produces zero failures)

## Run it

Requires Python 3.11+ and `openpyxl`.

```bash
pip install -r requirements.txt
python gen_data.py        # generate synthetic data (deterministic)
python ap_match.py        # 3-way match
python ap_duplicates.py   # duplicate-payment detection
python ap_close.py        # AP close + controls
python ap_controls.py     # SOX-style controls register (controller language)
python ap_vendor_recon.py # vendor-statement reconciliation
python ap_review.py       # independent reviewer (catches planted errors)
```

No config, no network, no keys — runs on the included synthetic data out of the box.
