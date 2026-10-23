"""Server-side email notifications (SMTP).

Reads all provider config from environment variables - no credentials are
ever hardcoded. Email delivery is best-effort: a notification failure must
never fail an otherwise-successful report operation. Local development can
set EMAIL_ENABLED=false to disable real sends entirely.
"""
from __future__ import annotations

import smtplib
import threading
from email.message import EmailMessage

from ..config import get_settings


def _recipient_valid(addr: str | None) -> bool:
    return bool(addr) and "@" in addr and "." in addr.split("@")[-1]


def _send_sync(to: str, subject: str, body: str) -> bool:
    s = get_settings()
    if not s.email_enabled or not _recipient_valid(to):
        return False
    msg = EmailMessage()
    msg["From"] = s.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.email_host, s.email_port, timeout=20) as server:
            if s.email_use_tls:
                server.starttls()
            if s.email_username:
                server.login(s.email_username, s.email_password)
            server.send_message(msg)
        return True
    except Exception:
        # Swallow provider failures; logged by caller via notification status.
        return False


def send_email_async(to: str, subject: str, body: str,
                     on_result=None) -> None:
    """Fire-and-forget send on a daemon thread so requests aren't blocked."""
    def _worker():
        ok = _send_sync(to, subject, body)
        if on_result:
            try:
                on_result(ok)
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True).start()


# ---- Templated notifications for the report workflow ----

_TEMPLATES = {
    "submitted": "Your report {report_id} was submitted",
    "verified": "Report {report_id} has been verified",
    "rejected": "Report {report_id} was rejected",
    "assigned": "Repair team assigned to report {report_id}",
    "in_progress": "Repair started for report {report_id}",
    "resolved": "Report {report_id} has been resolved",
    "reopened": "Report {report_id} was reopened",
    "duplicate": "Report {report_id} was marked as duplicate",
}


def _link(report_id: str) -> str:
    s = get_settings()
    return f"{s.app_base_url}/#/reports/{report_id}" if s.app_base_url else ""


def notify_status_change(status: str, report_id: str, to_email: str | None,
                         location: str | None, on_result=None) -> None:
    subject = _TEMPLATES.get(status, f"Report {report_id} updated").format(report_id=report_id)
    lines = [
        f"Report ID: {report_id}",
        f"Status: {status}",
    ]
    if location:
        lines.append(f"Location: {location}")
    link = _link(report_id)
    if link:
        lines.append(f"Track your report: {link}")
    lines.append("")
    lines.append("This is an automated message from the Pothole Detection System.")
    body = "\n".join(lines)

    if to_email:
        send_email_async(to_email, subject, body, on_result=on_result)
    # Also alert authorities on new submissions.
    s = get_settings()
    if status == "submitted" and _recipient_valid(s.authority_alert_email):
        send_email_async(s.authority_alert_email, f"[New report] {subject}", body)
