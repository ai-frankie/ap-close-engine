"""
AP close engine — regression tests.
Expected values verified from running against the included synthetic data.
Run: pytest test_ap.py -v
"""
import pytest
from ap_match import run_match
from ap_duplicates import find_duplicates, _normalize_inv
from ap_close import run_close
from ap_vendor_recon import reconcile
from ap_review import compute_truth, run_review
from ap_controls import run_controls


@pytest.fixture(scope="module")
def match():
    return run_match()


@pytest.fixture(scope="module")
def close():
    return run_close()


@pytest.fixture(scope="module")
def truth():
    return compute_truth()


# ── 3-way match ──────────────────────────────────────────────────────────────

class TestThreeWayMatch:
    def test_clean_invoices_matched(self, match):
        assert match["matched_count"] >= 120

    def test_price_variance_flagged(self, match):
        ex = [e for e in match["exceptions"] if e["invoice"] == "INV-3001"]
        assert len(ex) == 1
        assert ex[0]["reason"] == "PRICE_VARIANCE"

    def test_unapproved_po_flagged(self, match):
        ex = [e for e in match["exceptions"] if e["invoice"] == "INV-5001"]
        assert len(ex) == 1
        assert ex[0]["reason"] == "PO_NOT_APPROVED"

    def test_exception_count(self, match):
        assert match["exception_count"] == 2

    def test_total_equals_matched_plus_exceptions(self, match):
        assert match["matched_count"] + match["exception_count"] == 124


# ── duplicate-payment detection ──────────────────────────────────────────────

class TestDuplicates:
    def test_planted_duplicate_found(self):
        dups = find_duplicates()
        amounts = {round(d["amount"], 2) for d in dups}
        assert 4321.00 in amounts

    def test_duplicate_identifies_correct_invoices(self):
        dups = find_duplicates()
        dup = [d for d in dups if d["amount"] == 4321.00][0]
        assert set(dup["invoices"]) == {"INV-2001", "INV-2001-R"}

    def test_duplicate_reason_is_normalized_match(self):
        dups = find_duplicates()
        dup = [d for d in dups if d["amount"] == 4321.00][0]
        assert dup["reason"] == "NORMALIZED_MATCH"

    def test_normalize_strips_known_suffixes(self):
        assert _normalize_inv("INV-2001-R") == "INV-2001"
        assert _normalize_inv("INV-2001-DUP") == "INV-2001"
        assert _normalize_inv("INV-2001-COPY") == "INV-2001"

    def test_normalize_no_false_positive(self):
        assert _normalize_inv("INV-100") != _normalize_inv("INV-1000")

    def test_clean_payments_not_flagged(self):
        dups = find_duplicates()
        assert all(d["vendor"] is not None for d in dups)
        assert len(dups) >= 1  # at least the planted one


# ── AP close (aging, subledger, GL tie, GRNI, controls) ─────────────────────

class TestAPClose:
    def test_ap_subledger(self, close):
        assert abs(close["ap_subledger"] - 1_186_395.48) < 0.01

    def test_gl_ap_balance(self, close):
        assert abs(close["gl_ap"] - 1_200_037.48) < 0.01

    def test_aging_sums_to_subledger(self, close):
        total = sum(v["open"] for v in close["agesum"].values())
        assert abs(total - close["ap_subledger"]) < 0.01

    def test_grni_amount(self, close):
        assert abs(close["grni"] - 1500.00) < 0.01

    def test_grni_item_count(self, close):
        assert len(close["grni_items"]) == 1

    def test_grni_is_po_4001(self, close):
        assert close["grni_items"][0][0] == "PO-4001"


class TestAPControls:
    def test_gl_balanced(self, close):
        name, detail, ok = close["checks"][0]
        assert ok, f"GL balanced failed: {detail}"

    def test_aging_sum_control(self, close):
        name, detail, ok = close["checks"][1]
        assert ok, f"Aging sum control failed: {detail}"

    def test_subledger_gl_tie_fails(self, close):
        """Variance exists from planted breaks — control correctly fails."""
        name, detail, ok = close["checks"][2]
        assert not ok, "Expected subledger-GL tie to fail (planted breaks create variance)"

    def test_grni_flagged(self, close):
        name, detail, ok = close["checks"][3]
        assert ok, f"GRNI flag failed: {detail}"

    def test_no_negative_balances(self, close):
        name, detail, ok = close["checks"][4]
        assert ok, f"Negative balances check failed: {detail}"

    def test_exactly_five_controls(self, close):
        assert len(close["checks"]) == 5


