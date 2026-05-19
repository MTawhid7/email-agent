from config import Settings


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

        social: list[str] = []
        if s.signature_linkedin:
            social.append(f'<a href="{s.signature_linkedin}">LinkedIn</a>')
        if s.signature_github:
            social.append(f'<a href="{s.signature_github}">GitHub</a>')
        if s.signature_website:
            social.append(f'<a href="{s.signature_website}">Website</a>')
        if social:
            lines.append(" · ".join(social))

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

        social: list[str] = []
        if s.signature_linkedin:
            social.append(f"LinkedIn: {s.signature_linkedin}")
        if s.signature_github:
            social.append(f"GitHub: {s.signature_github}")
        if s.signature_website:
            social.append(f"Website: {s.signature_website}")
        if social:
            lines.append(" | ".join(social))

        return "\n".join(lines)
