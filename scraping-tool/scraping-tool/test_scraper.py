#!/usr/bin/env python3
"""
Tests for scraper.py

Tests extract_emails_from_url and generate_email_draft using unittest.mock
so no real network requests are made.

Run with:  python test_scraper.py
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

_results = {"passed": 0, "failed": 0}


def result(name, ok, detail=""):
    tag = PASS if ok else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{tag}] {name}{suffix}")
    if ok:
        _results["passed"] += 1
    else:
        _results["failed"] += 1


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

try:
    from scraper import extract_emails_from_url, generate_email_draft
    result("Import scraper.py", True)
except ImportError as e:
    result("Import scraper.py", False, str(e))
    print("\nCannot continue without scraper.py — aborting.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helper: build a fake requests.Response
# ---------------------------------------------------------------------------

def _fake_response(html: str, status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = html
    mock_resp.raise_for_status = MagicMock()  # does nothing (no error)
    return mock_resp


def _fake_response_error(status_code: int = 404):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return mock_resp


# ---------------------------------------------------------------------------
# Tests: extract_emails_from_url
# ---------------------------------------------------------------------------

print("\n--- extract_emails_from_url ---")

# 1. mailto: link is extracted
with patch("scraper.requests.get") as mock_get:
    html = '<html><body><a href="mailto:info@example.si">Contact</a></body></html>'
    mock_get.return_value = _fake_response(html)
    emails = extract_emails_from_url("http://test.example.si")
    result(
        "mailto: link extracted",
        emails == ["info@example.si"],
        f"got {emails}",
    )

# 2. mailto: with query string stripped
with patch("scraper.requests.get") as mock_get:
    html = '<a href="mailto:sales@myshop.si?subject=Hello">Email us</a>'
    mock_get.return_value = _fake_response(html)
    emails = extract_emails_from_url("http://myshop.si")
    result(
        "mailto: query string stripped",
        emails == ["sales@myshop.si"],
        f"got {emails}",
    )

# 3. Multiple mailto: links deduplicated and sorted
with patch("scraper.requests.get") as mock_get:
    html = """
    <a href="mailto:zebra@firma.si">Z</a>
    <a href="mailto:alpha@firma.si">A</a>
    <a href="mailto:alpha@firma.si">A again</a>
    """
    mock_get.return_value = _fake_response(html)
    emails = extract_emails_from_url("http://firma.si")
    result(
        "Multiple mailto: links deduplicated and sorted",
        emails == ["alpha@firma.si", "zebra@firma.si"],
        f"got {emails}",
    )

# 4. Regex fallback when no mailto: links
with patch("scraper.requests.get") as mock_get:
    html = "<html><body>Contact us at support@widget.si for help.</body></html>"
    mock_get.return_value = _fake_response(html)
    emails = extract_emails_from_url("http://widget.si")
    result(
        "Regex fallback finds email in plain text",
        "support@widget.si" in emails,
        f"got {emails}",
    )

# 5. Ignored domains filtered out
with patch("scraper.requests.get") as mock_get:
    html = """
    <html><body>
      <a href="mailto:noreply@example.com">bad</a>
      <a href="mailto:real@podjetje.si">good</a>
    </body></html>
    """
    mock_get.return_value = _fake_response(html)
    emails = extract_emails_from_url("http://podjetje.si")
    result(
        "Ignored domain (example.com) filtered out",
        emails == ["real@podjetje.si"],
        f"got {emails}",
    )

# 6. No emails found — returns empty list
with patch("scraper.requests.get") as mock_get:
    html = "<html><body><p>No contact info here.</p></body></html>"
    mock_get.return_value = _fake_response(html)
    emails = extract_emails_from_url("http://silent.si")
    result(
        "No emails found returns empty list",
        emails == [],
        f"got {emails}",
    )

# 7. HTTP error returns empty list (no crash)
with patch("scraper.requests.get") as mock_get:
    mock_get.return_value = _fake_response_error(404)
    emails = extract_emails_from_url("http://gone.si")
    result(
        "HTTP error returns empty list gracefully",
        emails == [],
        f"got {emails}",
    )

# 8. Network exception returns empty list (no crash)
with patch("scraper.requests.get") as mock_get:
    mock_get.side_effect = ConnectionError("Network unreachable")
    emails = extract_emails_from_url("http://offline.si")
    result(
        "Network exception returns empty list gracefully",
        emails == [],
        f"got {emails}",
    )

# 9. Emails normalised to lowercase
with patch("scraper.requests.get") as mock_get:
    html = '<a href="mailto:Info@Podjetje.SI">Contact</a>'
    mock_get.return_value = _fake_response(html)
    emails = extract_emails_from_url("http://podjetje.si")
    result(
        "Emails normalised to lowercase",
        emails == ["info@podjetje.si"],
        f"got {emails}",
    )

# 10. Regex fallback ignored-domain filtering
with patch("scraper.requests.get") as mock_get:
    # Only contains a sentry.io address — should be filtered out
    html = "<body>Error tracked at errors@sentry.io by our system.</body>"
    mock_get.return_value = _fake_response(html)
    emails = extract_emails_from_url("http://app.si")
    result(
        "Regex fallback: ignored domain (sentry.io) filtered",
        emails == [],
        f"got {emails}",
    )

# ---------------------------------------------------------------------------
# Tests: generate_email_draft
# ---------------------------------------------------------------------------

print("\n--- generate_email_draft ---")

def _make_biz(ime, emaili=None, telefon="", naslov="", spletna_stran=""):
    return {
        "ime": ime,
        "emaili": emaili or [],
        "telefon": telefon,
        "naslov": naslov,
        "spletna_stran": spletna_stran,
    }


# 11. File is created and contains expected content
with tempfile.TemporaryDirectory() as tmpdir:
    outfile = os.path.join(tmpdir, "draft.txt")
    businesses = [
        _make_biz("Frizerstvo Maja", ["maja@frizer.si"], "041 111 222", "Ljubljana", "https://frizer.si"),
    ]
    generate_email_draft(businesses, "Poslovna ponudba", "Spoštovani {ime},\n\nLep pozdrav.", outfile)

    exists = os.path.isfile(outfile)
    result("Output file created", exists)

    if exists:
        with open(outfile, encoding="utf-8") as f:
            content = f.read()
        result("Recipient email in file",    "maja@frizer.si"    in content, )
        result("Subject line in file",       "Poslovna ponudba"  in content, )
        result("{ime} replaced with name",   "Frizerstvo Maja"   in content and "{ime}" not in content)
        result("Phone number in file",       "041 111 222"       in content, )
        result("Website in file",            "https://frizer.si" in content, )

# 12. Business without email appears in "brez emaila" section
with tempfile.TemporaryDirectory() as tmpdir:
    outfile = os.path.join(tmpdir, "draft_no_email.txt")
    businesses = [
        _make_biz("Brez Emaila d.o.o.", emaili=[], telefon="040 999 888"),
    ]
    generate_email_draft(businesses, "Test zadeva", "Sporocilo.", outfile)
    with open(outfile, encoding="utf-8") as f:
        content = f.read()
    result(
        "No-email business listed in 'BREZ EMAILA' section",
        "Brez Emaila d.o.o." in content and "BREZ EMAILA" in content,
    )

# 13. Mixed: some with email, some without
with tempfile.TemporaryDirectory() as tmpdir:
    outfile = os.path.join(tmpdir, "draft_mixed.txt")
    businesses = [
        _make_biz("Podjetje Z Mailom", ["info@z-mailom.si"]),
        _make_biz("Podjetje Brez Maila"),
    ]
    generate_email_draft(businesses, "Zadeva", "Sporocilo.", outfile)
    with open(outfile, encoding="utf-8") as f:
        content = f.read()
    result(
        "Mixed list: both sections present",
        "Z emailom:       1" in content and "Brez emaila:     1" in content,
    )

# 14. Business with multiple emails generates one entry per email
with tempfile.TemporaryDirectory() as tmpdir:
    outfile = os.path.join(tmpdir, "draft_multi_email.txt")
    businesses = [
        _make_biz("Multi Mail", ["a@multi.si", "b@multi.si"]),
    ]
    generate_email_draft(businesses, "Z", "Msg.", outfile)
    with open(outfile, encoding="utf-8") as f:
        content = f.read()
    result(
        "Multiple emails: each appears as separate recipient",
        "a@multi.si" in content and "b@multi.si" in content,
    )

# 15. Empty business list writes file without crashing
with tempfile.TemporaryDirectory() as tmpdir:
    outfile = os.path.join(tmpdir, "draft_empty.txt")
    generate_email_draft([], "Zadeva", "Msg.", outfile)
    result(
        "Empty business list writes file without error",
        os.path.isfile(outfile),
    )

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _results["passed"] + _results["failed"]
print()
print("=" * 50)
print(f"Results: {_results['passed']}/{total} tests passed", end="")
if _results["failed"]:
    print(f"  |  {_results['failed']} FAILED")
    sys.exit(1)
else:
    print("  — all good!")
print("=" * 50)