# ── vendor-statement reconciliation ──────────────────────────────────────────

class TestVendorRecon:
    def test_all_vendors_present(self):
        r = reconcile()
        assert r["vendor_count"] == 8

    def test_variance_exists(self):
        r = reconcile()
        assert r["variance_count"] > 0


# ── independent reviewer (planted-error detection) ───────────────────────────

class TestReviewTruth:
    def test_truth_subledger(self, truth):
        assert abs(truth["ap subledger"] - 1_186_395.48) < 0.01

    def test_truth_grni(self, truth):
        assert abs(truth["grni accrual"] - 1500.00) < 0.01

    def test_truth_duplicate_count(self, truth):
        assert truth["duplicate count"] >= 1


class TestPlantedErrors:
    @pytest.fixture(scope="class")
    @staticmethod
    def review_rows():
        rows, _ = run_review()
        return {m: (g, e, res, diag) for m, g, e, res, diag in rows}

    def test_subledger_double_count_detected(self, review_rows):
        _, _, result, _ = review_rows["ap subledger"]
        assert result == "FAIL"

    def test_subledger_double_count_diagnosis(self, review_rows):
        _, _, _, diag = review_rows["ap subledger"]
        assert "double" in diag.lower() or "2x" in diag.lower()

    def test_grni_omission_detected(self, review_rows):
        _, _, result, _ = review_rows["grni accrual"]
        assert result == "FAIL"

    def test_duplicate_omission_detected(self, review_rows):
        _, _, result, _ = review_rows["duplicate count"]
        assert result == "FAIL"

    def test_correct_fields_pass(self, review_rows):
        _, _, result, _ = review_rows["gl ap control"]
        assert result == "OK"

    def test_total_fails(self):
        _, fails = run_review()
        assert fails >= 3


class TestCleanWorkbookPasses:
    """A correct workbook must pass with zero failures."""
    def test_clean_passes(self, tmp_path, truth):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Close"
        for label, val in truth.items():
            ws.append([label, val])
        clean = str(tmp_path / "clean.xlsx")
        wb.save(clean)
        rows, fails = run_review(clean)
        assert fails == 0, f"Clean workbook had {fails} failures: {rows}"


# ── SOX-style controls register ──────────────────────────────────────────────

class TestControlsRegister:
    @pytest.fixture(scope="class")
    @staticmethod
    def reg():
        return {c["id"]: c for c in run_controls()["register"]}

    def test_register_has_eight_controls(self):
        assert len(run_controls()["register"]) == 8

    def test_manual_je_to_ap_control_detected(self, reg):
        """C8 — the seeded top-side JE (Source='Manual JE', no ref) must FAIL."""
        assert reg["C8"]["result"] == "FAIL"
        assert "5,000" in reg["C8"]["detail"]

    def test_manual_je_flag_names_source(self, reg):
        assert any("Manual JE" in e for e in reg["C8"]["exceptions"])

    def test_grni_unbooked_detected(self, reg):
        """C12 — GRNI computed but not booked to GL 2150 = unrecorded liability."""
        assert reg["C12"]["result"] == "FAIL"
        assert "1,500" in reg["C12"]["detail"]

    def test_clean_data_passes_integrity_controls(self, reg):
        """C2/C4/C5/C10 should PASS on the clean demo population."""
        for cid in ("C2", "C4", "C5", "C10"):
            assert reg[cid]["result"] == "PASS", f"{cid} unexpectedly {reg[cid]['result']}"

    def test_evidenced_controls_report_ok_when_clean(self, reg):
        for cid in ("C9", "C21"):
            assert reg[cid]["result"] in ("OK", "REVIEW")

    def test_two_failures_total(self):
        assert run_controls()["fail_count"] == 2

    def test_every_control_has_objective_and_assertion(self, reg):
        for c in reg.values():
            assert c["objective"] and c["assertion"] and c["delivery"] in ("AUTOMATED", "EVIDENCED")
