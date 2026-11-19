#!/usr/bin/env python3
"""nofakedone: audit a git diff for work that only *looks* finished.

Zero dependencies. Tested on Python 3.10 and 3.13.

Usage:
  nofakedone.py                      audit uncommitted changes (vs HEAD, plus untracked files)
  nofakedone.py --base main          audit everything changed since `main`
  nofakedone.py --diff changes.diff  audit a saved unified diff ("-" reads stdin)
  nofakedone.py --json               machine-readable output
  nofakedone.py --hook               run as a Claude Code Stop hook (reads hook JSON on stdin)

Exit codes: 0 clean (or only warnings), 1 blocking findings, 2 blocking findings in --hook mode.
Silence one line with an inline comment:  nofakedone: ok <reason>
Silence whole paths with a .nofakedoneignore file (one glob per line).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional, Tuple

__version__ = "0.1.0"

BLOCK = "block"
WARN = "warn"

TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|"
    r"\.(test|spec)\.[cm]?[jt]sx?$|Tests?\.(java|kt|cs)$|_spec\.rb$|(^|/)conftest\.py$"
)
CI_PATH = re.compile(
    r"(^|/)\.github/workflows/|(^|/)\.gitlab-ci\.yml$|(^|/)\.circleci/|(^|/)azure-pipelines\.yml$|"
    r"(^|/)Jenkinsfile$|(^|/)\.pre-commit-config\.yaml$|(^|/)\.husky/"
)
CONFIG_PATH = re.compile(
    r"(^|/)(pyproject\.toml|setup\.cfg|tox\.ini|\.coveragerc|pytest\.ini|package\.json|"
    r"jest\.config\.[cm]?[jt]s|vitest\.config\.[cm]?[jt]s|\.nycrc(\.json)?|codecov\.ya?ml|karma\.conf\.js)$"
)
DOC_PATH = re.compile(r"\.(md|mdx|rst|txt|adoc)$|(^|/)(CHANGELOG|LICENSE|NOTICE)", re.I)
SELF_PATH = re.compile(r"(^|/)nofakedone(\.py)?$|(^|/)\.nofakedoneignore$")

SUPPRESS = re.compile(r"nofakedone:\s*ok", re.I)


@dataclass
class Rule:
    id: str
    severity: str
    title: str
    why: str
    pattern: Optional[re.Pattern] = None
    scope: str = "code"  # code | test | any | ci | config


def r(p: str) -> re.Pattern:
    return re.compile(p)


# Line rules: applied to every ADDED line whose file matches the rule's scope.
LINE_RULES: List[Rule] = [
    # --- stubs pretending to be implementations
    Rule("STUB_NOT_IMPLEMENTED", BLOCK, "Unimplemented stub",
         "The function raises 'not implemented' instead of doing the work.",
         r(r"raise\s+NotImplementedError|throw\s+new\s+(Error|NotImplementedException|UnsupportedOperationException)\(\s*['\"`]?\s*(not\s*implemented|todo|unimplemented)?|"
           r"\btodo!\(|\bunimplemented!\(|panic\(\s*\"(not implemented|todo|unimplemented)|"
           r"NotImplementedException\(|fatalError\(\s*\"(not implemented|todo)"), "code"),
    Rule("STUB_ELIDED", BLOCK, "Elided code placeholder",
         "A comment stands in for code that was never written.",
         r(r"(//|#|/\*|<!--)\s*\.{3}\s*(rest|remaining|existing|other|more|same)\b|"
           r"(//|#)\s*(rest of (the )?(code|implementation|function)|implementation (goes )?here|"
           r"add (your |the )?(logic|implementation) here|your code here|placeholder implementation)"), "code"),
    Rule("FAKE_RETURN", WARN, "Placeholder return value",
         "A hard-coded or dummy return value marked as temporary.",
         r(r"(?i)return\s+[^;#/\n]+[;]?\s*(//|#)\s*(todo|fixme|placeholder|dummy|fake|mock(ed)?|stub|temporary|hardcoded)\b"), "code"),
    Rule("TODO_ADDED", WARN, "New TODO/FIXME",
         "Work was deferred. Fine if intentional, but say so in the summary.",
         r(r"(//|#|/\*|<!--|--)\s*(TODO|FIXME|XXX|HACK)\b"), "code"),

    # --- swallowed errors
    Rule("SWALLOWED_ERROR", BLOCK, "Swallowed exception",
         "Errors are caught and discarded, so failures become silent successes.",
         r(r"except\s*(\(?[A-Za-z_., ]*\)?)?\s*(as\s+\w+)?\s*:\s*(pass|\.\.\.)\s*$|"
           r"catch\s*(\([^)]*\))?\s*\{\s*\}|\.catch\(\s*\(\s*\w*\s*\)\s*=>\s*\{?\s*\}?\s*\)|"
           r"rescue\s*(=>\s*\w+)?\s*;?\s*(nil|end)\s*$|_\s*=\s*err\s*$|if\s+err\s*!=\s*nil\s*\{\s*\}"), "code"),

    # --- tests that cannot fail
    Rule("TEST_SKIPPED", BLOCK, "Test skipped or disabled",
         "A test was switched off instead of being made to pass.",
         r(r"@pytest\.mark\.(skip|xfail)\b|pytest\.skip\(|@unittest\.skip|\bself\.skipTest\(|"
           r"\b(it|test|describe|context)\.(skip|todo)\(|\bx(it|describe|test)\(|"
           r"@(Disabled|Ignore)\b|\bt\.Skip(Now|f)?\(|#\[ignore\]|\bskip\s*:\s*true|\bpending\(|"
           r"\[(Fact|Theory)\(Skip\s*="), "test"),
    Rule("TEST_FOCUSED", BLOCK, "Focused test (.only)",
         "'.only' silently stops every other test from running.",
         r(r"\b(it|test|describe|context)\.only\(|\bf(it|describe)\("), "test"),
    Rule("TAUTOLOGY_ASSERT", BLOCK, "Assertion that cannot fail",
         "The assertion is always true, so the test proves nothing.",
         r(r"\bassert\s+(True|1|not\s+False)\s*($|#|,)|assert(True|That)\(\s*true\s*\)|assertEquals?\(\s*(true|1)\s*,\s*(true|1)\s*\)|"
           r"self\.assert(True|Equal)\(\s*(True|1)\s*(,\s*(True|1))?\s*\)|"
           r"expect\(\s*(true|1|!0)\s*\)\.(toBe|toEqual|toBeTruthy)\(\s*(true|1)?\s*\)|"
           r"expect\(\s*(?P<a>\w+)\s*\)\.(toBe|toEqual)\(\s*(?P=a)\s*\)|assert!\(\s*true\s*\)|"
           r"assert_eq!\(\s*(?P<b>\w+)\s*,\s*(?P=b)\s*\)|\bassert\s+(?P<c>\w+)\s*==\s*(?P=c)\s*($|#)"), "test"),
    Rule("TEST_GAMING", BLOCK, "Code detects the test environment",
         "Production code behaves differently under test, so tests check a fake path.",
         r(r"""['"]pytest['"]\s+in\s+sys\.modules|sys\.modules\.get\(\s*['"]pytest|PYTEST_CURRENT_TEST|"""
           r"""process\.env\.(NODE_ENV|JEST_WORKER_ID|VITEST)\s*={2,3}\s*['"]?test|process\.env\.(JEST_WORKER_ID|VITEST)\b|"""
           r"""if\s+.*\b(is_testing|IS_TEST|isTestEnv|TESTING)\b\s*(==|===)?\s*(True|true)?\s*[:{)]"""), "code"),

    # --- bypassing the checks
    Rule("HOOK_BYPASS", BLOCK, "Git hooks bypassed",
         "--no-verify skips the checks the project set up.",
         r(r"\bgit\s+(\S+\s+)*?(commit|push|merge|rebase|cherry-pick)\b[^\n]*--no-verify\b|\bHUSKY=0\b|SKIP=\S*\s+git\s+commit"), "any"),
    Rule("CI_SOFT_FAIL", BLOCK, "CI step can no longer fail",
         "A test or lint step was set to pass even when it fails.",
         r(r"continue-on-error:\s*true|allow_failure:\s*true|"
           r"(pytest|jest|vitest|npm (run )?test|yarn test|pnpm test|go test|cargo test|mvn test|gradle test|ruff|eslint|mypy|tsc)\b[^\n]*\|\|\s*(true|exit 0|:)\s*[\"',;)]*\s*$"), "any"),
    Rule("LINT_SUPPRESSED", WARN, "Type or lint check suppressed",
         "A checker was told to look away. Fine if justified, so justify it.",
         r(r"#\s*type:\s*ignore|@ts-(ignore|nocheck|expect-error)|eslint-disable|#\s*noqa\b|//\s*nolint|"
           r"#\s*pylint:\s*disable|@SuppressWarnings|#\[allow\(|#\s*pragma:\s*no\s*cover"), "code"),
]

