import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import nofakedone as nfd  # noqa: E402

FIX = os.path.join(HERE, "fixtures")


def rules_for(diff_text):
    return {f.rule for f in nfd.analyze(nfd.parse_diff(diff_text))}


def one(path, *added, removed=(), deleted=False):
    lines = [f"diff --git a/{path} b/{path}"]
    if deleted:
        lines.append("deleted file mode 100644")
    lines += [f"--- a/{path}", f"+++ b/{path}", f"@@ -1,{len(removed)} +1,{len(added)} @@"]
    lines += [f"-{r}" for r in removed] + [f"+{a}" for a in added]
    return "\n".join(lines) + "\n"


class FixtureTests(unittest.TestCase):
    def test_fake_fixture_catches_every_category(self):
        with open(os.path.join(FIX, "fake.diff"), encoding="utf-8") as fh:
            got = rules_for(fh.read())
        expected = {
            "STUB_NOT_IMPLEMENTED", "STUB_ELIDED", "SWALLOWED_ERROR", "TEST_GAMING",
            "TEST_SKIPPED", "TEST_FOCUSED", "TAUTOLOGY_ASSERT", "TESTS_REMOVED",
            "TEST_FILE_DELETED", "COVERAGE_LOWERED", "CI_SOFT_FAIL", "HOOK_BYPASS",
            "LINT_SUPPRESSED", "TODO_ADDED", "FAKE_RETURN",
        }
        self.assertEqual(expected - got, set(), f"missed: {expected - got}")

    def test_clean_fixture_is_clean(self):
        with open(os.path.join(FIX, "clean.diff"), encoding="utf-8") as fh:
            self.assertEqual(nfd.analyze(nfd.parse_diff(fh.read())), [])


class RuleTests(unittest.TestCase):
    def test_multiline_python_swallow(self):
        self.assertIn("SWALLOWED_ERROR", rules_for(one("a.py", "try:", "    x()", "except Exception:", "    pass")))

    def test_multiline_js_swallow(self):
        self.assertIn("SWALLOWED_ERROR", rules_for(one("a.js", "try { x() } catch (e) {", "}")))

    def test_reraise_is_not_swallow(self):
        self.assertNotIn("SWALLOWED_ERROR", rules_for(one("a.py", "except ValueError:", "    raise")))

    def test_rust_and_go_stubs(self):
        self.assertIn("STUB_NOT_IMPLEMENTED", rules_for(one("lib.rs", "    todo!()")))
        self.assertIn("SWALLOWED_ERROR", rules_for(one("main.go", "    _ = err")))

    def test_skip_rules_only_apply_to_tests(self):
        self.assertNotIn("TEST_SKIPPED", rules_for(one("src/app.py", "@pytest.mark.skip")))
        self.assertIn("TEST_SKIPPED", rules_for(one("tests/test_app.py", "@pytest.mark.skip")))

    def test_go_and_java_skips(self):
        self.assertIn("TEST_SKIPPED", rules_for(one("pkg/x_test.go", "\tt.Skip(\"later\")")))
        self.assertIn("TEST_SKIPPED", rules_for(one("src/FooTest.java", "    @Disabled")))

    def test_real_assert_is_fine(self):
        self.assertEqual(rules_for(one("tests/test_x.py", "def test_x():", "    assert add(1, 2) == 3")), set())

    def test_self_comparison_is_tautology(self):
        self.assertIn("TAUTOLOGY_ASSERT", rules_for(one("x.test.ts", "expect(result).toBe(result)")))

    def test_docs_are_ignored(self):
        self.assertEqual(rules_for(one("docs/guide.md", "raise NotImplementedError", "# TODO")), set())

    def test_prose_mentioning_flags_is_fine(self):
        self.assertEqual(rules_for(one("README.md", "never use `pytest || true` or `--no-verify`")), set())
        self.assertEqual(rules_for(one("plugin.json", '"description": "catches --no-verify"')), set())

    def test_bypass_in_scripts_is_caught(self):
        self.assertIn("HOOK_BYPASS", rules_for(one("Makefile", "\tgit -C . commit -m x --no-verify")))
        self.assertIn("CI_SOFT_FAIL", rules_for(one("package.json", '"test": "jest || true"')))

    def test_inline_suppression(self):
        self.assertEqual(rules_for(one("a.py", "raise NotImplementedError  # nofakedone: ok abstract base")), set())

    def test_ignore_file_globs(self):
        diff = nfd.parse_diff(one("vendor/lib.py", "raise NotImplementedError"))
        self.assertEqual(nfd.analyze(diff, ["vendor/*"]), [])

    def test_coverage_raised_is_fine(self):
        self.assertEqual(rules_for(one("pyproject.toml", "fail_under = 95", removed=["fail_under = 90"])), set())

    def test_rewriting_tests_without_losing_any_is_fine(self):
        d = one("tests/test_a.py",
                "def test_a():", "    assert a() == 2", "def test_b():", "    assert b() == 3",
                removed=["def test_a():", "    assert a() == 1", "def test_b():", "    assert b() == 1"])
        self.assertEqual(rules_for(d), set())

    def test_assertions_stripped_from_kept_test(self):
        d = one("tests/test_a.py", "def test_a():", "    a()",
                removed=["def test_a():", "    assert a() == 1", "    assert calls == 1", "    assert log == []"])
        self.assertIn("ASSERTIONS_REMOVED", rules_for(d))

    def test_line_numbers(self):
        f = nfd.parse_diff("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -40,0 +41,2 @@\n+x = 1\n+raise NotImplementedError\n")
        found = nfd.analyze(f)
        self.assertEqual(found[0].line, 42)


