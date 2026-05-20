import base64
import sys
from pathlib import Path
from urllib.parse import urlparse

from config import Settings

# ── Icon path resolution ───────────────────────────────────────────────────────
# Icons live in static/icons/{name}.svg, bundled by PyInstaller via
# the 'static' data entry in email_agent.spec.

def _icons_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "static" / "icons"   # type: ignore[attr-defined]
    return Path(__file__).parent.parent / "static" / "icons"


def _load_icon_b64(name: str) -> tuple[str, str] | None:
    """
    Return (mime_type, base64_data) for the given platform icon, or None.
    Prefers PNG (email-safe) over SVG.
    """
    key = name.lower().strip()
    for ext, mime in ((".png", "image/png"), (".svg", "image/svg+xml")):
        path = _icons_dir() / f"{key}{ext}"
        if path.exists():
            return mime, base64.b64encode(path.read_bytes()).decode()
    return None


# ── Platform → domain mapping (Google favicon fallback) ───────────────────────
# Used only when the local SVG file is missing.

_PLATFORM_DOMAINS: dict[str, str | None] = {
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
    "website":   None,
    "blog":      None,
    "portfolio": None,
}

_GOOGLE_FAVICON = "https://www.google.com/s2/favicons?domain={domain}&sz=64"


def _fallback_img_url(label: str, url: str) -> str:
    domain = _PLATFORM_DOMAINS.get(label.lower().strip())
    if domain is None:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or url
        except Exception:
            domain = url
    return _GOOGLE_FAVICON.format(domain=domain)


# ── Icon HTML builder ──────────────────────────────────────────────────────────

def _icon_html(label: str, url: str) -> str:
    """
    Build an email-safe <img> icon link.
    Priority: local bundled SVG (base64 data URI) → Google favicon URL fallback.
    """
    result = _load_icon_b64(label)
    if result:
        mime, b64 = result
        src = f"data:{mime};base64,{b64}"
    else:
        src = _fallback_img_url(label, url)

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
