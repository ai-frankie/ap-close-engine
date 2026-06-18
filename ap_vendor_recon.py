"""Vendor-statement reconciliation: our open AP vs vendor's open items.
Matches at the invoice level; surfaces timing differences (in-transit payments,
unapplied credits).
Run: python ap_vendor_recon.py
"""
import csv, os
from collections import defaultdict

D = os.path.dirname(os.path.abspath(__file__))


def fnum(x):
    try: return float(str(x).replace(",", ""))
    except (ValueError, TypeError): return None


def load(name, data_dir=None):
    p = os.path.join(data_dir or D, name)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


def reconcile(data_dir=None):
    """Reconcile our AP invoices/payments against vendor statements.
    Returns per-vendor results + portfolio summary."""
    d = data_dir or D
    invs = load("AP_Invoices.csv", d)
    pays = load("Payments.csv", d)
    vstmt = load("Vendor_Statement.csv", d)
    if not invs:
        raise ValueError("AP_Invoices.csv must exist and be non-empty in " + d)

    # our open balance per vendor+invoice
    paid = defaultdict(float)
    for p in pays:
        paid[p.get("Invoice_Number")] += fnum(p.get("Amount")) or 0

    ours = defaultdict(dict)
    for inv in invs:
        vendor = inv.get("Vendor")
        ino = inv.get("Invoice_Number")
        amt = (fnum(inv.get("Amount")) or 0) - paid.get(ino, 0)
        if amt > 0.005:
            ours[vendor][ino] = round(amt, 2)

    # vendor's view
    theirs = defaultdict(dict)
    for s in vstmt:
        vendor = s.get("Vendor")
        ino = s.get("Invoice_Number")
        theirs[vendor][ino] = round(fnum(s.get("Amount")) or 0, 2)

    all_vendors = sorted(set(list(ours.keys()) + list(theirs.keys())))
    results = []
    for v in all_vendors:
        our_invs = ours.get(v, {})
        their_invs = theirs.get(v, {})
        our_total = round(sum(our_invs.values()), 2)
        their_total = round(sum(their_invs.values()), 2)
        variance = round(our_total - their_total, 2)

        # invoice-level detail
        all_inv = sorted(set(list(our_invs.keys()) + list(their_invs.keys())))
        details = []
        for ino in all_inv:
            o = our_invs.get(ino, 0)
            t = their_invs.get(ino, 0)
            diff = round(o - t, 2)
            if abs(diff) > 0.005:
                if o > 0 and t == 0:
                    note = "On our books only (not on vendor statement)"
                elif t > 0 and o == 0:
                    note = "On vendor statement only (not on our books)"
                else:
                    note = f"Amount difference: ours {o:,.2f} vs theirs {t:,.2f}"
                details.append({"invoice": ino, "ours": o, "theirs": t,
                                "diff": diff, "note": note})

        results.append({
            "vendor": v,
            "our_total": our_total,
            "their_total": their_total,
            "variance": variance,
            "status": "TIES" if abs(variance) < 0.01 else "VARIANCE",
            "details": details,
        })

    tied = sum(1 for r in results if r["status"] == "TIES")
    total_var = round(sum(r["variance"] for r in results), 2)
    return {
        "vendors": results,
        "vendor_count": len(results),
        "tied_count": tied,
        "variance_count": len(results) - tied,
        "total_variance": total_var,
    }


if __name__ == "__main__":
    r = reconcile()
    print(f"VENDOR STATEMENT RECON: {r['vendor_count']} vendors, "
          f"{r['tied_count']} tie, {r['variance_count']} have variances")
    print(f"Total portfolio variance: {r['total_variance']:,.2f}")
    for v in r["vendors"]:
        if v["status"] != "TIES":
            print(f"\n  {v['vendor']}: ours {v['our_total']:,.2f} vs "
                  f"theirs {v['their_total']:,.2f} = {v['variance']:,.2f}")
            for d in v["details"][:5]:
                print(f"    {d['invoice']}: {d['note']}")