class CliTests(unittest.TestCase):
    def run_main(self, args, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = nfd.main(args)
        finally:
            sys.stdin = old
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes_and_json(self):
        code, out, _ = self.run_main(["--diff", os.path.join(FIX, "fake.diff"), "--json"])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertTrue(data["blocking"])
        code, _, _ = self.run_main(["--diff", os.path.join(FIX, "clean.diff")])
        self.assertEqual(code, 0)

    def test_strict_promotes_warnings(self):
        code, _, _ = self.run_main(["--diff", "-", "--strict"], stdin=one("a.py", "x = 1  # TODO later"))
        self.assertEqual(code, 1)


@unittest.skipIf(subprocess.run(["git", "--version"], capture_output=True).returncode != 0, "git missing")
class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        g = lambda *a: subprocess.run(["git", *a], cwd=self.repo, capture_output=True, check=True)
        g("init", "-q")
        g("config", "user.email", "t@example.com")
        g("config", "user.name", "t")
        with open(os.path.join(self.repo, "app.py"), "w") as fh:
            fh.write("def f():\n    return 1\n")
        g("add", ".")
        g("commit", "-qm", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, payload):
        p = subprocess.run([sys.executable, os.path.join(HERE, "..", "scripts", "nofakedone.py"), "--hook"],
                           input=json.dumps(payload), capture_output=True, text=True, cwd=self.repo)
        return p.returncode, p.stderr

    def test_hook_passes_clean_repo(self):
        self.assertEqual(self.hook({"cwd": self.repo})[0], 0)

    def test_hook_blocks_stub_in_tracked_and_untracked_files(self):
        with open(os.path.join(self.repo, "app.py"), "w") as fh:
            fh.write("def f():\n    raise NotImplementedError\n")
        with open(os.path.join(self.repo, "new.py"), "w") as fh:
            fh.write("try:\n    g()\nexcept Exception:\n    pass\n")
        code, err = self.hook({"cwd": self.repo})
        self.assertEqual(code, 2)
        self.assertIn("STUB_NOT_IMPLEMENTED", err)
        self.assertIn("new.py", err)

    def test_hook_never_loops(self):
        with open(os.path.join(self.repo, "app.py"), "w") as fh:
            fh.write("def f():\n    raise NotImplementedError\n")
        self.assertEqual(self.hook({"cwd": self.repo, "stop_hook_active": True})[0], 0)

    def test_hook_outside_git_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.hook({"cwd": d}), (0, ""))


if __name__ == "__main__":
    unittest.main()
