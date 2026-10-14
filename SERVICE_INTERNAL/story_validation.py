"""Deterministic, local validation for the Add News form.

No external AI/API is used. Everything here is plain text processing so the
rules can be enforced on the server (where they cannot be bypassed by sending
a hand built request) and mirrored in the browser for instant feedback.

The block detection deliberately mirrors BLOG.views.parse_story_content so the
validator "sees" the same headings / lists / paragraphs that readers will get.
The content is only INSPECTED, it is never modified or returned changed, so the
author's markdown formatting is stored exactly as typed.

Two kinds of findings are produced:

    BLOCK  - the story cannot be published until the author fixes it.
    WARN   - advisory. The author is told why and is asked whether to post
             anyway or go back and edit (see AddNewsView, `confirm_warnings`).
"""

import re
from difflib import SequenceMatcher

#   SIMILARITY THRESHOLDS (0.0 - 1.0)
SIMILARITY_BLOCK = 0.90
SIMILARITY_WARN = 0.75

#   Editorial quality floor (mirrors DOCS/NEWS_CONTENT_CONVENTION.MD). A story
#   under HARD_MIN_BODY_WORDS is refused outright; between the floor and
#   MIN_BODY_WORDS it can still publish, but only after the author reads the
#   reason and confirms. This keeps the corpus from filling up with near-empty
#   posts that hurt search visibility and ad eligibility.
HARD_MIN_BODY_WORDS = 100
MIN_BODY_WORDS = 300
#   A story built on another report, post or page must say so: a line that starts
#   with "Source" (e.g. "Source: https://..."), or a link anywhere in the body.
SOURCE_RE = re.compile(r"(?im)^\s*source\b")
URL_RE = re.compile(r"https?://\S+")

IMG_RE = re.compile(r"^(imgl|imgr|imgc)\s+(\S+)(?:\s+(.*))?$")
VID_RE = re.compile(r"^(vidl|vidr|vidc)\s+(\S+)(?:\s+(.*))?$")
FILE_RE = re.compile(r"^filel\s+(\S+)(?:\s+(.*))?$")
HEADING_RE = re.compile(r"^(#+)\s*(.*)$")
BULLET_RE = re.compile(r"^\*\s+")
ORDERED_RE = re.compile(r"^\d+\.\s+")
STARTER_RE = re.compile(r"^(#+\s+|\*\s+|\d+\.\s+|imgl\s+|imgr\s+|imgc\s+|vidl\s+|vidr\s+|vidc\s+|filel\s+)")

#   a line made only of one repeated decorative symbol, 4 or more times
SEPARATOR_RE = re.compile(r"^([^\w\s])\1{3,}$")
#   a line made only of symbols / spaces (no letters or digits at all), 4+ chars
SYMBOL_ONLY_RE = re.compile(r"^[^\w]{4,}$", re.UNICODE)
#   a run of the same symbol inside text, e.g. "wow!!!!!!!!!!" or "-----"
LONG_SYMBOL_RUN_RE = re.compile(r"([^\w\s])\1{7,}")


def _block(code, message, rule=None):
    return {"code": code, "level": "block", "message": message, "rule": rule or code}


def _warn(code, message, rule=None):
    return {"code": code, "level": "warn", "message": message, "rule": rule or code}


