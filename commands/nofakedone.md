---
description: Audit the current diff for fake "done" (stubs, disabled tests, tautological asserts, swallowed errors)
argument-hint: "[--base <ref>] [--strict]"
---

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/nofakedone.py" $ARGUMENTS` from the repository root and show the report.

Then, for every BLOCK finding, do the real work: implement the stub, re-enable or restore the test, assert on real behavior, handle or re-raise the error, or restore the check.
Only if a finding is genuinely intended, add an inline `nofakedone: ok <reason>` comment and say why in your reply.
Never delete or weaken a test to make this report pass. Re-run the command until it reports no BLOCK findings.