TEST_DEF = re.compile(
    r"^\s*(async\s+)?def\s+test_\w*|^\s*(it|test)\s*\(|^\s*@Test\b|^\s*func\s+Test\w+\s*\(|"
    r"^\s*#\[test\]|^\s*\[(Fact|Theory|Test|TestMethod)\]|^\s*it\s+['\"]"
)
ASSERTION = re.compile(
    r"\bassert\w*\b|\bexpect\s*\(|\bshould\b|\.to(Be|Equal|Throw|Match|Have)\w*\(|\bt\.(Error|Fatal|Fail)|\bverify\s*\("
)
MULTI_EXCEPT = re.compile(r"^\s*except\b[^:]*:\s*(#.*)?$")
EMPTY_BODY_PY = re.compile(r"^\s*(pass|\.\.\.)\s*(#.*)?$")
MULTI_CATCH = re.compile(r"\bcatch\s*(\([^)]*\))?\s*\{\s*$")
EMPTY_BODY_BRACE = re.compile(r"^\s*\}\s*;?\s*$")
COVERAGE_NUM = re.compile(
    r"(fail[_-]under|fail_under|--cov-fail-under|branches|functions|lines|statements|"
    r"coverageThreshold|minimum[_-]?coverage|threshold)\s*[\"']?\s*[:=]\s*[\"']?\s*(\d+(\.\d+)?)", re.I
)