# --------------------------------------------------------------------------
#   TEXT HELPERS
# --------------------------------------------------------------------------
def strip_inline_markup(text):
    """Plain readable text from one line of this project's markdown flavour."""
    text = text or ""
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def normalise_for_compare(text):
    """Lower case, markup free, punctuation free, single spaced."""
    text = strip_inline_markup(text).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE).replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def similarity(a, b):
    """0.0 - 1.0 similarity between two pieces of text.

    The higher of a character level and a word level comparison, so both a
    copied headline and a lightly reworded / reordered one are caught."""
    na, nb = normalise_for_compare(a), normalise_for_compare(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    char_ratio = SequenceMatcher(None, na, nb, autojunk=False).ratio()
    wa, wb = na.split(), nb.split()
    word_ratio = SequenceMatcher(None, wa, wb, autojunk=False).ratio()
    #   same words, different order
    sa, sb = set(wa), set(wb)
    set_ratio = (2.0 * len(sa & sb) / (len(sa) + len(sb))) if (sa or sb) else 0.0
    #   set overlap only counts when the word counts are close, otherwise a
    #   long paragraph that merely contains the headline words would score high
    if max(len(wa), len(wb)) > 1.35 * min(len(wa), len(wb)):
        set_ratio = 0.0
    return max(char_ratio, word_ratio, set_ratio)


def _first_sentence(text):
    match = re.match(r"^(.+?[.!?])(\s|$)", text.strip())
    return match.group(1) if match else text.strip()


def _leading_words(text, count):
    return " ".join(text.split()[:count])


def opening_similarity(heading, paragraph):
    """How closely a paragraph's OPENING reproduces the heading.

    Compared against the whole paragraph, its first sentence, and the same
    number of leading words as the headline, so a paragraph that starts with
    the headline and then carries on is still caught."""
    heading_words = len(normalise_for_compare(heading).split())
    candidates = [
        paragraph[:500],
        _first_sentence(paragraph),
        _leading_words(strip_inline_markup(paragraph), heading_words),
        _leading_words(strip_inline_markup(paragraph), heading_words + 2),
    ]
    return max(similarity(heading, c) for c in candidates if c and c.strip())


# --------------------------------------------------------------------------
#   BLOCK SPLITTING (mirrors BLOG.views.parse_story_content)
# --------------------------------------------------------------------------
def split_blocks(content):
    """Return a list of dicts: {type, text, raw, level}.

    type is one of: heading, bullet, ordered, image, video, file, paragraph.
    Empty headings are kept (text == "") so they can be reported."""
    lines = [line.rstrip() for line in (content or "").replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")]
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if IMG_RE.match(line):
            blocks.append({"type": "image", "text": "", "raw": line, "level": 0})
            i += 1
            continue
        if VID_RE.match(line):
            blocks.append({"type": "video", "text": "", "raw": line, "level": 0})
            i += 1
            continue
        if FILE_RE.match(line):
            blocks.append({"type": "file", "text": "", "raw": line, "level": 0})
            i += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            blocks.append({"type": "heading", "text": heading.group(2).strip(), "raw": line, "level": len(heading.group(1))})
            i += 1
            continue

        if BULLET_RE.match(line):
            while i < len(lines):
                current = lines[i].strip()
                if not current or not BULLET_RE.match(current):
                    break
                blocks.append({"type": "bullet", "text": current[2:].strip(), "raw": current, "level": 0})
                i += 1
            continue

        if ORDERED_RE.match(line):
            while i < len(lines):
                current = lines[i].strip()
                if not current or not ORDERED_RE.match(current):
                    break
                blocks.append({"type": "ordered", "text": ORDERED_RE.sub("", current, count=1).strip(), "raw": current, "level": 0})
                i += 1
            continue

        paragraph_lines = []
        while i < len(lines):
            current = lines[i].strip()
            if not current:
                break
            if STARTER_RE.match(current):
                break
            paragraph_lines.append(current)
            i += 1
            if i < len(lines) and not lines[i].strip():
                break
        if paragraph_lines:
            blocks.append({"type": "paragraph", "text": " ".join(paragraph_lines).strip(), "raw": " ".join(paragraph_lines), "level": 0})
        else:
            #   safety: never loop forever on an unexpected line
            i += 1
    return blocks


def _word_count(text):
    return len(re.findall(r"\w+", strip_inline_markup(text), flags=re.UNICODE))


def _letter_count(text):
    return len(re.findall(r"[^\W\d_]", strip_inline_markup(text), flags=re.UNICODE))


def _is_meaningless(text):
    """True for filler such as 'aaaaaaa', 'asdf asdf asdf', 'lorem ipsum' or
    'test test test'. Deterministic, conservative checks only."""
    norm = normalise_for_compare(text)
    if not norm:
        return True
    words = norm.split()
    if re.search(r"(.)\1{5,}", norm.replace(" ", "")) and len(set(words)) <= 2:
        return True
    if len(words) >= 3 and len(set(words)) == 1:
        return True
    if len(words) >= 6 and len(set(words)) <= max(1, len(words) // 6):
        return True
    if norm.startswith("lorem ipsum"):
        return True
    return False


# --------------------------------------------------------------------------
#   MAIN ENTRY POINT
# --------------------------------------------------------------------------
def validate_story(heading, content):
    """Inspect a story and return {"errors": [...], "warnings": [...]}.

    Every item is {"code", "level", "message", "rule"} where `message` tells the
    author exactly what to correct. `content` is never altered."""
    errors, warnings = [], []
    heading = (heading or "").strip()
    content = content or ""
    blocks = split_blocks(content)

    def add(item):
        (errors if item["level"] == "block" else warnings).append(item)

    #   RULE 5: EMPTY / SYMBOL-ONLY HEADINGS ("#", "##", "### ***")
    for block in blocks:
        if block["type"] != "heading":
            continue
        text = block["text"]
        if not text:
            add(_block(
                "empty_heading",
                f'Your article contains an empty heading ("{block["raw"]}"). Type the section title after the # symbols, or delete that line.',
            ))
            break
        if not re.search(r"\w", strip_inline_markup(text), flags=re.UNICODE):
            add(_block(
                "symbol_heading",
                f'Your article contains a heading made only of symbols ("{block["raw"][:40]}"). Give that heading real words, or delete the line.',
            ))
            break

    #   RULE 6: DECORATIVE SEPARATORS / REPEATED SYMBOLS
    separator_lines = []
    for raw_line in content.replace("\r\n", "\n").split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if STARTER_RE.match(stripped) and not SEPARATOR_RE.match(stripped):
            #   a real "* item" / "# title" line is judged by the heading rules
            continue
        if SEPARATOR_RE.match(stripped) or (SYMBOL_ONLY_RE.match(stripped) and not HEADING_RE.match(stripped)):
            separator_lines.append(stripped)
    if separator_lines:
        sample = separator_lines[0][:30]
        add(_block(
            "decorative_separator",
            f'Your article contains a decorative separator line ("{sample}"). Remove it and use blank lines between paragraphs or a # section heading instead.',
        ))
    elif LONG_SYMBOL_RUN_RE.search(content):
        run = LONG_SYMBOL_RUN_RE.search(content).group(0)[:30]
        add(_block(
            "repeated_symbols",
            f'Your article contains a long run of repeated symbols ("{run}"). Remove the extra symbols; they add nothing to the story. Only hurt your story outreach and you might be shadow banned.',
        ))

    #   RULE 3: BODY MUST NOT OPEN WITH A HEADING THAT REPEATS THE MAIN HEADING
    first_real = next((b for b in blocks if b["type"] not in ("image", "video", "file")), None)
    if first_real is not None and first_real["type"] == "heading" and first_real["text"]:
        score = similarity(heading, first_real["text"])
        if score >= SIMILARITY_BLOCK:
            add(_block(
                "body_starts_with_heading_copy",
                f'Your article body begins with the heading "{first_real["raw"][:80]}", which is the same as your main headline. '
                "The headline is already shown at the top of the page. Delete that line and start with your opening paragraph.",
            ))
        elif score >= SIMILARITY_WARN:
            add(_warn(
                "body_starts_with_heading_similar",
                f'Your article body begins with a heading ("{first_real["raw"][:80]}") that is very close to your main headline. '
                "Readers will see almost the same text twice. Consider starting with a normal opening paragraph.",
            ))
        else:
            add(_warn(
                "body_starts_with_heading",
                "Your article begins with a heading. It is better to open with a plain paragraph that introduces the story, "
                "and use headings only for later sections.",
            ))

    #   RULE 2 / 10: MEANINGFUL BODY (not just a heading, fragment, or filler)
    body_blocks = [b for b in blocks if b["type"] in ("paragraph", "bullet", "ordered")]
    body_text = " ".join(b["text"] for b in body_blocks)
    heading_norm = normalise_for_compare(heading)
    body_norm = normalise_for_compare(body_text)
    words = _word_count(body_text)
    letters = _letter_count(body_text)

    if not body_blocks:
        add(_block(
            "no_body_text",
            "Your article has no body text. Headings, images, videos and files alone are not a story. "
            "Write the report itself in normal paragraphs below the headline.",
        ))
    elif body_norm and body_norm == heading_norm:
        add(_block(
            "body_is_heading_only",
            "Your article body only repeats the headline which is not allowed.",
        ))
    elif _is_meaningless(body_text):
        add(_block(
            "meaningless_text",
            "Your article body looks like filler text (repeated words or characters). Replace it with a real report of the story.",
        ))
    elif words < HARD_MIN_BODY_WORDS:
        add(_block(
            "body_too_short",
            f"Your article body is only {words} words. A story needs at least {HARD_MIN_BODY_WORDS} words of real "
            "reporting before it can be published. Add the facts, names, dates and details readers need.",
        ))
    elif words < MIN_BODY_WORDS:
        add(_warn(
            "body_below_target",
            f"Your article body is {words} words. Our standard is at least {MIN_BODY_WORDS} words so the story is complete "
            "and useful; short stories reach fewer readers and weaken our eligibility for ad partners. "
            "Expand it with real detail, or confirm that you want to publish it as it is.",
        ))

    #   RULE 11: NAME THE SOURCE. A story built on another report, post or page
    #   must say where the facts came from, so readers (and reviewers) can verify
    #   it. A link anywhere in the body, or a "Source:" line, satisfies this.
    if body_blocks and not (URL_RE.search(content) or SOURCE_RE.search(content)):
        add(_warn(
            "missing_source",
            "Your article does not name a source. Add a 'Source:' line or a link to where the facts come from, "
            "so readers can trust the story and verify it.",
        ))

    #   RULE 1: FIRST PARAGRAPH vs HEADING (>= 90% blocks)
    first_paragraph = None
    for block in blocks:
        if block["type"] in ("image", "video", "file", "heading"):
            continue
        first_paragraph = block
        break

    if first_paragraph is not None and heading:
        score = opening_similarity(heading, first_paragraph["text"])
        percent = int(round(score * 100))
        if score >= SIMILARITY_BLOCK:
            add(_block(
                "first_paragraph_matches_heading",
                f"Your first paragraph is too similar to your headline ({percent}% match, the limit is below 90%). "
                "Rewrite the opening paragraph so that it introduces the story instead of repeating the headline.",
                rule="first_paragraph_similarity",
            ))
        elif score >= SIMILARITY_WARN:
            add(_warn(
                "first_paragraph_close_to_heading",
                f"Your first paragraph is quite similar to your headline ({percent}% match). "
                "It is allowed, but search engines can treat repeated text as low value. Consider adding new detail in the opening paragraph.",
                rule="first_paragraph_similarity",
            ))
        if first_paragraph["type"] in ("bullet", "ordered"):
            add(_warn(
                "first_paragraph_is_list",
                "Your article opens with a list instead of a normal paragraph. "
                "It is better to introduce the story in a plain paragraph first.",
            ))
        elif re.match(r"^\s*(\*\*|__)", first_paragraph["raw"] or ""):
            add(_warn(
                "first_paragraph_formatted",
                "Your first paragraph starts with bold or italic formatting. The guide recommends keeping the opening paragraph plain text.",
            ))

    return {"errors": errors, "warnings": warnings}


def first_error_message(result):
    """Single sentence summary for the `detail` field of an error response."""
    errors = result.get("errors") or []
    if not errors:
        return ""
    if len(errors) == 1:
        return errors[0]["message"]
    return f"Your article cannot be submitted yet. {len(errors)} problems need fixing: " + " ".join(
        f"({n}) {e['message']}" for n, e in enumerate(errors, 1)
    )
