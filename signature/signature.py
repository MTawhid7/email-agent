from config import Settings

# ── Platform badge colours ─────────────────────────────────────────────────────
# Inline SVG is stripped by all major email clients (Gmail, Outlook, Apple Mail).
# Styled text badges are the universally supported email-safe alternative.

_BADGE_COLOURS: dict[str, tuple[str, str]] = {
    # label (lowercase) → (background, text colour)
    "linkedin":  ("#0A66C2", "#ffffff"),
    "whatsapp":  ("#25D366", "#ffffff"),
    "instagram": ("#E4405F", "#ffffff"),
    "twitter":   ("#000000", "#ffffff"),
    "x":         ("#000000", "#ffffff"),
    "facebook":  ("#1877F2", "#ffffff"),
    "github":    ("#24292F", "#ffffff"),
    "youtube":   ("#FF0000", "#ffffff"),
    "tiktok":    ("#010101", "#ffffff"),
    "website":   ("#6B7280", "#ffffff"),
    "portfolio": ("#6B7280", "#ffffff"),
    "blog":      ("#6B7280", "#ffffff"),
}

_DEFAULT_BADGE = ("#4B5563", "#ffffff")   # neutral dark for unknown platforms


def _badge_html(label: str, url: str) -> str:
    """
    Build an email-safe styled link badge.
    Uses only inline CSS properties supported by Outlook, Gmail, and Apple Mail.
    """
    bg, fg = _BADGE_COLOURS.get(label.lower().strip(), _DEFAULT_BADGE)
    return (
        f'<a href="{url}" title="{label}" target="_blank" rel="noopener noreferrer" '
        f'style="display:inline-block;padding:3px 10px;margin:0 4px 4px 0;'
        f'background-color:{bg};color:{fg};text-decoration:none;'
        f'font-family:Arial,Helvetica,sans-serif;font-size:11px;font-weight:bold;'
        f'border-radius:3px;mso-padding-alt:3px 10px;">'   # mso- prefix for Outlook
        f'{label}'
        f'</a>'
    )


class SignatureBuilder:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def build_html(self) -> str:
        s = self._s
        lines: list[str] = []

        name_line = f"<strong>{s.signature_name}</strong>"
        if s.signature_title and s.signature_company:
            name_line += f" | {s.signature_title}, {s.signature_company}"
        elif s.signature_title:
            name_line += f" | {s.signature_title}"
        elif s.signature_company:
            name_line += f" | {s.signature_company}"
        lines.append(name_line)

        if s.signature_phone:
            lines.append(s.signature_phone)

        if s.social_links:
            badges = "".join(
                _badge_html(link["label"], link["url"])
                for link in s.social_links
            )
            lines.append(badges)

        inner = "<br>\n".join(lines)
        return f"\n<br><hr>\n<p>\n{inner}\n</p>"

    def build_plain_text(self) -> str:
        s = self._s
        lines: list[str] = ["--"]

        name_line = s.signature_name
        if s.signature_title and s.signature_company:
            name_line += f" | {s.signature_title}, {s.signature_company}"
        elif s.signature_title:
            name_line += f" | {s.signature_title}"
        elif s.signature_company:
            name_line += f" | {s.signature_company}"
        lines.append(name_line)

        if s.signature_phone:
            lines.append(s.signature_phone)

        if s.social_links:
            lines.append(" | ".join(
                f"{link['label']}: {link['url']}" for link in s.social_links
            ))

        return "\n".join(lines)
