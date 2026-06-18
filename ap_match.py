"""3-way match: PO <-> goods receipt <-> invoice, tolerance-based.
An invoice may be paid only if: a PO exists and is approved, goods were received
for at least the billed qty, and the billed unit price matches the PO within tolerance.
Run: python ap_match.py
"""
import csv, os

D = os.path.dirname(os.path.abspath(__file__))
PRICE_TOL = 0.01  # 1% unit-price tolerance


def fnum(x):
    try: return float(str(x).replace(",", ""))
    except (ValueError, TypeError): return None


def load(name, data_dir=None):
    p = os.path.join(data_dir or D, name)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


def run_match(data_dir=None):
    """Run 3-way match on PO/receipt/invoice data. Returns result dict."""
    d = data_dir or D
    pos = load("PO.csv", d)
    receipts = load("Receipts.csv", d)
    invs = load("AP_Invoices.csv", d)
    if not pos or not invs:
        raise ValueError("PO.csv and AP_Invoices.csv must exist and be non-empty in " + d)

    po_lookup = {}
    for r in pos:
        po_lookup[r["PO_Number"]] = {
            "price": fnum(r["Unit_Price"]),
            "qty": fnum(r.get("Qty_Ordered")) or 0,
            "status": (r.get("Status") or "").strip(),
        }

    recv_qty = {}
    for r in receipts:
        recv_qty[r["PO_Number"]] = recv_qty.get(r["PO_Number"], 0) + (fnum(r["Qty_Received"]) or 0)

    matched, exceptions = [], []
    for inv in invs:
        ref = (inv.get("PO_Number") or "").strip()
        qty = fnum(inv.get("Qty_Billed")) or 0
        price = fnum(inv.get("Unit_Price"))
        ino = inv.get("Invoice_Number")
        amt = fnum(inv.get("Amount")) or 0

        if ref not in po_lookup:
            exceptions.append({"invoice": ino, "reason": "NO_PO",
                               "detail": f"PO {ref} not found"})
            continue

        po = po_lookup[ref]

        if po["status"] != "Approved":
            exceptions.append({"invoice": ino, "reason": "PO_NOT_APPROVED",
                               "detail": f"PO {ref} status is '{po['status']}'"})
            continue

        if ref not in recv_qty:
            exceptions.append({"invoice": ino, "reason": "NO_RECEIPT",
                               "detail": f"no receipt for {ref}"})
            continue

        if qty > recv_qty[ref]:
            exceptions.append({"invoice": ino, "reason": "OVER_BILLED",
                               "detail": f"billed {qty} > received {recv_qty[ref]}"})
            continue

        pprice = po["price"]
        if pprice and price is not None and pprice > 0:
            unit_var = abs(price - pprice) / pprice
            po_total = round(po["qty"] * pprice, 2)
            inv_total = amt
            total_var = abs(inv_total - po_total) / po_total if po_total else 0
            if unit_var > PRICE_TOL or total_var > PRICE_TOL:
                exceptions.append({"invoice": ino, "reason": "PRICE_VARIANCE",
                                   "detail": f"billed {price} vs PO {pprice} "
                                             f"(unit var {unit_var:.1%}, "
                                             f"total {inv_total:,.2f} vs {po_total:,.2f})"})
                continue

        matched.append(ino)

    return {"matched": matched, "matched_count": len(matched),
            "exceptions": exceptions, "exception_count": len(exceptions)}


if __name__ == "__main__":
    r = run_match()
    print(f"3-WAY MATCH: {r['matched_count']} matched, "
          f"{r['exception_count']} exceptions")
    for e in r["exceptions"]:
        print(f"  [{e['reason']}] {e['invoice']}: {e['detail']}")