@dataclass
class FileDiff:
    path: str
    old_path: Optional[str] = None
    added: List[Tuple[int, str]] = field(default_factory=list)
    removed: List[Tuple[int, str]] = field(default_factory=list)
    deleted: bool = False
    new: bool = False


@dataclass
class Finding:
    rule: str
    severity: str
    title: str
    why: str
    path: str
    line: int
    snippet: str


# ---------------------------------------------------------------- diff input

def run_git(args: List[str], cwd: Optional[str] = None) -> Tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return p.returncode, p.stdout
    except FileNotFoundError:
        return 127, ""


def collect_diff(base: Optional[str], cwd: Optional[str] = None) -> Optional[str]:
    code, _ = run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    if code != 0:
        return None
    has_head = run_git(["rev-parse", "--verify", "HEAD"], cwd)[0] == 0
    ref = base or ("HEAD" if has_head else None)
    if ref:
        _, diff = run_git(["diff", "--no-color", "--no-ext-diff", "-U0", "-M", ref], cwd)
    else:
        _, diff = run_git(["diff", "--no-color", "--no-ext-diff", "-U0", "--cached"], cwd)
    _, untracked = run_git(["ls-files", "--others", "--exclude-standard", "-z"], cwd)
    root = run_git(["rev-parse", "--show-toplevel"], cwd)[1].strip() or (cwd or ".")
    for rel in filter(None, untracked.split("\0")):
        full = os.path.join(root, rel)
        try:
            if os.path.getsize(full) > 1_000_000:
                continue
            with open(full, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        diff += f"\ndiff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(lines)} @@\n"
        diff += "".join(f"+{ln}\n" for ln in lines)
    return diff


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_diff(text: str) -> List[FileDiff]:
    files: List[FileDiff] = []
    cur: Optional[FileDiff] = None
    old_no = new_no = 0
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", raw)
            cur = FileDiff(path=m.group(2) if m else raw[11:], old_path=m.group(1) if m else None)
            files.append(cur)
            continue
        if cur is None:
            continue
        if raw.startswith("deleted file mode"):
            cur.deleted = True
        elif raw.startswith("new file mode"):
            cur.new = True
        elif raw.startswith("--- ") or raw.startswith("+++ "):
            continue
        elif raw.startswith("@@"):
            m = HUNK.match(raw)
            if m:
                old_no, new_no = int(m.group(1)), int(m.group(3))
        elif raw.startswith("+"):
            cur.added.append((new_no, raw[1:]))
            new_no += 1
        elif raw.startswith("-"):
            cur.removed.append((old_no, raw[1:]))
            old_no += 1
        elif raw.startswith(" "):
            old_no += 1
            new_no += 1
    return files


# ---------------------------------------------------------------- analysis

def load_ignores(root: str) -> List[str]:
    try:
        with open(os.path.join(root, ".nofakedoneignore"), encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    except OSError:
        return []


def ignored(path: str, globs: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(os.path.basename(path), g) for g in globs)


def in_scope(rule: Rule, path: str) -> bool:
    is_test = bool(TEST_PATH.search(path))
    if rule.scope == "test":
        return is_test
    return not DOC_PATH.search(path)


def is_comment_example(line: str) -> bool:
    """Skip lines that only mention a pattern inside a string literal describing it."""
    s = line.strip()
    return s.startswith(("r\"", "r'", "\"\"\"", "'''"))


def analyze(files: List[FileDiff], ignore_globs: Iterable[str] = ()) -> List[Finding]:
    out: List[Finding] = []
    ignore_globs = list(ignore_globs)
    for f in files:
        if ignored(f.path, ignore_globs) or SELF_PATH.search(f.path):
            continue
        is_test = bool(TEST_PATH.search(f.path))

        for no, line in f.added:
            if SUPPRESS.search(line) or is_comment_example(line):
                continue
            for rule in LINE_RULES:
                if rule.scope == "code" and is_test and rule.id in ("TEST_GAMING",):
                    continue
                if in_scope(rule, f.path) and rule.pattern.search(line):
                    out.append(Finding(rule.id, rule.severity, rule.title, rule.why, f.path, no, line.strip()[:160]))

        # handler opened on one line, emptied on the next
        if not DOC_PATH.search(f.path):
            nums = dict(f.added)
            for no, line in f.added:
                nxt = nums.get(no + 1)
                if nxt is None or SUPPRESS.search(line) or SUPPRESS.search(nxt):
                    continue
                if (MULTI_EXCEPT.search(line) and EMPTY_BODY_PY.match(nxt)) or \
                   (MULTI_CATCH.search(line) and EMPTY_BODY_BRACE.match(nxt)):
                    out.append(Finding("SWALLOWED_ERROR", BLOCK, "Swallowed exception",
                                       "Errors are caught and discarded, so failures become silent successes.",
                                       f.path, no, f"{line.strip()} / {nxt.strip()}"[:160]))

        # whole test file deleted
        if is_test and f.deleted:
            n = sum(1 for _, l in f.removed if TEST_DEF.search(l))
            out.append(Finding("TEST_FILE_DELETED", BLOCK, "Test file deleted",
                               f"A test file with {n} test(s) was removed.", f.path, 0, f"deleted {f.path}"))
            continue

        # tests or assertions removed on net
        if is_test and not f.deleted:
            removed_tests = [(n, l) for n, l in f.removed if TEST_DEF.search(l)]
            added_tests = [l for _, l in f.added if TEST_DEF.search(l)]
            if len(removed_tests) > len(added_tests):
                n, l = removed_tests[0]
                out.append(Finding("TESTS_REMOVED", BLOCK, "Tests removed",
                                   f"{len(removed_tests) - len(added_tests)} more test(s) removed than added.",
                                   f.path, n, l.strip()[:160]))
            rem_a = [(n, l) for n, l in f.removed if ASSERTION.search(l) and not SUPPRESS.search(l)]
            add_a = [l for _, l in f.added if ASSERTION.search(l)]
            if len(rem_a) - len(add_a) >= 2 and len(removed_tests) <= len(added_tests):
                n, l = rem_a[0]
                out.append(Finding("ASSERTIONS_REMOVED", BLOCK, "Assertions removed",
                                   f"{len(rem_a) - len(add_a)} more assertion(s) removed than added; tests got weaker.",
                                   f.path, n, l.strip()[:160]))

        # coverage thresholds lowered
        if CONFIG_PATH.search(f.path) or CI_PATH.search(f.path):
            before: Dict[str, float] = {}
            for _, l in f.removed:
                m = COVERAGE_NUM.search(l)
                if m:
                    before[m.group(1).lower()] = float(m.group(2))
            for n, l in f.added:
                m = COVERAGE_NUM.search(l)
                if m and m.group(1).lower() in before and float(m.group(2)) < before[m.group(1).lower()]:
                    out.append(Finding("COVERAGE_LOWERED", BLOCK, "Coverage threshold lowered",
                                       f"{m.group(1)} went from {before[m.group(1).lower()]:g} to {m.group(2)}.",
                                       f.path, n, l.strip()[:160]))
    # stable order, dedupe
    seen = set()
    uniq = []
    for x in sorted(out, key=lambda x: (x.severity != BLOCK, x.path, x.line, x.rule)):
        k = (x.rule, x.path, x.line)
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq


# ---------------------------------------------------------------- output

def render(findings: List[Finding], files: List[FileDiff], color: bool) -> str:
    def c(code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if color else s

    blocks = [f for f in findings if f.severity == BLOCK]
    warns = [f for f in findings if f.severity == WARN]
    lines = [c("1", f"nofakedone v{__version__}") + f"  scanned {len(files)} changed file(s)"]
    if not findings:
        lines.append(c("32", "No fake-done patterns found. Receipts look real."))
        return "\n".join(lines)
    for f in findings:
        tag = c("31;1", "BLOCK") if f.severity == BLOCK else c("33", "warn ")
        loc = f"{f.path}:{f.line}" if f.line else f.path
        lines.append(f"{tag} {c('1', f.title)}  {loc}  [{f.rule}]")
        lines.append(f"      {f.snippet}")
        lines.append(c("2", f"      {f.why}"))
    lines.append("")
    lines.append(f"{len(blocks)} blocking, {len(warns)} warning(s).")
    if blocks:
        lines.append("Fix each BLOCK, or if it is genuinely intended, add `nofakedone: ok <reason>` on that line.")
    return "\n".join(lines)


def hook_message(findings: List[Finding]) -> str:
    blocks = [f for f in findings if f.severity == BLOCK]
    body = "\n".join(
        f"- [{f.rule}] {f.title} at {f.path}:{f.line}: `{f.snippet}`. {f.why}" for f in blocks[:15]
    )
    more = f"\n- ...and {len(blocks) - 15} more" if len(blocks) > 15 else ""
    return (
        "nofakedone: the diff still contains work that only looks finished. Before you stop:\n"
        f"{body}{more}\n"
        "For each item, either do the real work, or (only if it is truly intended) add an inline "
        "`nofakedone: ok <reason>` comment and tell the user why in your final message. "
        "Do not delete or weaken tests to get past this check."
    )


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="nofakedone", description="Audit a diff for fake 'done'.")
    ap.add_argument("--base", help="git ref to diff against (default: HEAD + untracked files)")
    ap.add_argument("--diff", help="read a unified diff from this file ('-' for stdin)")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--hook", action="store_true", help="Claude Code Stop-hook mode")
    ap.add_argument("--strict", action="store_true", help="treat warnings as blocking")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)

    cwd = None
    if a.hook:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError:
            payload = {}
        if payload.get("stop_hook_active"):
            return 0  # already blocked once this turn; never loop forever
        cwd = payload.get("cwd") or None
        if os.environ.get("NOFAKEDONE_DISABLE") == "1":
            return 0

    if a.diff:
        text = sys.stdin.read() if a.diff == "-" else open(a.diff, encoding="utf-8", errors="replace").read()
        root = os.getcwd()
    else:
        text = collect_diff(a.base, cwd)
        if text is None:
            if not a.hook:
                print("nofakedone: not inside a git repository.", file=sys.stderr)
            return 0
        root = run_git(["rev-parse", "--show-toplevel"], cwd)[1].strip() or os.getcwd()

    files = parse_diff(text)
    findings = analyze(files, load_ignores(root))
    if a.strict:
        for f in findings:
            f.severity = BLOCK
    blocking = any(f.severity == BLOCK for f in findings)

    if a.hook:
        if blocking:
            print(hook_message(findings), file=sys.stderr)
            return 2
        return 0
    if a.json:
        print(json.dumps({"version": __version__, "files": len(files),
                          "blocking": blocking, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        print(render(findings, files, color=sys.stdout.isatty() and not os.environ.get("NO_COLOR")))
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
