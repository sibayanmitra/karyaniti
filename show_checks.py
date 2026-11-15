"""Show CHECK-verdict entries from the audit for manual review."""
import json
from pathlib import Path

audit_path = Path("authority_build/supplement_audit_v2.json")
results = json.loads(audit_path.read_text(encoding="utf-8"))

checks = [r for r in results if r["verdict"] == "CHECK"]
print(f"CHECK entries: {len(checks)}\n")
for r in checks:
    print(f"tid={r['tid']}  overlap={r['overlap']}  seq={r['seq_ratio']}")
    print(f"  expected: {r['expected_name']}")
    print(f"  got:      {r['actual_title']}")
    print()
