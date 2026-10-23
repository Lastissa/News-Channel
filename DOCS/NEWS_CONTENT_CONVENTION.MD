# NEWS CONTENT CONVENTION

This document explains how news content should be written so it remains natural for human editors and still reliable for automated parsing.

## CORE PRINCIPLE

Writers should write like normal article content. They do not need to think like developers. The parser should detect structure from simple patterns instead of requiring complex markup.

To keep the system clear and safe, each job has one official format only.

---

## EDITORIAL QUALITY RULES

These rules decide whether a story may be published. They are enforced by the
editor on the server (`SERVICE_INTERNAL/story_validation.py`, used by the Add
News form) and are repeated in the author handbook for writers.

1. **Length.** A story body must carry at least 300 words of real content. Under
   100 words the editor blocks the post; between 100 and 300 it warns and the
   author must confirm. Short posts reach fewer readers and weaken the site's
   eligibility for advertising partners.
2. **Source.** Every story must name where its facts came from: a `Source:` line
   or a link in the body. A story built on another outlet's report, a social post
   or a press release must say so.
3. **Originality.** Do not publish a single tweet, a single social post or a
   lightly reworded copy of another report as a full article. Add the facts,
   names, dates and detail readers cannot get from the source alone.
4. **No filler.** Do not pad the body with sentences that carry no information.
   Say each fact once, then move on.
5. **Keep promotion out of the news feed.** About-us pieces and business
   promotions are not news. They belong on the promotion surface, never in a
   news category.

---

## OFFICIAL FORMATS

### 1) LINKS

A link has two allowed shapes:

- A short phrase that hides a long address: `[words](https://...)`
- A bare address pasted as it is: `https://...`

Examples:

