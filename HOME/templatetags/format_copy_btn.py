import re
from django import template

register = template.Library()


@register.filter
def filter_copy_btn_text(value):
    if not value:
        return ""

    # Walk lines, skip blanks and image directives, take the first real line
    needed = ""
    for line in value.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^img[lr]\s+", stripped):
            continue
        needed = stripped
        break

    if not needed:
        return ""

    # Strip leading heading markers: "# ", "## ", etc.
    needed = re.sub(r"^#+\s*", "", needed)

    # Strip bullet markers: "* ", "- "
    needed = re.sub(r"^[*\-]\s+", "", needed)

    # Strip numbered list markers: "1. ", "2) "
    needed = re.sub(r"^\d+[.)]\s+", "", needed)

    # Strip bold/italic: **x**, __x__, *x*, _x_, ***x***
    needed = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", needed)
    needed = re.sub(r"\*\*(.+?)\*\*", r"\1", needed)
    needed = re.sub(r"__(.+?)__", r"\1", needed)
    needed = re.sub(r"\*(.+?)\*", r"\1", needed)
    needed = re.sub(r"_(.+?)_", r"\1", needed)

    # Strip inline code and strikethrough
    needed = re.sub(r"`(.+?)`", r"\1", needed)
    needed = re.sub(r"~~(.+?)~~", r"\1", needed)

    # Strip links [label](url) -> label, and images ![alt](url) -> alt
    needed = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", needed)
    needed = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", needed)

    # Strip any leftover HTML tags
    needed = re.sub(r"<[^>]+>", "", needed)

    # Collapse extra whitespace
    needed = re.sub(r"[ \t]+", " ", needed)

    return "** JUST IN **\n\n" + needed.strip()
