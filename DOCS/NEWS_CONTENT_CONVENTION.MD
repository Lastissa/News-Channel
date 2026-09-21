# NEWS CONTENT CONVENTION

This document explains how news content should be written so it remains natural for human editors and still reliable for automated parsing.

## CORE PRINCIPLE

Writers should write like normal article content. They do not need to think like developers. The parser should detect structure from simple patterns instead of requiring complex markup.

To keep the system clear and safe, each job has one official format only.

---

## OFFICIAL FORMATS

### 1) LINKS

Any word or token that begins with http:// or https:// should be treated as a hyperlink.

Example:

https://myschoolgist.com/news/unilag-post-utme-form/

Rule:
- The parser should convert the whole URL token into an anchor tag.
- No second format such as [text](url) should be used for the same job.

### 2) ORDERED LISTS

Any line that begins with a number followed by a dot should be treated as an ordered list item.

Example:

1. First point
2. Second point
3. Third point

Rule:
- Use only "1." format.
- Do not use "1)" or "-" for ordered lists.
- The parser should treat consecutive lines beginning with this pattern as one ordered list block.

### 3) UNORDERED LISTS

Any line that begins with * should be treated as an unordered list item.

Example:

* First bullet
* Second bullet
* Third bullet

Rule:
- Use only "*" for unordered bullets.
- Do not use "-" or "•" as an alternative.
- The parser should treat consecutive "*" lines as one unordered list block.

### 4) HEADINGS

Any line that starts with # should be treated as a heading.

Example:

# This is a section heading
## This is a subheading
### This is a smaller heading

Rule:
- One hash means heading level 2.
- Two hashes mean heading level 3.
- Three hashes mean heading level 4.
- The page title itself is the main h1 and should not be written as a content heading marker.
- The parser should only treat lines that begin with # as headings.
- No second syntax should be used for headings.

### 5) ITALIC TEXT

Italic text should use double underscore wrapping.

Example:

__important note__

Rule:
- Use __text__ only.
- Do not use separate markers for the same job.

### 6) BOLD TEXT

Bold text should use double asterisk wrapping.

Example:

**important update**

Rule:
- Use **text** only.
- Do not create alternate bold syntax for the same task.

---

## WRITING STYLE FOR AUTHORS

Writers should use plain article writing. They should not be forced to think in markup.

Recommended guidance for writers:

- Write in normal paragraphs.
- Leave a blank line between paragraphs.
- Start a new line with * for bullet points.
- Start a new line with 1. for numbered points.
- Start a new line with # for section titles.
- Paste links normally as full URLs.
- Use bold or italic only when needed, using the allowed markers.

---

## PARSING ORDER

To avoid conflict, the parser should process content in this order:

1. Detect heading blocks first
2. Detect unordered and ordered list blocks next
3. Detect URL links in text
4. Detect bold and italic inline markup
5. Treat remaining text as normal paragraphs

This order prevents a line from being misread as ordinary copy when it is actually a heading, list, or link.

---

## ONE FORMAT PER JOB

This is the most important rule:

- Heading: # only
- Unordered list: * only
- Ordered list: 1. only
- Italic: __ only
- Bold: ** only
- Link: http:// or https:// only

Do not introduce alternate patterns for the same purpose. This keeps the editor simple and the parser reliable.

---

## EXAMPLE

Example content written in the official style:

# Admission Process

The application portal reopened for the new session. Students should review eligibility before submitting their records.

## Key requirements

* A valid email address
* A recent passport photo
* Correct JAMB details

1. Visit the official portal
2. Complete the form
3. Upload all required documents

The official portal is here: https://example.edu/admission

__Please note:__ deadlines are strict.

**Late applications will not be accepted.**

This format is natural for writers and safe for the parser.
