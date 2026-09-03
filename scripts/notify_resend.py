#!/usr/bin/env python3
"""
notify_resend.py - dependency-free failure/alert email sender for the MLS pipeline.

WHY THIS EXISTS
---------------
Between 2026-08-26 and 2026-09-01 the mls-export job failed every morning
(expired Stellar SSO cookie) and Ryan was never told. The failure GUARD worked;
the NOTIFICATION did not. Alerts depended on gmail_create_draft plus the
BonesBot Auto-Send Apps Script: a two-hop chain where a silent break in either
hop produces exactly zero emails and zero warning.

This module removes both hops. It talks straight to the Resend API using only
the standard library, so an alert has one dependency (network) instead of three
(Gmail connector + Apps Script + network).

DESIGN RULES
------------
1. Standard library only. No pip install, so it cannot be broken by a
   dependency-resolution failure mid-run.
2. Browser User-Agent is MANDATORY. api.resend.com sits behind Cloudflare,
   which blocks the default python-urllib UA with error 1010. This cost real
   debugging time once (DECISIONS 2026-08-27); the UA is hardcoded below so it
   can never be forgotten again.
3. send_alert() NEVER raises. An alerting system that throws an exception and
   kills the run it was trying to report on is worse than no alerting. All
   failures are caught and returned as {"sent": False, "error": ...} so the
   caller can log it and continue.
4. Sends from the verified adamsonfl.com domain, matching the pattern already
   used by netlify/functions/community-lead.js.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

RESEND_ENDPOINT = "https://api.resend.com/emails"

# Cloudflare in front of api.resend.com rejects python-urllib's default UA
# with error 1010. Do not remove. See DECISIONS 2026-08-27.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)

DEFAULT_FROM = "The Adamson Group <Info@AdamsonFL.com>"
DEFAULT_REPLY_TO = "Ryan@adamson-group.com"
DEFAULT_TO = "Ryan@Adamson-Group.com"

# Where to look for a .env holding RESEND_API_KEY. Ordered most-specific first.
# /tmp/canonical_pipeline is where the scheduled job stages its scripts, so it
# is checked before the FUSE-mounted repo.
ENV_SEARCH_PATHS = [
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parent.parent / ".env",
    Path("/tmp/canonical_pipeline/.env"),
]


def load_env(extra_path=None):
    """Parse the first .env found into a dict. Never raises."""
    paths = ([Path(extra_path)] if extra_path else []) + ENV_SEARCH_PATHS
    for p in paths:
        try:
            if not p.is_file():
                continue
            env = {}
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
            if env:
                return env
        except Exception:
            continue
    return {}


def resolve_key(env=None, explicit=None):
    """RESEND_API_KEY from explicit arg, then process env, then .env file."""
    if explicit:
        return explicit
    if os.environ.get("RESEND_API_KEY"):
        return os.environ["RESEND_API_KEY"]
    return (env or load_env()).get("RESEND_API_KEY")


def send_alert(subject, text, to=None, html=None, api_key=None,
               from_addr=None, reply_to=None, tag=None, timeout=30):
    """
    Send an alert email via Resend.

    Returns a dict and NEVER raises:
      success -> {"sent": True,  "id": "<resend id>", "via": "resend"}
      failure -> {"sent": False, "error": "<reason>", "via": "resend"}
    """
    env = load_env()
    key = resolve_key(env, api_key)
    if not key:
        return {"sent": False, "error": "RESEND_API_KEY not found in env or .env",
                "via": "resend"}

    recipients = to if isinstance(to, list) else [to or DEFAULT_TO]

    # A subject prefix makes these trivially filterable in Gmail and makes it
    # obvious at a glance that the message is machine-generated.
    if tag and not subject.startswith("["):
        subject = "[" + tag + "] " + subject

    payload = {
        "from": from_addr or env.get("RESEND_FROM") or DEFAULT_FROM,
        "to": recipients,
        "reply_to": reply_to or env.get("RESEND_REPLY_TO") or DEFAULT_REPLY_TO,
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html

    req = urllib.request.Request(
        RESEND_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            data = json.loads(body) if body.strip().startswith("{") else {}
            return {"sent": True, "id": data.get("id"), "status": r.status,
                    "via": "resend"}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        # 403 + "1010" is the Cloudflare UA block. Should be impossible given
        # BROWSER_UA above, but name it explicitly so the cause is never
        # re-debugged from scratch.
        if "1010" in detail:
            detail += " (Cloudflare UA block - BROWSER_UA may have been altered)"
        return {"sent": False, "error": "HTTP " + str(e.code) + ": " + detail,
                "via": "resend"}
    except Exception as e:
        return {"sent": False, "error": type(e).__name__ + ": " + str(e),
                "via": "resend"}


# Plain-language explanations keyed to the failed_step values the job emits.
# Ryan reads these on a phone at 7am; each one says what broke and what to do.
COMMON_CAUSES = {
    "matrix_session_expired":
        "Your Stellar MLS sign-in expired. Open https://www.stellarmls.com/ in "
        "Chrome on the mini-PC, click MLS Login, enter your password and finish "
        "the SMS 2FA. One sign-in usually buys 2+ weeks of unattended runs. The "
        "automation cannot type passwords or 2FA codes, so this needs you.",
    "auto_mount_missing":
        "A folder the job needs is gone or renamed (most likely "
        "automation/AG_website). Restore it, or fix the mount path in the task.",
    "pip_install":
        "Python dependency install failed - network/PyPI issue, or disk full.",
    "disk_space_low":
        "A drive has under 1GB free even after the 14-day cleanup. Usually needs "
        "a Claude app restart to rebuild the VM.",
    "canonical_restore":
        "Could not fetch the pipeline scripts from GitHub. Usually an expired "
        "GITHUB_TOKEN (rotate per scripts/PAT_SETUP.md) or a GitHub outage.",
    "integrity_check":
        "Pipeline scripts failed their checksum check - they changed between "
        "fetch and execution. Rare; treat as a bug.",
    "github_token_missing":
        "GITHUB_TOKEN is missing from .env. See scripts/PAT_SETUP.md.",
    "chrome_not_connected":
        "The Claude Chrome extension is not connected. Chrome must be RUNNING "
        "with a window open and the side panel signed in to bonesbot2026@gmail.com.",
    "saved_search_empty":
        "Matrix returned 0 records for '000 - Market Update'. Check the saved "
        "search still exists and has criteria.",
    "staging_invariant":
        "Wrong number of batch CSVs reached staging - an export silently failed.",
    "row_count_assertion":
        "The combined CSV row count did not match what Matrix reported.",
    "ingest":
        "Supabase load failed - connection or schema issue. If the header guard "
        "aborted, the export column set drifted from the ingest map; check "
        "_shared/DECISIONS.md for a pending migration.",
    "publish":
        "Area stats could not be regenerated or pushed. Data IS safely in "
        "Postgres; only the website rebuild was skipped.",
    "tally_mismatch":
        "Reconciliation math did not add up - the ingest may have dropped or "
        "duplicated rows. Worth a manual look.",
    "no_run":
        "The job did not run at all today, or died before it could report. "
        "Check that the mini-PC is awake and the Claude desktop app is open.",
}


def build_failure_body(failed_step, error_message=None, details=None,
                       status_path=None):
    """Compose the plain-text failure alert."""
    cause = COMMON_CAUSES.get(
        failed_step, "Unrecognized failure step - check the run output."
    )
    lines = [
        "The daily MLS export did not finish.",
        "",
        "FAILED AT: " + str(failed_step),
        "",
        "WHAT IT MEANS",
        cause,
        "",
    ]
    if error_message:
        lines += ["ERROR", str(error_message)[:1500], ""]
    if details:
        lines += ["RUN DETAIL", str(details)[:1500], ""]
    lines += [
        "IMPACT",
        "No new MLS data was loaded. Postgres and the public site are still "
        "serving the last successful run's numbers, which look normal but are "
        "stale. Anything you quote today should be checked against the MLS.",
        "",
    ]
    if status_path:
        lines += ["Status JSON: " + str(status_path), ""]
    lines += ["This alert was sent directly through Resend, bypassing Gmail.",
              "", "- BonesBot"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="Send an MLS pipeline alert via Resend.")
    ap.add_argument("--subject")
    ap.add_argument("--text", help="Body text. Use --text-file for long bodies.")
    ap.add_argument("--text-file", help="Read body from this file.")
    ap.add_argument("--html-file", help="Optional HTML body from this file.")
    ap.add_argument("--to", action="append",
                    help="Recipient (repeatable). Defaults to Ryan.")
    ap.add_argument("--tag", default="MLS",
                    help="Subject prefix tag. Default: MLS")
    ap.add_argument("--failed-step",
                    help="Compose a standard failure alert for this step.")
    ap.add_argument("--error-message")
    ap.add_argument("--details")
    ap.add_argument("--status-path")
    ap.add_argument("--api-key")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be sent; do not call Resend.")
    a = ap.parse_args()

    if a.failed_step:
        subject = a.subject or ("MLS export FAILED at " + a.failed_step)
        text = build_failure_body(a.failed_step, a.error_message, a.details,
                                  a.status_path)
        tag = a.tag or "MLS"
    else:
        if not a.subject:
            print("ERROR: --subject required (or use --failed-step)",
                  file=sys.stderr)
            return 2
        subject = a.subject
        if a.text_file:
            text = Path(a.text_file).read_text(encoding="utf-8", errors="replace")
        elif a.text:
            text = a.text
        else:
            text = sys.stdin.read()
        tag = a.tag

    html = None
    if a.html_file:
        try:
            html = Path(a.html_file).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print("WARN: could not read --html-file: " + str(e), file=sys.stderr)

    if a.dry_run:
        print("[dry-run] to=" + str(a.to or [DEFAULT_TO]))
        print("[dry-run] subject=[" + str(tag) + "] " + subject)
        print("[dry-run] body:")
        print(text)
        return 0

    res = send_alert(subject, text, to=a.to, html=html, api_key=a.api_key, tag=tag)
    print(json.dumps(res))
    # Exit 0 on success, 1 on send failure, so callers can branch. The caller
    # should log a failed alert but must NOT abort its own error handling.
    return 0 if res.get("sent") else 1


if __name__ == "__main__":
    sys.exit(main())
