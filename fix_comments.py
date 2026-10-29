import re

# Fix 1: AmbiguousCompletionEnforcer.enforce_settlement_prerequisites() should fail if no row
file1 = "services/orchestrator/architecture_hardening_part14.py"
with open(file1, "r") as f:
    content = f.read()

content = re.sub(
    r"        if not row:\n            return  # No completion recorded yet, nothing to settle/enforce here",
    r"        if not row:\n            raise AmbiguousCompletionError(\n                f\"Job {job_id} has no completion record. Settlement requires an explicitly recorded completion status.\"\n            )",
    content
)
with open(file1, "w") as f:
    f.write(content)

# Fix 3: mark_completion() should update is_reconciled or state transition
with open(file1, "r") as f:
    content = f.read()
content = re.sub(
    r"            \"ON CONFLICT\(job_id\) DO UPDATE SET is_ambiguous=excluded.is_ambiguous\",\n            \(job_id, is_ambiguous, False\)",
    r"            \"ON CONFLICT(job_id) DO UPDATE SET is_ambiguous=excluded.is_ambiguous, is_reconciled=False\",\n            (job_id, is_ambiguous, False)",
    content
)
with open(file1, "w") as f:
    f.write(content)

print("Applied fixes to services/orchestrator/architecture_hardening_part14.py")
