---
name: nofakedone
description: Use before saying a coding task is done, finished, fixed or passing, and whenever the nofakedone Stop hook blocks you. Audits the git diff for work that only looks finished (unimplemented stubs, elided code, swallowed exceptions, skipped/focused/deleted tests, assertions that cannot fail, code that detects the test environment, --no-verify, CI steps that cannot fail, lowered coverage thresholds) and explains how to resolve each finding honestly.
---

# nofakedone

"Done" means the behavior works and the checks that prove it still run. This skill keeps you honest about that.

## When to run it

- Before you tell the user a task is complete, fixed, or that tests pass.
- When the Stop hook prints `nofakedone: the diff still contains work that only looks finished`.
- When the user asks "is this really done?" or asks for a pre-commit sanity check.

## How to run it

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/nofakedone.py"            # uncommitted changes + untracked files
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/nofakedone.py" --base main  # whole branch
```

If the plugin root is not set (the skill was copied by hand), run `scripts/nofakedone.py` from this repository.

## How to resolve each finding

| Rule | Do this instead |
|---|---|
| STUB_NOT_IMPLEMENTED, STUB_ELIDED | Write the actual implementation. If you cannot, say so plainly and leave the task open. |
| SWALLOWED_ERROR | Handle the error, log it and re-raise, or let it propagate. Never turn failure into silent success. |
| TEST_SKIPPED, TEST_FOCUSED | Make the test pass, or remove `.only`. If a test is truly obsolete, tell the user which one and why. |
| TESTS_REMOVED, TEST_FILE_DELETED, ASSERTIONS_REMOVED | Restore them. Change a test only when the specified behavior changed, and say so. |
| TAUTOLOGY_ASSERT | Assert on the real output of the code under test. |
| TEST_GAMING | Remove the test-only branch. Use dependency injection or fixtures instead. |
| HOOK_BYPASS, CI_SOFT_FAIL, COVERAGE_LOWERED | Restore the check and fix what it catches. |
| TODO_ADDED, FAKE_RETURN, LINT_SUPPRESSED (warnings) | Fine only if intended: list them in your final message. |

## Rules

1. Never delete, skip or weaken a test to get past this check. That is the exact behavior it exists to catch.
2. Use `nofakedone: ok <reason>` only for code that is genuinely meant to be that way (an abstract method, an optional import), and repeat the reason to the user.
3. If you cannot finish honestly, stop and report what is left. An honest "not done yet" beats a fake "done".
