"""Audit Git commit candidates without printing matched private values."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {"config", "state", "reports", "logs", "observed", "browser-profile", ".venv", "__pycache__"}
PRIVATE_NAMES = {"forms.json", "settings.json", "paths.json", "installation.json", ".formfiller-owner.json", "Accommodation Log.txt"}
TEXT_SUFFIXES = {".py", ".ps1", ".bat", ".md", ".txt", ".html", ".js", ".css", ".svg"}
PATTERNS = {
    "personal_windows_path": re.compile(r"(?i)(?:[A-Z]:[\\/]+Users[\\/]+[^\s\\/\"']+|OneDrive\s*-\s*)"),
    "email_address": re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    "ssn_shape": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone_shape": re.compile(r"(?<!\d)(?:\(\d{3}\)\s*\d{3}[- .]\d{4}|\d{3}[- .]\d{3}[- .]\d{4})(?!\d)"),
    "secret_shape": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{25,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"),
}
FORM_LINK = re.compile(r"https://forms\.(?:office\.com|cloud\.microsoft)/[^\s\"'<>]*", re.I)


def inspect_file(relative, raw):
    """Return sanitized finding codes only; never return a matched value."""
    path = Path(relative)
    if (any(part.lower() in PRIVATE_PARTS for part in path.parts) or path.name in PRIVATE_NAMES
            or path.name.startswith(".env") or path.suffix.lower() in {".pem", ".key"}
            or relative.startswith("tools/artifacts/")):
        return ["private_file"]
    if (path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".gitignore", ".gitattributes"}
            and relative != ".githooks/pre-commit"):
        return ["unreviewed_file_type"]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        return ["binary_or_non_utf8_file"]
    findings = [code for code, pattern in PATTERNS.items() if pattern.search(text)]
    for match in FORM_LINK.finditer(text):
        url = urlsplit(match.group())
        identifiers = parse_qs(url.query).get("id", [])
        if (identifiers and any(not identifier.startswith("synthetic-") for identifier in identifiers)) or url.path.startswith("/r/"):
            findings.append("non_synthetic_form_link")
            break
    return sorted(set(findings))


def git(args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return result.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Read the exact staged blobs, including forced additions.")
    args = parser.parse_args(argv)
    try:
        command = ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"] if args.staged else ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        names = sorted(set(name.decode("utf-8") for name in git(command).split(b"\0") if name))
        findings = []
        for index, name in enumerate(names, 1):
            if args.staged:
                raw = git(["show", ":" + name])
                metadata = git(["ls-files", "-s", "--", name])
                linked = metadata.startswith(b"120000 ")
            else:
                path = ROOT / name
                linked = path.is_symlink() or path.is_junction()
                raw = b"" if linked else path.read_bytes()
            codes = ["linked_file"] if linked else inspect_file(name, raw)
            if codes:
                findings.append({"file_index": index, "codes": codes})
        print(json.dumps({"files_checked": len(names), "findings": findings, "mode": "staged" if args.staged else "candidates"}))
        return 1 if findings else 0
    except Exception:
        print(json.dumps({"error": "privacy_audit_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
