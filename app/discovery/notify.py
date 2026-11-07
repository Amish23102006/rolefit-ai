"""Email notifications for new alerts (SMTP over STARTTLS). Credentials come from the environment only.
Emails contain titles, companies, locations, links and scores - never resume or evidence text."""
import smtplib
import ssl
from email.message import EmailMessage


class EmailNotifier:
    def __init__(self, host: str, port: int, user: str, password: str, sender: str, smtp_factory=smtplib.SMTP):
        self.host, self.port, self.user, self._password, self.sender = host, port, user, password, sender or user
        self._factory = smtp_factory

    def __repr__(self):
        return f"EmailNotifier(host={self.host!r}, user={self.user!r})"

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.user and self._password and self.sender)

    @staticmethod
    def compose(to: str, alerts: list) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = f"RoleFit AI: {len(alerts)} new job alert{'s' if len(alerts) != 1 else ''}"
        msg["To"] = to
        lines = ["New openings that match your RoleFit profile:", ""]
        for a in alerts[:25]:
            score = f" | readiness {a['readiness_score']:.0f}/100" if a.get("readiness_score") is not None else " | lead (open the link to check)"
            lines += [f"- {a['title']} - {a['company']}" + (f" ({a['location']})" if a.get("location") else "") + score,
                      f"  {a['url']}" if a.get("url") else "  (no link)", ""]
        if len(alerts) > 25:
            lines.append(f"...and {len(alerts) - 25} more in RoleFit (Job alerts page).")
        lines += ["", "Readiness is RoleFit's heuristic rubric, not an employer ATS score and not a guarantee of selection.",
                  "Always confirm details on the official posting. Turn these emails off on the RoleFit Profile page."]
        msg.set_content("\n".join(lines))
        return msg

    def send(self, to: str, alerts: list) -> None:
        msg = self.compose(to, alerts)
        msg["From"] = self.sender
        with self._factory(self.host, self.port, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(self.user, self._password)
            s.send_message(msg)
