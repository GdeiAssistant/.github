#!/usr/bin/env python3
"""Tests for repository documentation, anti-leak, and agent-file hygiene checks."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent / "check_hygiene.py"
SPEC = importlib.util.spec_from_file_location("check_hygiene", SCRIPT_PATH)
hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hygiene)


class CheckHygieneTests(unittest.TestCase):
    def _init_minimal_repo(self, repo: Path, english_agents: bool = False, public: bool = False, with_coc: bool = False) -> None:
        repo.mkdir(parents=True, exist_ok=True)
        sections = hygiene.AGENTS_SECTIONS_EN if english_agents else hygiene.AGENTS_SECTIONS_ZH
        agents = "\n".join(
            ["<!-- content-boundary:begin -->"] + [f"## {s}\nOK" for s in sections]
        )
        (repo / "AGENTS.md").write_text(agents + "\n", encoding="utf-8")
        (repo / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        (repo / "SECURITY.md").write_text("# Security\n\nReport issues privately.\n", encoding="utf-8")
        if public:
            (repo / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
            (repo / "CONTRIBUTING.md").write_text("# Contributing\n", encoding="utf-8")
            if with_coc:
                (repo / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\n", encoding="utf-8")
            (repo / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True, exist_ok=True)
            (repo / ".github" / "ISSUE_TEMPLATE" / "bug.yml").write_text("name: Bug\n", encoding="utf-8")
            (repo / ".github" / "pull_request_template.md").write_text("## Summary\n", encoding="utf-8")
        (repo / ".gitignore").write_text(
            "\n".join(hygiene.REQUIRED_GITIGNORE_PATTERNS) + "\n",
            encoding="utf-8",
        )
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "guide.md").write_text("# Guide\n\nSetup steps.\n", encoding="utf-8")
        (repo / "build" / "plans").mkdir(parents=True, exist_ok=True)
        (repo / "build" / "2026-01-01-audit.md").write_text("# Build artifact\n", encoding="utf-8")

        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "add", "AGENTS.md", "CLAUDE.md", "SECURITY.md", ".gitignore"], cwd=repo, check=True)

    def _run_cli(self, repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--root", str(repo), *extra],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_repo_under_build_ancestor_scans_repo_and_skips_repo_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "build" / "repo"
            self._init_minimal_repo(repo)

            found_rels = {p.relative_to(repo).as_posix() for p in hygiene.iter_files(repo)}
            self.assertIn("docs/guide.md", found_rels)
            self.assertNotIn("build/2026-01-01-audit.md", found_rels)

            clean = self._run_cli(repo, "--private")
            self.assertEqual(clean.returncode, 0, msg=clean.stdout + clean.stderr)

            (repo / "plans").mkdir()
            (repo / "docs" / "postmortem.md").write_text("# Notes\n", encoding="utf-8")

            dirty = self._run_cli(repo, "--private")
            self.assertEqual(dirty.returncode, 1, msg=dirty.stdout + dirty.stderr)
            self.assertIn("plans/: do not split directories by phase", dirty.stdout)
            self.assertIn("docs/postmortem.md:", dirty.stdout)

    def test_english_agents_and_nested_agents_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            self._init_minimal_repo(repo, english_agents=True)
            (repo / "apps" / "web").mkdir(parents=True)
            (repo / "apps" / "web" / "AGENTS.md").write_text("# Web rules\n", encoding="utf-8")
            res = self._run_cli(repo, "--private", "--strict")
            self.assertEqual(res.returncode, 0, msg=res.stdout + res.stderr)

    def test_retired_engineering_doc_and_gitignore_exception_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            self._init_minimal_repo(repo)
            (repo / ".github").mkdir(exist_ok=True)
            (repo / ".github" / "engineering.md").write_text("# Legacy\n", encoding="utf-8")
            gi = repo / ".gitignore"
            gi.write_text(gi.read_text(encoding="utf-8") + "!.github/engineering.md\n", encoding="utf-8")

            res = self._run_cli(repo, "--private")
            self.assertEqual(res.returncode, 1)
            self.assertIn(".github/engineering.md is retired", res.stdout)
            self.assertIn(".gitignore still unignores retired .github/engineering.md", res.stdout)

    def test_readme_patch_prose_phase_headings_and_post_license_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            self._init_minimal_repo(repo)
            (repo / "README.md").write_text(
                "# Demo\n\n## P0–P6 Runtime Status\n\nBehavior remains unchanged in this PR.\n\n"
                "## License\n\nMIT\n\n## Weekly secret scan\n\nRuns weekly.\n",
                encoding="utf-8",
            )
            res = self._run_cli(repo, "--private")
            self.assertEqual(res.returncode, 1)
            self.assertIn("PR-diff narration in README prose", res.stdout)
            self.assertIn("phase-milestone heading in README", res.stdout)
            self.assertIn("section placed after License", res.stdout)

    def test_code_examples_in_readme_are_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            self._init_minimal_repo(repo)
            (repo / "README.md").write_text(
                "# Demo\n\nDo not write `remains unchanged` in prose.\n\n"
                "```markdown\n## License\n\n## After License Example\n```\n\n"
                "## License\n\nMIT\n",
                encoding="utf-8",
            )
            res = self._run_cli(repo, "--private")
            self.assertEqual(res.returncode, 0, msg=res.stdout + res.stderr)

    def test_public_vs_private_internal_artifacts_and_missing_gitignore_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            self._init_minimal_repo(repo, public=True)
            (repo / "docs" / "changes").mkdir(parents=True)
            (repo / "docs" / "changes" / "card.md").write_text("# Card\n", encoding="utf-8")
            (repo / "docs" / "acceptance-policy.md").write_text("# Policy\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "-f", "docs/changes/card.md", "docs/acceptance-policy.md"],
                cwd=repo,
                check=True,
            )

            pub = self._run_cli(repo)
            self.assertEqual(pub.returncode, 1)
            self.assertIn("docs/changes/", pub.stdout)
            self.assertIn("docs/acceptance-policy.md", pub.stdout)

            priv = self._run_cli(repo, "--private")
            self.assertEqual(priv.returncode, 0, msg=priv.stdout + priv.stderr)

            (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
            missing_gi = self._run_cli(repo, "--private")
            self.assertEqual(missing_gi.returncode, 1)
            self.assertIn("missing required anti-leak patterns", missing_gi.stdout)

    def test_public_repo_requires_pr_and_issue_templates_and_optional_coc(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            self._init_minimal_repo(repo, public=True, with_coc=False)
            clean = self._run_cli(repo)
            self.assertEqual(clean.returncode, 0, msg=clean.stdout + clean.stderr)

            need_coc = self._run_cli(repo, "--require-coc")
            self.assertEqual(need_coc.returncode, 1)
            self.assertIn("CODE_OF_CONDUCT.md", need_coc.stdout)

            (repo / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\n", encoding="utf-8")
            has_coc = self._run_cli(repo, "--require-coc")
            self.assertEqual(has_coc.returncode, 0, msg=has_coc.stdout + has_coc.stderr)

            (repo / ".github" / "pull_request_template.md").unlink()
            missing_pr_tpl = self._run_cli(repo)
            self.assertEqual(missing_pr_tpl.returncode, 1)
            self.assertIn(".github/pull_request_template.md", missing_pr_tpl.stdout)

            (repo / ".github" / "pull_request_template.md").write_text("## Summary\n", encoding="utf-8")
            (repo / ".github" / "ISSUE_TEMPLATE" / "bug.yml").unlink()
            empty_issue_tpl = self._run_cli(repo)
            self.assertEqual(empty_issue_tpl.returncode, 1)
            self.assertIn("ISSUE_TEMPLATE", empty_issue_tpl.stdout)

            priv = self._run_cli(repo, "--private")
            self.assertEqual(priv.returncode, 0, msg=priv.stdout + priv.stderr)

    def test_gitignored_local_notes_are_skipped_while_staged_notes_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            self._init_minimal_repo(repo, public=True)
            (repo / "docs" / "changes").mkdir(parents=True)
            (repo / "docs" / "changes" / "note.md").write_text("# Note\n", encoding="utf-8")
            (repo / "docs" / "plans").mkdir(parents=True)
            (repo / "docs" / "plans" / "draft.md").write_text("# Draft\n", encoding="utf-8")
            (repo / "docs" / "acceptance-policy.md").write_text("# Policy\n", encoding="utf-8")

            ignored_res = self._run_cli(repo)
            self.assertEqual(ignored_res.returncode, 0, msg=ignored_res.stdout + ignored_res.stderr)

            subprocess.run(["git", "add", "-f", "docs/changes/note.md"], cwd=repo, check=True)
            staged_res = self._run_cli(repo)
            self.assertEqual(staged_res.returncode, 1)
            self.assertIn("docs/changes/", staged_res.stdout)

    def test_strict_docs_fails_on_doc_warnings_but_keeps_code_comments_non_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            self._init_minimal_repo(repo, public=True)
            (repo / "module.py").write_text("# 这里等待重试\nvalue = 1\n", encoding="utf-8")

            docs_ok = self._run_cli(repo, "--strict-docs")
            self.assertEqual(docs_ok.returncode, 0, msg=docs_ok.stdout + docs_ok.stderr)
            self.assertIn("non-English comments", docs_ok.stdout)

            strict_fail = self._run_cli(repo, "--strict")
            self.assertEqual(strict_fail.returncode, 1)

            (repo / "docs" / "long.md").write_text("# Long\n\n" + ("x" * 405) + "\n", encoding="utf-8")
            doc_para_fail = self._run_cli(repo, "--strict-docs")
            self.assertEqual(doc_para_fail.returncode, 1)
            self.assertIn("paragraph runs", doc_para_fail.stdout)
            (repo / "docs" / "long.md").unlink()

            (repo / "docs" / "orphan.zh-CN.md").write_text("# Orphan\n", encoding="utf-8")
            orphan_fail = self._run_cli(repo, "--strict-docs")
            self.assertEqual(orphan_fail.returncode, 1)
            self.assertIn("single-language file needs no suffix", orphan_fail.stdout)


class AgentInstructionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        hygiene.errors.clear()
        hygiene.warnings.clear()
        hygiene.doc_warnings.clear()
        self.git("init", "--quiet")
        (self.root / "AGENTS.md").write_text(
            "\n".join("## " + name for name in hygiene.AGENTS_SECTIONS)
            + "\n" + hygiene.CONTENT_BOUNDARY,
            encoding="utf-8",
        )
        (self.root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def test_ignored_local_files_are_not_a_delivery(self):
        (self.root / ".gitignore").write_text("AGENTS.md\nCLAUDE.md\n")
        hygiene.check_agents(self.root)
        self.assertTrue(any("AGENTS.md" in e for e in hygiene.errors))
        self.assertTrue(any("CLAUDE.md" in e for e in hygiene.errors))

    def test_tracked_instructions_pass(self):
        self.git("add", "AGENTS.md", "CLAUDE.md")
        hygiene.check_agents(self.root)
        self.assertEqual(hygiene.errors, [])

    def test_missing_claude_entry_is_reported(self):
        (self.root / "CLAUDE.md").unlink()
        self.git("add", "AGENTS.md")
        hygiene.check_agents(self.root)
        self.assertTrue(any("CLAUDE.md" in e for e in hygiene.errors))

    def test_content_boundary_block_is_required(self):
        (self.root / "AGENTS.md").write_text(
            "\n".join("## " + name for name in hygiene.AGENTS_SECTIONS),
            encoding="utf-8",
        )
        self.git("add", "AGENTS.md", "CLAUDE.md")
        hygiene.check_agents(self.root)
        self.assertTrue(any("content-boundary" in e for e in hygiene.errors))

    def test_git_metadata_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("AGENTS.md", "CLAUDE.md"):
                (root / name).write_bytes((self.root / name).read_bytes())
            hygiene.check_agents(root)
            self.assertTrue(hygiene.errors)

    def test_secret_diagnostic_does_not_print_the_value(self):
        value = "ghp_" + "X" * 30
        (self.root / "example.txt").write_text(value)
        hygiene.check_secrets(self.root)
        self.assertTrue(hygiene.errors)
        self.assertNotIn(value[:12], "\n".join(hygiene.errors))


class LocaleSuffixTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        hygiene.errors.clear()
        hygiene.warnings.clear()
        hygiene.doc_warnings.clear()

    def check(self, name: str):
        path = self.root / name
        path.write_text("# Title\n", encoding="utf-8")
        hygiene.check_filename(self.root, path)
        return list(hygiene.errors)

    def test_en_suffix_is_accepted(self):
        self.assertEqual(self.check("guide.en.md"), [])

    def test_zh_cn_suffix_is_accepted(self):
        self.assertEqual(self.check("guide.zh-CN.md"), [])

    def test_lowercase_zh_cn_is_rejected(self):
        self.assertTrue(self.check("guide.zh-cn.md"))

    def test_regional_english_variant_is_rejected(self):
        self.assertTrue(self.check("guide.en-us.md"))


class BilingualPairTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        hygiene.errors.clear()
        hygiene.warnings.clear()
        hygiene.doc_warnings.clear()

    def write(self, name: str, body: str):
        (self.root / name).write_text(body, encoding="utf-8")

    def test_missing_link_is_an_error(self):
        self.write("guide.md", "# Guide\n\nEnglish | [简体中文](guide.zh-CN.md)\n")
        self.write("guide.zh-CN.md", "# 指南\n\n中文正文。\n")
        hygiene.check_bilingual_pair(self.root)
        self.assertTrue(any("guide.md" in e for e in hygiene.errors))

    def test_mutual_links_pass(self):
        self.write("guide.md", "# Guide\n\nEnglish | [简体中文](guide.zh-CN.md)\n")
        self.write("guide.zh-CN.md", "# 指南\n\n[English](guide.md) | 简体中文\n")
        hygiene.check_bilingual_pair(self.root)
        self.assertEqual(hygiene.errors, [])

    def test_orphan_translation_warns_but_does_not_fail(self):
        self.write("guide.zh-CN.md", "# 指南\n\n[English](guide.md) | 简体中文\n")
        hygiene.check_bilingual_pair(self.root)
        self.assertEqual(hygiene.errors, [])
        self.assertTrue(hygiene.warnings)


class CommentLanguageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        hygiene.errors.clear()
        hygiene.warnings.clear()
        hygiene.doc_warnings.clear()

    def test_chinese_comment_warns_without_failing(self):
        (self.root / "module.py").write_text("# 这里等待重试\nvalue = 1\n", encoding="utf-8")
        hygiene.check_comment_language(self.root)
        self.assertEqual(hygiene.errors, [])
        self.assertTrue(hygiene.warnings)
        self.assertEqual(hygiene.doc_warnings, [])

    def test_chinese_string_literal_is_not_a_comment(self):
        (self.root / "module.py").write_text('MESSAGE = "重试失败"\n', encoding="utf-8")
        hygiene.check_comment_language(self.root)
        self.assertEqual(hygiene.warnings, [])

    def test_english_comment_passes(self):
        (self.root / "module.py").write_text("# wait before retrying\nvalue = 1\n", encoding="utf-8")
        hygiene.check_comment_language(self.root)
        self.assertEqual(hygiene.warnings, [])


if __name__ == "__main__":
    unittest.main()
