"""Duplicate-payment detection: same vendor + amount, normalized invoice# or near dates.
Run: python ap_duplicates.py
"""
import csv, os, re, datetime as dt
from collections import defaultdict

D = os.path.dirname(os.path.abspath(__file__))
DATE_WINDOW = 7  # days
GROUP_CAP = 100  # max pairwise comparisons per group
SUFFIX_PAT = re.compile(r"[-_](R|DUP|COPY|REV)$", re.IGNORECASE)


def fnum(x):
    try: return float(str(x).replace(",", ""))
    except (ValueError, TypeError): return None


def fdate(x):
    try: return dt.datetime.strptime((x or "").strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError): return None


def load(name, data_dir=None):
    p = os.path.join(data_dir or D, name)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


def _normalize_inv(s):
    """Strip one known duplicate-indicating suffix for comparison.
    INV-2001-R -> INV-2001, INV-2001-DUP -> INV-2001.
    Does NOT strip digits (INV-100 must not match INV-1000)."""
    s = (s or "").strip().upper()
    return SUFFIX_PAT.sub("", s)


def find_duplicates(data_dir=None):
    """Find suspected duplicate payments. Returns list of dups."""
    pays = load("Payments.csv", data_dir)
    if not pays:
        raise ValueError("Payments.csv must exist and be non-empty")

    groups = defaultdict(list)
    for p in pays:
        key = (p.get("Vendor"), round(fnum(p.get("Amount")) or 0, 2))
        groups[key].append(p)

    dups = []
    for (vendor, amount), items in groups.items():
        if len(items) < 2:
            continue
        if len(items) > GROUP_CAP:
            print(f"WARNING: group ({vendor}, {amount}) has {len(items)} items, "
                  f"capped pairwise at {GROUP_CAP}")
            items = items[:GROUP_CAP]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                norm_match = (_normalize_inv(a.get("Invoice_Number"))
                              == _normalize_inv(b.get("Invoice_Number"))
                              and _normalize_inv(a.get("Invoice_Number")) != "")
                da, db = fdate(a.get("Payment_Date")), fdate(b.get("Payment_Date"))
                near_date = da and db and abs((da - db).days) <= DATE_WINDOW
                if norm_match or near_date:
                    dups.append({
                        "vendor": vendor,
                        "amount": amount,
                        "payments": [a.get("Payment_Number"), b.get("Payment_Number")],
                        "invoices": [a.get("Invoice_Number"), b.get("Invoice_Number")],
                        "reason": "NORMALIZED_MATCH" if norm_match else "NEAR_DATE",
                    })
    return dups


if __name__ == "__main__":
    dups = find_duplicates()
    print(f"DUPLICATE PAYMENTS: {len(dups)} suspected")
    for d in dups:
        print(f"  [{d['reason']}] {d['vendor']} ${d['amount']:,.2f} "
              f"{d['payments']} invoices={d['invoices']}")
