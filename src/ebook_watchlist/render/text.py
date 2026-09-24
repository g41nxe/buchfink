"""Plain-text Digest — what lands in stdout and therefore in cron logs."""

from __future__ import annotations

from ..digest import Digest, DigestEntry


def _lines_for(entry: DigestEntry) -> list[str]:
    parts = [entry.title]
    if entry.author:
        parts.append(f"— {entry.author}")
    if entry.detail:
        parts.append(f"[{entry.detail}]")
    if entry.flags:
        parts.extend(f"**{flag}**" for flag in entry.flags)
    lines = ["  - " + " ".join(parts)]
    if entry.judgement:
        lines.append(f"    {entry.judgement}")
    if entry.pitch:
        lines.append(f"    {entry.pitch}")
    if entry.url:
        lines.append(f"    {entry.url}")
    return lines


def render_text(digest: Digest) -> str:
    lines = [
        f"{digest.profile_name} — {digest.headline}",
        "=" * 60,
    ]
    if digest.gate is not None and digest.gate.is_worth_saying:
        lines.append(digest.gate.text)
    for section in digest.sections:
        lines.append("")
        lines.append(section.title)
        for entry in section.entries:
            lines.extend(_lines_for(entry))
    lines.append("")
    return "\n".join(lines)
