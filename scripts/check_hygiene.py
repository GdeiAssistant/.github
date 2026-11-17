#!/usr/bin/env python3
"""Repository documentation, naming, anti-leak, and agent-file hygiene checker.

Usage:
    python scripts/check_hygiene.py               # check public repository
    python scripts/check_hygiene.py --private     # check private repository
    python scripts/check_hygiene.py --strict-docs # treat doc warnings as failures
    python scripts/check_hygiene.py --strict      # treat all warnings as failures

Exit code 0 means pass, 1 means at least one blocking violation.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
import urllib.parse
from pathlib import Path

# Files whose names are fixed by GitHub or by long-standing community
# convention. They are exempt from the lowercase / hyphen rules.
CONVENTIONAL_ANYWHERE = {
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SUPPORT.md",
    "LICENSE",
    "LICENSE.md",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARK.md",
    "CHANGELOG.md",
    "AGENTS.md",
    "CLAUDE.md",
}
CONVENTIONAL_ROOT_ONLY = {"CLAUDE.md", "LICENSE"}

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    "build", "dist", ".next", ".gradle", ".agents",
}

# Banned filename patterns.
BANNED_PATTERNS = [
    (re.compile(r"(?<!\d)20\d{2}[-_]?\d{2}[-_]?\d{2}(?!\d)"), "filename contains a date (dates belong to commit history)"),
    (re.compile(r"[-_]v\d+(\.\d+)*$"), "filename ends with a version number (that is a document version, not content)"),
    (re.compile(r"^(v|version)\d+$"), "filename is just a version number"),
    (re.compile(r"[-_](new|old|tmp|temp|final|draft|latest|backup)([-_.]|$)", re.I), "filename contains a stage word"),
    (re.compile(r"[-_](status|current|wip)([-_.]|$)", re.I), "filename contains a status word (it becomes a lie the moment the status changes)"),
    (re.compile(r"(luna|handoff|superpower)", re.I), "filename contains an internal codename"),
]

# Directories split by phase rather than by subject.
BANNED_DIR = re.compile(
    r"^(upgrade-v\d+|v\d+|plans?|handoffs?|audits?|superpowers?|archive|old|tmp)$", re.I
)

# Documents that must not enter the repository.
# Files under prompts/, .github/, and templates/ are templates, not records.
FORBIDDEN_DOC = re.compile(
    r"(audit|postmortem|retrospective|-review-|_review_|^review-|-handoff)", re.I
)
FORBIDDEN_DOC_SKIP_DIRS = {"prompts", ".github", "templates"}

AGENTS_SECTIONS = ["项目是什么", "技术栈", "目录", "本地验证", "命名与文档", "不要做", "提交与 PR"]
AGENTS_SECTIONS_ZH = AGENTS_SECTIONS
AGENTS_SECTIONS_EN = [
    "What this repository is",
    "Stack",
    "Layout",
    "Local checks",
    "Do not",
    "Commits and pull requests",
]

CONTENT_BOUNDARY = "<!-- content-boundary:begin -->"

REQUIRED_GITIGNORE_PATTERNS = [
    "docs/audits/",
    "docs/plans/",
    "docs/handoffs/",
    "docs/changes/",
    "docs/acceptance-policy.md",
    ".claude/",
    ".codex/",
    ".local/",
    "ops-notes/",
    "*.local.md",
    "*.internal.md",
]

FENCED_BLOCK_RE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
CODE_SPAN_RE = re.compile(r"`[^`\n]+`")
RE_PATCH_PROSE = re.compile(
    r"\b(this change|this pr|in this pr|this policy pr|remains? unchanged)\b",
    re.IGNORECASE,
)
RE_PHASE_HEADING = re.compile(r"^#{1,4}\s+.*\bP0[–-]P\d+\b", re.MULTILINE)
RE_LICENSE_HEADING = re.compile(r"^##\s+(?:License|许可证)\s*$")
RE_H2_HEADING = re.compile(r"^##\s+\S+")

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
LOCALE_RE = re.compile(r"^(?P<stem>.+?)\.(?P<loc>[A-Za-z_-]+)\.md$")

ALLOWED_LOCALES = {"zh-CN", "en"}
LANGUAGE_ROOTS = {"zh", "cn", "en"}

MAX_PARAGRAPH = 400
SOFT_AGENTS_LINES = 100
MAX_AGENTS_LINES = 120

REQUIRED_OPEN_SOURCE = [
    "CONTRIBUTING.md",
    "SECURITY.md",
    ".github/pull_request_template.md",
]


def git_visible_files(root: Path) -> set[Path] | None:
    """Return tracked and unignored working-tree files when root is a Git checkout."""
    if not (root / ".git").exists():
        return None
    res = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if res.returncode != 0:
        return None
    visible: set[Path] = set()
    for raw in res.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="surrogateescape")
        candidate = root / rel
        if candidate.is_file():
            visible.add(candidate)
    return visible


def is_untracked_gitignored(root: Path, rel_path: str) -> bool:
    """Return True only when rel_path has no tracked/unignored files and is gitignored."""
    if not (root / ".git").exists():
        return False
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", rel_path],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if listed.returncode == 0 and listed.stdout.strip(b"\0"):
        return False
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", rel_path],
        cwd=root,
        check=False,
    )
    return ignored.returncode == 0


def iter_files(root: Path):
    visible = git_visible_files(root)
    if visible is not None:
        for p in sorted(visible):
            if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
                continue
            yield p
        return
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            yield p


def strip_fenced_blocks(text: str) -> str:
    return FENCED_BLOCK_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def blank_code_spans(text: str) -> str:
    return CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), text)


def split_locale(name: str) -> tuple[str, str | None]:
    """Split runbook.zh-CN.md into ('runbook', 'zh-CN')."""
    m = LOCALE_RE.match(name)
    if m:
        tag = m.group("loc")
        root = re.split(r"[-_]", tag)[0].lower()
        if root in LANGUAGE_ROOTS:
            return m.group("stem"), tag
    return name[:-3], None


def locale_error(locale: str) -> str | None:
    """Return the error for a bad locale suffix, or None when it is valid."""
    if locale in ALLOWED_LOCALES:
        return None
    return f"locale suffix must be .zh-CN.md or .en.md, not .{locale}.md"


def check_filename(root: Path, path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    rel = path.relative_to(root)
    name = path.name

    if rel.parts and rel.parts[0] == ".github":
        return errors, warnings

    stem, locale = split_locale(name) if name.endswith(".md") else (name, None)
    base = f"{stem}.md"

    if base in CONVENTIONAL_ANYWHERE:
        if base in CONVENTIONAL_ROOT_ONLY and rel.parent != Path("."):
            warnings.append(f"{rel}: {base} belongs at the repository root")
        if locale:
            msg = locale_error(locale)
            if msg:
                errors.append(f"{rel}: {msg}")
        return errors, warnings

    if path.suffix not in {".md", ".yml", ".yaml"}:
        return errors, warnings

    if stem != stem.lower():
        errors.append(f"{rel}: filename must be all lowercase")
    if "_" in stem:
        errors.append(f"{rel}: join words with -, not _")
    if " " in name:
        errors.append(f"{rel}: filename must not contain spaces")
    if any(unicodedata.east_asian_width(c) in "WF" for c in name):
        errors.append(f"{rel}: filename must be ASCII")

    for pattern, reason in BANNED_PATTERNS:
        if pattern.search(stem):
            errors.append(f"{rel}: {reason}")

    if locale:
        msg = locale_error(locale)
        if msg:
            errors.append(f"{rel}: {msg}")

    return errors, warnings


def check_dirs(root: Path) -> list[str]:
    errors: list[str] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_dir() and BANNED_DIR.match(p.name):
            if is_untracked_gitignored(root, f"{rel.as_posix()}/"):
                continue
            errors.append(f"{rel}/: do not split directories by phase, see section 1.3")
    return errors


def check_doc_type(root: Path, path: Path) -> list[str]:
    rel = path.relative_to(root)
    if any(part in FORBIDDEN_DOC_SKIP_DIRS for part in rel.parts[:-1]):
        return []
    if FORBIDDEN_DOC.search(path.stem):
        return [f"{rel}: audit / retrospective / handoff documents do not enter the repository, see section 2.2"]
    return []


def check_links(root: Path, path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    rel = path.relative_to(root)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return errors, warnings
    cleaned = blank_code_spans(strip_fenced_blocks(text))
    for m in LINK_RE.finditer(cleaned):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#", "<")):
            continue
        resolved = (path.parent / urllib.parse.unquote(target.split("#")[0])).resolve()
        if not resolved.is_relative_to(root):
            warnings.append(f"{rel}: cross-repository reference, not checked -> {target}")
            continue
        if not resolved.exists():
            errors.append(f"{rel}: broken link -> {target}")
    return errors, warnings


def check_readme_quality(root: Path) -> list[str]:
    errors: list[str] = []
    for name in ("README.md", "README.zh-CN.md"):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        unfenced = strip_fenced_blocks(text)
        prose = blank_code_spans(unfenced)

        for m in RE_PATCH_PROSE.finditer(prose):
            errors.append(f"{name}: PR-diff narration in README prose -> '{m.group(0)}'")
        for m in RE_PHASE_HEADING.finditer(prose):
            errors.append(f"{name}: phase-milestone heading in README -> '{m.group(0).strip()}'")

        seen_license = False
        for raw_line in unfenced.splitlines():
            stripped = raw_line.strip()
            if RE_LICENSE_HEADING.match(stripped):
                seen_license = True
                continue
            if seen_license and RE_H2_HEADING.match(stripped):
                errors.append(f"{name}: section placed after License/许可证 heading -> '{stripped}'")
    return errors


def check_public_internal_artifacts(root: Path, private: bool = False) -> list[str]:
    if private:
        return []
    errors: list[str] = []
    if (root / "docs" / "changes").is_dir() and not is_untracked_gitignored(root, "docs/changes/"):
        errors.append("docs/changes/: internal change directory must not remain in a public repository")
    if (root / "docs" / "acceptance-policy.md").exists() and not is_untracked_gitignored(
        root, "docs/acceptance-policy.md"
    ):
        errors.append("docs/acceptance-policy.md: internal acceptance policy must not remain in a public repository")
    return errors


HEAD_LINES = 15


def check_bilingual_pair(root: Path) -> tuple[list[str], list[str]]:
    """When both languages exist, the two files link to each other near the top."""
    errors: list[str] = []
    warnings: list[str] = []
    for p in iter_files(root):
        if p.suffix != ".md":
            continue
        stem, locale = split_locale(p.name)
        if not locale:
            continue
        base = p.with_name(f"{stem}.md")
        rel = p.relative_to(root)
        if not base.exists():
            warnings.append(f"{rel}: has a .{locale}.md version but no {base.name}; a single-language file needs no suffix")
            continue
        try:
            translated = "\n".join(p.read_text(encoding="utf-8", errors="ignore").split("\n")[:HEAD_LINES])
            original = "\n".join(base.read_text(encoding="utf-8", errors="ignore").split("\n")[:HEAD_LINES])
        except OSError:
            continue
        if base.name not in translated:
            errors.append(f"{rel}: no link back to {base.name} near the top")
        if p.name not in original:
            errors.append(f"{base.relative_to(root)}: no link to {p.name} near the top")
    return errors, warnings


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
COMMENT_SYNTAX = {
    ".py": ("#",), ".rb": ("#",), ".sh": ("#",), ".bash": ("#",), ".zsh": ("#",),
    ".yml": ("#",), ".yaml": ("#",), ".toml": ("#",), ".tf": ("#",),
    ".js": ("//",), ".jsx": ("//",), ".ts": ("//",), ".tsx": ("//",), ".mjs": ("//",),
    ".java": ("//",), ".kt": ("//",), ".kts": ("//",), ".go": ("//",), ".rs": ("//",),
    ".swift": ("//",), ".cs": ("//",), ".c": ("//",), ".h": ("//",),
    ".cpp": ("//",), ".hpp": ("//",), ".m": ("//",), ".mm": ("//",),
    ".gradle": ("//",), ".scala": ("//",), ".dart": ("//",), ".php": ("//",),
}
CODE_SKIP_DIRS = SKIP_DIRS | {"migrations", "testdata", "fixtures", "vendor", "third_party"}


def check_comment_language(root: Path) -> list[str]:
    """Comments are English; grandfathered backlog emits warnings."""
    offenders: list[tuple[str, int]] = []
    for p in iter_files(root):
        prefixes = COMMENT_SYNTAX.get(p.suffix)
        if not prefixes:
            continue
        if any(part in CODE_SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits = 0
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped.startswith(prefixes):
                continue
            if CJK_RE.search(stripped):
                hits += 1
        if hits:
            offenders.append((str(p.relative_to(root)), hits))

    if offenders:
        total = sum(n for _, n in offenders)
        offenders.sort(key=lambda x: -x[1])
        top = ", ".join(f"{f}({n})" for f, n in offenders[:5])
        return [f"{len(offenders)} files carry {total} lines of non-English comments; write new ones in English — worst: {top}"]
    return []


def check_paragraphs(root: Path, path: Path) -> list[str]:
    warnings: list[str] = []
    rel = path.relative_to(root)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return warnings
    in_code = False
    buf: list[str] = []

    def flush() -> None:
        if buf:
            n = len("".join(buf))
            if n > MAX_PARAGRAPH:
                warnings.append(f"{rel}: paragraph runs {n} characters, limit is {MAX_PARAGRAPH}")
            buf.clear()

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        stripped = line.strip()
        if (
            not stripped
            or line.startswith("#")
            or re.match(r"^(?:[|*>-]|\d+\.)(?:\s|$)", stripped)
            or stripped.startswith("!")
        ):
            flush()
            continue
        buf.append(stripped)
    flush()
    return warnings


def check_agents(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if (root / ".github" / "engineering.md").exists() and not is_untracked_gitignored(
        root, ".github/engineering.md"
    ):
        errors.append(".github/engineering.md is retired; keep repository rules in AGENTS.md")

    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "-z", "--", "AGENTS.md", "CLAUDE.md"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    if tracked.returncode:
        errors.append("cannot read Git tracking state; run this from the repository root")
    else:
        names = set(tracked.stdout.split("\0"))
        for name in ("AGENTS.md", "CLAUDE.md"):
            if name not in names:
                errors.append(f"{name} is not tracked by Git; existing on disk does not mean committed")

    agents = root / "AGENTS.md"
    if not agents.exists():
        errors.append("AGENTS.md is missing")
        return errors, warnings
    lines = agents.read_text(encoding="utf-8", errors="ignore").split("\n")
    if len(lines) > MAX_AGENTS_LINES:
        errors.append(f"AGENTS.md has {len(lines)} lines, limit is {MAX_AGENTS_LINES}")
    elif len(lines) > SOFT_AGENTS_LINES:
        warnings.append(f"AGENTS.md has {len(lines)} lines; keep it under {SOFT_AGENTS_LINES}")

    text = "\n".join(lines)
    zh_missing = [
        s for s in AGENTS_SECTIONS_ZH
        if not re.search(rf"^##\s+{re.escape(s)}\b", text, re.MULTILINE)
    ]
    en_missing = [
        s for s in AGENTS_SECTIONS_EN
        if not re.search(rf"^##\s+{re.escape(s)}\b", text, re.MULTILINE)
    ]
    missing = en_missing if len(en_missing) < len(zh_missing) else zh_missing
    if missing:
        errors.append(f"AGENTS.md is missing sections: {', '.join(missing)}")
    if CONTENT_BOUNDARY not in text:
        errors.append("AGENTS.md is missing the content-boundary block")

    claude = root / "CLAUDE.md"
    if not claude.exists():
        errors.append("CLAUDE.md is missing; its content should be the single line @AGENTS.md")
    else:
        content = claude.read_text(encoding="utf-8", errors="ignore").strip()
        if content != "@AGENTS.md":
            errors.append("CLAUDE.md must be the single line @AGENTS.md, not a copy of the AGENTS.md body")

    return errors, warnings


def check_gitignore(root: Path) -> list[str]:
    gi = root / ".gitignore"
    if not gi.exists():
        return [".gitignore is missing"]
    errors: list[str] = []
    text = gi.read_text(encoding="utf-8", errors="ignore")
    missing = [pat for pat in REQUIRED_GITIGNORE_PATTERNS if pat not in text]
    if missing:
        errors.append(".gitignore is missing required anti-leak patterns: " + ", ".join(missing))
    if re.search(r"^\s*!\s*/?\.github/engineering\.md\s*$", text, re.MULTILINE):
        errors.append(".gitignore still unignores retired .github/engineering.md")
    return errors


def check_docs_baseline(root: Path, private: bool = False, require_coc: bool = False) -> list[str]:
    """Require community health files for public repos and SECURITY.md for private ones."""
    errors: list[str] = []
    if private:
        if not (root / "SECURITY.md").is_file():
            errors.append("private repository is missing SECURITY.md")
        return errors

    for rel in REQUIRED_OPEN_SOURCE:
        if not (root / rel).is_file():
            errors.append(f"{rel} is missing; an open-source repository must ship it")
    if require_coc and not (root / "CODE_OF_CONDUCT.md").is_file():
        errors.append("CODE_OF_CONDUCT.md is missing; an open-source repository must ship it")
    if not any((root / name).is_file() for name in ("LICENSE", "LICENSE.md", "LICENSE.txt")):
        errors.append("LICENSE is missing; an open-source repository must ship it")

    issue_dir = root / ".github" / "ISSUE_TEMPLATE"
    if not issue_dir.is_dir() or not any(issue_dir.iterdir()):
        errors.append(".github/ISSUE_TEMPLATE/ is missing or empty; add at least one issue form")
    return errors


def run_checks(
    root: Path, private: bool = False, require_coc: bool = False
) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    doc_warnings: list[str] = []

    errors.extend(check_dirs(root))
    for path in iter_files(root):
        fn_errs, fn_warns = check_filename(root, path)
        errors.extend(fn_errs)
        doc_warnings.extend(fn_warns)
        if path.suffix == ".md":
            errors.extend(check_doc_type(root, path))
            link_errs, link_warns = check_links(root, path)
            errors.extend(link_errs)
            doc_warnings.extend(link_warns)
            doc_warnings.extend(check_paragraphs(root, path))

    errors.extend(check_readme_quality(root))
    errors.extend(check_public_internal_artifacts(root, private=private))
    agent_errs, agent_warns = check_agents(root)
    errors.extend(agent_errs)
    doc_warnings.extend(agent_warns)

    pair_errs, pair_warns = check_bilingual_pair(root)
    errors.extend(pair_errs)
    doc_warnings.extend(pair_warns)

    code_warnings = check_comment_language(root)
    errors.extend(check_gitignore(root))
    errors.extend(check_docs_baseline(root, private=private, require_coc=require_coc))

    return errors, doc_warnings, code_warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="repository root")
    ap.add_argument("--strict", action="store_true", help="treat all warnings as failures")
    ap.add_argument("--strict-docs", action="store_true", help="treat documentation warnings as failures while keeping code-comment warnings non-blocking")
    ap.add_argument("--require-coc", action="store_true", help="require a local CODE_OF_CONDUCT.md instead of inheriting org defaults")
    ap.add_argument("--private", action="store_true", help="skip public-only OSS baseline and leak checks")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    errors, doc_warnings, code_warnings = run_checks(
        root, private=args.private, require_coc=args.require_coc
    )

    unique_errors = sorted(set(errors))
    unique_warnings = sorted(set(doc_warnings) | set(code_warnings))

    for w in unique_warnings:
        print(f"warning  {w}")
    for e in unique_errors:
        print(f"error    {e}")

    print(f"\n{len(unique_errors)} errors, {len(unique_warnings)} warnings")

    if unique_errors:
        return 1
    if args.strict and unique_warnings:
        return 1
    if args.strict_docs and doc_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
