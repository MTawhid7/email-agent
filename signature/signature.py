from urllib.parse import urlparse

from config import Settings

# ── Icon delivery ──────────────────────────────────────────────────────────────
#
# Gmail (and most web clients) block ALL data: URIs and inline SVG in emails.
# The only universally supported method is externally hosted HTTPS PNG images.
#
# We serve our branded icons from jsDelivr CDN backed by this public GitHub repo.
# jsDelivr is purpose-built for serving static assets from GitHub repos with
# global CDN caching — the exact approach used by Wisestamp, Exclaimer, etc.
#
# URL pattern: https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/path/to/file

_JSDELIVR_BASE = "https://cdn.jsdelivr.net/gh/MTawhid7/email-agent@main/static/icons"

# Platform slugs that have a bundled PNG in static/icons/
_BUNDLED_ICONS = frozenset({
    "linkedin", "whatsapp", "instagram", "twitter", "x",
    "facebook", "github", "youtube", "tiktok", "telegram", "discord",
})

# Google favicon service — fallback for unknown/custom platform labels
_GOOGLE_FAVICON = "https://www.google.com/s2/favicons?domain={domain}&sz=64"

# Known platform → canonical domain (for Google favicon fallback)
_PLATFORM_DOMAINS: dict[str, str | None] = {
    "snapchat":  "snapchat.com",
    "pinterest": "pinterest.com",
    "reddit":    "reddit.com",
    "website":   None,
    "blog":      None,
    "portfolio": None,
}


def _icon_src(label: str, link_url: str) -> str:
    """
    Return the best HTTPS URL for a social platform icon.
    1. Bundled PNG via jsDelivr CDN (known platforms)
    2. Google favicon service (unknown labels — uses the link's own domain)
    """
    key = label.lower().strip()

    if key in _BUNDLED_ICONS:
        return f"{_JSDELIVR_BASE}/{key}.png"

    # Try Google favicon with known domain mapping first
    domain = _PLATFORM_DOMAINS.get(key)
    if domain is None:
        # Extract domain from the supplied URL
        try:
            parsed = urlparse(link_url)
            domain = parsed.netloc or link_url
        except Exception:
            domain = link_url

    return _GOOGLE_FAVICON.format(domain=domain)


def _icon_html(label: str, url: str) -> str:
    """Build an email-safe icon link using an externally hosted HTTPS PNG."""
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
