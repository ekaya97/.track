"""Static security scanner — detect hardcoded secrets and dangerous patterns."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

# ── Test file detection (shared pattern) ──────────────────────────────────────

_TEST_PATH_RE = re.compile(
    r"(^|/)(test_|tests/|__tests__/)|(_test|\.test|\.spec)\.[^/]+$"
)


def _is_test_file(path: str) -> bool:
    return bool(_TEST_PATH_RE.search(path))


# ── Known secret prefixes ────────────────────────────────────────────────────

SECRET_PREFIXES = [
    ("AKIA", "AKIA prefix (AWS key)"),
    ("sk_live_", "Stripe live secret key"),
    ("sk_test_", "Stripe test secret key"),
    ("ghp_", "GitHub personal access token (ghp_)"),
    ("gho_", "GitHub OAuth token (gho_)"),
    ("github_pat_", "GitHub personal access token (github_pat_)"),
    ("xoxb-", "Slack bot token (xoxb-)"),
    ("xoxp-", "Slack user token (xoxp-)"),
    ("eyJ", "JWT token (eyJ)"),
]

# ── Secret assignment patterns ────────────────────────────────────────────────

SECRET_ASSIGN_RE = re.compile(
    r"""(?:password|secret|api_key|apikey|token|auth)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)

# ── Dangerous pattern detectors ───────────────────────────────────────────────

# SQL keywords in f-strings or .format()
_SQL_FSTRING_RE = re.compile(
    r"""f["'].*\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER)\b.*\{""",
    re.IGNORECASE,
)
_SQL_FORMAT_RE = re.compile(
    r"""["'].*\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER)\b.*["']\.format\(""",
    re.IGNORECASE,
)

# yaml.load without SafeLoader
_YAML_UNSAFE_RE = re.compile(r"yaml\.load\s*\([^)]*\)")
_YAML_SAFE_RE = re.compile(r"yaml\.load\s*\([^)]*Loader\s*=")


# ── Entropy calculation ──────────────────────────────────────────────────────


def _entropy(s: str) -> float:
    """Calculate Shannon entropy of a string in bits per character."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    length = len(s)
    ent = 0.0
    for count in freq.values():
        p = count / length
        if p > 0:
            ent -= p * math.log2(p)
    return ent


# ── Main scanner ─────────────────────────────────────────────────────────────


def scan_security(files: list[tuple[str, str]]) -> dict:
    """Scan files for security issues.

    Args:
        files: List of (file_path, source_code) tuples.

    Returns:
        Dict with findings and stats.
    """
    findings: list[dict] = []
    files_scanned = 0

    for file_path, source in files:
        # Skip test files for secret detection
        is_test = _is_test_file(file_path)
        files_scanned += 1

        for line_num, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()

            # Skip comments
            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            # ── Hardcoded secrets (skip in test files) ────────────────
            if not is_test:
                _check_secrets(file_path, line_num, line, findings)

            # ── Dangerous patterns (check everywhere) ─────────────────
            _check_dangerous(file_path, line_num, line, stripped, findings)

    # ── Stats ─────────────────────────────────────────────────────────
    stats = {
        "files_scanned": files_scanned,
        "findings_high": sum(1 for f in findings if f["severity"] == "high"),
        "findings_medium": sum(1 for f in findings if f["severity"] == "medium"),
        "findings_low": sum(1 for f in findings if f["severity"] == "low"),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "findings": findings,
        "stats": stats,
    }


def _check_secrets(
    file_path: str, line_num: int, line: str, findings: list[dict]
) -> None:
    """Check a line for hardcoded secrets."""
    # Known prefix patterns
    for prefix, description in SECRET_PREFIXES:
        if prefix in line:
            # Extract the string containing the prefix
            match = re.search(rf"""["']({re.escape(prefix)}[^"']+)["']""", line)
            if match:
                snippet = line.strip()
                if len(snippet) > 80:
                    snippet = snippet[:77] + "..."
                findings.append({
                    "type": "hardcoded_secret",
                    "severity": "high",
                    "file": file_path,
                    "line": line_num,
                    "pattern": f"{description}",
                    "snippet": snippet,
                })
                return  # One finding per line

    # Assignment patterns: password = "...", secret = "...", etc.
    m = SECRET_ASSIGN_RE.search(line)
    if m:
        value = m.group(1)
        if len(value) > 8:  # Non-trivial value
            snippet = line.strip()
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."
            findings.append({
                "type": "hardcoded_secret",
                "severity": "high",
                "file": file_path,
                "line": line_num,
                "pattern": "Hardcoded credential in assignment",
                "snippet": snippet,
            })
            return

    # High-entropy strings in assignments
    str_match = re.search(r"""=\s*["']([A-Za-z0-9+/=_\-]{16,})["']""", line)
    if str_match:
        value = str_match.group(1)
        if _entropy(value) > 4.5:
            snippet = line.strip()
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."
            findings.append({
                "type": "hardcoded_secret",
                "severity": "medium",
                "file": file_path,
                "line": line_num,
                "pattern": "High-entropy string in assignment",
                "snippet": snippet,
            })


def _check_dangerous(
    file_path: str, line_num: int, line: str, stripped: str, findings: list[dict]
) -> None:
    """Check a line for dangerous code patterns."""
    # eval() / exec() with non-constant argument
    for func in ("eval", "exec"):
        pattern = rf"\b{func}\s*\("
        if re.search(pattern, stripped):
            # Check if argument is a literal string
            literal_check = rf"""{func}\s*\(\s*["']"""
            if not re.search(literal_check, stripped):
                snippet = stripped[:80]
                findings.append({
                    "type": "dangerous_pattern",
                    "severity": "medium",
                    "file": file_path,
                    "line": line_num,
                    "pattern": f"{func}() with variable argument",
                    "snippet": snippet,
                })

    # os.system()
    if "os.system(" in stripped:
        findings.append({
            "type": "dangerous_pattern",
            "severity": "medium",
            "file": file_path,
            "line": line_num,
            "pattern": "os.system() call",
            "snippet": stripped[:80],
        })

    # subprocess with shell=True
    if "shell=True" in stripped and "subprocess" in stripped:
        findings.append({
            "type": "dangerous_pattern",
            "severity": "medium",
            "file": file_path,
            "line": line_num,
            "pattern": "subprocess with shell=True",
            "snippet": stripped[:80],
        })

    # SQL injection via f-strings or .format()
    if _SQL_FSTRING_RE.search(line) or _SQL_FORMAT_RE.search(line):
        findings.append({
            "type": "dangerous_pattern",
            "severity": "high",
            "file": file_path,
            "line": line_num,
            "pattern": "SQL string with variable interpolation",
            "snippet": stripped[:80],
        })

    # pickle.loads()
    if "pickle.loads(" in stripped or "pickle.load(" in stripped:
        findings.append({
            "type": "dangerous_pattern",
            "severity": "medium",
            "file": file_path,
            "line": line_num,
            "pattern": "pickle.loads() — unsafe deserialization",
            "snippet": stripped[:80],
        })

    # yaml.load() without SafeLoader
    if _YAML_UNSAFE_RE.search(stripped) and not _YAML_SAFE_RE.search(stripped):
        findings.append({
            "type": "dangerous_pattern",
            "severity": "medium",
            "file": file_path,
            "line": line_num,
            "pattern": "yaml.load() without SafeLoader",
            "snippet": stripped[:80],
        })
