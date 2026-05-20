from urllib.parse import urlparse

from config import Settings

# ── Icon delivery ──────────────────────────────────────────────────────────────
#
# Gmail (and most web clients) block ALL data: URIs. jsDelivr requires the
# GitHub repo to be public. The only guaranteed-working method for any email
# client is externally hosted HTTPS PNG images.
#
# Google's favicon service (s2/favicons) is served from Google's own CDN.
# Gmail auto-loads images from Google's CDN. Returns actual brand favicons as
# PNG: LinkedIn's blue "in" square, GitHub's Octocat, WhatsApp's green phone,
# etc. — exactly what users expect to see.

_GOOGLE_FAVICON = "https://www.google.com/s2/favicons?domain={domain}&sz=64"

# Known platform → canonical domain
_PLATFORM_DOMAINS: dict[str, str] = {
    "linkedin":  "linkedin.com",
    "whatsapp":  "whatsapp.com",
    "instagram": "instagram.com",
    "twitter":   "twitter.com",
    "x":         "x.com",
    "facebook":  "facebook.com",
    "github":    "github.com",
    "youtube":   "youtube.com",
    "tiktok":    "tiktok.com",
    "telegram":  "telegram.org",
    "discord":   "discord.com",
    "snapchat":  "snapchat.com",
    "pinterest": "pinterest.com",
    "reddit":    "reddit.com",
}


def _icon_src(label: str, link_url: str) -> str:
    """
    Return a Google favicon HTTPS URL for the platform icon.
    Known platforms use the canonical domain; others extract domain from the URL.
    """
    key = label.lower().strip()
    domain = _PLATFORM_DOMAINS.get(key)

    if domain is None:
        try:
            parsed = urlparse(link_url)
            domain = parsed.netloc or link_url
        except Exception:
            domain = link_url

    return _GOOGLE_FAVICON.format(domain=domain)


def _icon_html(label: str, url: str) -> str:
    """Build an email-safe icon link using Google's favicon CDN."""
    src = _icon_src(label, url)
    return (
        f'<a href="{url}" title="{label}" target="_blank" rel="noopener noreferrer" '
        f'style="display:inline-block;margin:0 6px 4px 0;text-decoration:none;">'
        f'<img src="{src}" width="28" height="28" alt="{label}" '
        f'style="display:block;border-radius:5px;border:0;" />'
        f'</a>'
    )


# ── SignatureBuilder ───────────────────────────────────────────────────────────

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
            icons = "".join(
                _icon_html(link["label"], link["url"])
                for link in s.social_links
            )
            lines.append(icons)

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