Read the [admission guide](https://myschoolgist.com/news/unilag-post-utme-form/) before you apply.

The official portal is https://myschoolgist.com/news/unilag-post-utme-form/

Rule:
- Prefer `[words](https://...)` whenever the address is long, so the reader
  sees a word instead of a wall of characters.
- The parser turns `[words](url)` into a link whose visible text is `words`
  and whose destination is the address inside the brackets.
- A bare URL is still auto-linked, but it shows the whole address. Use it
  only for short addresses or a link simply pasted into the text.
- Both shapes are parsed in one pass, so the address inside `[words](...)`
  is never linked a second time.
- A link may appear inside a paragraph, a heading, or a list item.

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
- Headings are also the story's jump targets. The editor's "Table of contents"
  dropdown decides whether the story page shows a "TABLE OF CONTENT" section
  right after the opening paragraph, and how much of it opens on arrival:
  Off (no list), Level 1 - title only, Level 2 - top sections, or Level 3 -
  fully open. It is Off by default and only the author can change it; the
  choice is a display setting, not an edit, so it never moves the story's last
  published time.

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

### 7) INLINE IMAGES

Any line that starts with imgl, imgr, or imgc should be treated as an inline image.

Example:

imgl https://a.com/pic.jpg A cat sitting
imgr https://a.com/pic.jpg A dog running
imgc https://a.com/pic.jpg A city skyline at night

Rule:
- The first word on the line is the keyword: imgl, imgr, or imgc.
- The second word is the image URL.
- Everything after the URL, on the same line, is the alt text.
- imgl floats the image left. imgr floats the image right. In both cases the surrounding paragraph text wraps around the image; it is never rendered as its own full-width block.
- imgc centers the image and blocks -- it sits on its own line, and unlike imgl/imgr nothing wraps around it.
- If no alt text is given after the URL, the parser falls back to the filename taken from the URL. Example: imgl https://a.com/cat.jpg produces alt="cat.jpg".
- The inline image (imgl, imgr, or imgc) is always rendered smaller than the page's top-level (hero) image.
- This token is parsed before headings, bold, and italic, so an image URL or its alt text is never partially consumed by #, **, or __.
- Do not introduce an alternate syntax for inline images.

### 8) INLINE FILES

Any line that starts with filel should be treated as an inline, downloadable file link.

Example:

filel https://a.com/report.pdf 2025 Annual Report

Rule:
- The first word on the line is the keyword: filel.
- The second word is the file URL.
- Everything after the URL, on the same line, is the link text shown to the reader.
- Unlike imgl/imgr, a filel link is never floated -- it sits inside the normal paragraph flow, as a plain download link (imgc is not floated either, but it still blocks onto its own line the way a picture does; filel never does that).
- Clicking it downloads the file instead of navigating the reader away from the story.
- If no link text is given after the URL, the parser falls back to the filename taken from the URL. Example: filel https://a.com/report.pdf produces the visible text "report.pdf".
- This token is parsed before headings, bold, and italic, so a file URL or its link text is never partially consumed by #, **, or __.
- Do not introduce an alternate syntax for inline files.
- The easiest way to get a filel line: upload the file to /archive/ (Add Image / File), then use its "Copy url" button, which copies a ready `filel <url> <description>` line straight to the clipboard.

### 9) INLINE VIDEOS

Any line that starts with vidl, vidr, or vidc should be treated as an inline video.

Example:

vidl https://a.com/clip.mp4 Crowd at the rally
vidr https://a.com/clip.mp4 The damaged bridge
vidc https://a.com/clip.mp4 Flood water rising

Rule:
- The first word on the line is the keyword: vidl, vidr, or vidc.
- The second word is the video URL. A direct file (MP4/MOV/WEBM/OGG, e.g. an /archive/ upload) plays in a plain `<video>`. A provider PAGE is embedded with the provider's own player instead: YouTube (watch, share, Shorts, live), Vimeo, TikTok, Instagram Reels/posts, Facebook, Dailymotion, Twitch clips, X/Twitter, Rumble, Odysee, Streamable, VK, Loom and Google Drive. Portrait providers (TikTok, Reels, Shorts) reserve a 9:16 box; the others use 16:9. Paste the full video page URL (for TikTok use the `tiktok.com/@user/video/...` address, not a `vm.tiktok.com` short link).
- Everything after the URL, on the same line, is the caption shown beneath the video.
- vidl floats the video left. vidr floats the video right. In both cases the surrounding paragraph text wraps around the video; it is never rendered as its own full-width block.
- vidc centers the video and blocks -- it sits on its own line, and unlike vidl/vidr nothing wraps around it.
- The video plays on its own (autoplay), muted, on a loop, and shows two overlaid controls: a play/pause button and a sound (mute/unmute) button. There is no native control bar, no seek bar, and no fullscreen.
- Sound is off by default. When the reader switches sound on, the video only plays aloud while it is on screen: as soon as it scrolls out of view it goes silent, and its sound comes back when the video is visible again (until the reader mutes it).
- If no caption is given after the URL, no caption is drawn beneath the video.
- The inline video (vidl, vidr, or vidc) is always rendered smaller than the page's top-level (hero) image.
- This token is parsed before headings, bold, and italic, so a video URL or its caption is never partially consumed by #, **, or __.
- Do not introduce an alternate syntax for inline videos.
- The easiest way to get a video line: upload the clip to /archive/ (Add Image / File), then use its "Copy url" button for the URL. Videos must be MP4 or MOV and 10MB or smaller; other files are capped at 3MB and pictures at 5MB. An oversized upload is refused right away with the size in the message, so shrink or trim the clip and try again.

### 10) BUTTONS

Any line that starts with the word `btn` should be treated as a button.

Example:

btn https://a.com/apply Start your application
btn https://a.com/donate Donate to the fund

Rule:
- The first word on the line is the keyword: `btn`.
- The second word is the destination URL.
- Everything after the URL, on the same line, is the text printed on the button.
- The button sits on its own line and nothing wraps around it. It is a link
  (a call to action such as Apply, Register, Donate or Subscribe), not a download.
- If no text is given after the URL, the URL itself is printed on the button.
- Use `[words](url)` for a link inside a sentence; use `btn` on its own line
  when the link should stand out as a button a reader can tap.
- Do not introduce an alternate syntax for buttons.

---

## WRITING STYLE FOR AUTHORS

Writers should use plain article writing. They should not be forced to think in markup.

Recommended guidance for writers:

- Write in normal paragraphs.
- Write at least 300 words of real content. A body under 100 words is blocked by the editor.
- Always name your source with a `Source:` line or a link in the body.
- Leave a blank line between paragraphs.
- Start a new line with * for bullet points.
- Start a new line with 1. for numbered points.
- Start a new line with # for section titles.
- Paste a link as a full URL, or write [words](url) so a long address shows as a short phrase instead.
- Start a new line with btn, followed by the URL and the text the button carries, to place a call-to-action button (Apply, Register, Donate, Subscribe).
- Use bold or italic only when needed, using the allowed markers.
- Start a new line with imgl or imgr, followed by the image URL and optional alt text, to place a small inline image that floats left or right.
- Start a new line with imgc, followed by the image URL and optional alt text, to place a small inline image that is centered and blocking instead of floated.
- Start a new line with vidl or vidr, followed by the video URL and optional caption, to place a small inline video that floats left or right and plays on its own with a play/pause button and a sound button (sound starts off).
- Start a new line with vidc, followed by the video URL and optional caption, to place a small inline video that is centered and blocking instead of floated.

---

## PARSING ORDER

To avoid conflict, the parser should process content in this order:

1. Detect inline image tokens (imgl/imgr/imgc) first, so their URL and alt text are never consumed by another marker
2. Detect inline video tokens (vidl/vidr/vidc) next, for the same reason
3. Detect inline file tokens (filel) next
4. Detect button lines (btn) next
5. Detect heading blocks next
6. Detect unordered and ordered list blocks next
7. Detect links in text, both [words](url) and bare URLs
8. Detect bold and italic inline markup
9. Treat remaining text as normal paragraphs

This order prevents a line from being misread as ordinary copy when it is actually a heading, list, or link.

---

## ONE FORMAT PER JOB

This is the most important rule:

- Heading: # only
- Unordered list: * only
- Ordered list: 1. only
- Italic: __ only
- Bold: ** only
- Link: [words](url) for a short phrase over a long address, or a bare http:// or https:// URL
- Inline image: imgl (left), imgr (right), or imgc (centered, blocking) only
- Inline video: vidl (left), vidr (right), or vidc (centered, blocking) only
- Inline file: filel only
- Button: btn only

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

imgl https://example.edu/images/campus-gate.jpg Students queue at the campus gate

__Please note:__ deadlines are strict.

**Late applications will not be accepted.**

This format is natural for writers and safe for the parser.
