"""PRD preprocessing — prepends explicit line markers to the raw PRD text.

Why: LLMs have no intrinsic concept of physical line numbers; asking a model
to emit `source_line` from plain text produces hallucinated integers. By
prefixing each line with a literal `[NNN] ` marker, the line number becomes
a token the model can copy verbatim. The intake agent is prompted to read
the marker directly instead of counting.

This is the single source of truth for line-number formatting. Both the
intake agent (producing `PRDClaim.source_line`) and the critic agents
(citing line numbers in `evidence`) assume input has been run through
`number_lines` before being placed into their prompts.
"""

from __future__ import annotations

LINE_MARKER_WIDTH = 3  # supports PRDs up to 999 lines; extend if needed.


def number_lines(prd_text: str) -> str:
    """Return the PRD text with each line prefixed by a zero-padded `[NNN] ` marker.

    Line numbers are 1-indexed. Blank lines are kept and numbered so that
    downstream references stay stable when users paste in or out of code
    blocks. Trailing newline, if present, is preserved.
    """
    if not prd_text:
        return ""
    lines = prd_text.splitlines()
    width = max(LINE_MARKER_WIDTH, len(str(len(lines))))
    numbered = [f"[{str(i + 1).zfill(width)}] {line}" for i, line in enumerate(lines)]
    trailing_nl = "\n" if prd_text.endswith("\n") else ""
    return "\n".join(numbered) + trailing_nl


def parse_line_marker(quoted: str) -> int | None:
    """Extract the integer line number from a `[NNN]`-prefixed line.

    Returns None if no marker is present. Used by the eval harness to align
    critic-cited lines back to the original PRD.
    """
    import re

    m = re.match(r"\s*\[(\d+)\]", quoted)
    return int(m.group(1)) if m else None
