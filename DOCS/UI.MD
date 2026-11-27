# USER INTERFACE ARCHITECHTURE
Every decision regarding user interface is made here 

## NEWS CONTENT WRITING CONVENTION
See [NEWS_CONTENT_CONVENTION.MD](NEWS_CONTENT_CONVENTION.MD) for the approved writing format for all news content. Every story must follow the single-format rules for headings, lists, links, bold, and italic so the parser stays predictable and writers stay consistent.

## SOC
The ui target and response perfectly to both mobile and desktop, with mobile first css and all templates extending the base template , each app have its own dedicated templates and any general templates live in the service_internal like the base template

### BASE TEMPLATE STRUCTURE

All other templates in this project extends it as it carries the root strcture of how the user interface looks like.

**mobile**
> header: project name + logo + search btn + open nav [Nav bar contanin this as it vary slightly when signed in and when not signin](#nav-bar-cotent)

> Body: will be determined by the extendee

> footer: splitted into two: one for quick "receive newsletter form that collect only email informing the user that when they decide to finaly join become a memeber and the persk of being a member is bookmark and viewing history news(they they have viewed before can be shown to them alongside date they viewed it ), also they can set prefrence for theme on any device, they just have to press forgot password but until them  " arranged vertically with background same as the header, the other for footer details like socials *availanle in SERVICES_INTERNAL.config.About*

**Desktop**
> header: uses nav-bar content also, the difference is tht, it is not uisng a nav bar icon, also, the headers responds properly to hover

> body and footer are similar to mobile too except the footer is not verticallly stacked but horiontally

<u style="color:pink">*All colour architecture lives in the base template css file*</u>


#### NAV BAR COTENT
all links is prototype as their views will be put in place soon, lastly there should be a toggle theme icon in the nav bar
|signed In| Not signed in|
|---|---|
HOME|HOME|
EDITORIAL TEAM|EDITORIAL TEAM|
NEWS CATEGORY with a dropdown of its own for all categories |NEWS CATEGORY with a dropdown of its own for all categors|
Scholarship|Scholarship|
Bookmarks| Signup|
Profile| Login|



### LANDING / HOME PAGE STRUCTURE
Since this willl be extending the [base template](#base-template-structure), the body is only the important asect, by default, 

**Page Layout**
hero section:  carousel slider with btn to seitch manually and also switcha automatically of 6 featured post (take the first 6 from what the render context is passing and use it here , if not up to 6 then use only whatever is available even if its 2 or 1 or 3 and if zero, give a no news slider), 
positioning of hero content: image link set as the bg, heading set over the bg bold, name of the author also added, the hero should have a label "FEATURED POST", two glasmhotphic btn, "SHARE STORY"(IT COPIES THE LINK TO THAT STORY) on target _self and "READ STORY" that open that story on target _self. also there should be a bookmark icon at the top right of the hero(this also aplies to other news that is not in hero),this button once click send a post requwst to "demo endpoint", the endpoint perform the update or fail if no logged in user, but it alwasy retur a jsonreponse witl detail as key alwasy , just different status code depending on the situaltuon.

the remaiing body should be news and also a button at the end for "load more", not just a regular button but one that is detailed and interactive in 3d  

---


### BRAND COLOUR
The accent is Signal Cyan. Tokens live in `HOME/static/home/css/base.css`: `--brand` (#22D3EE, fills and anything sitting on the navy nav or footer), `--brand-deep` (#0B6E8A on light paper, cyan on the dark theme, for text and lines), `--brand-hover`, `--brand-wash` and `--on-brand` (navy text that sits on a brand fill). Never hard code the hex in a template or stylesheet. `--amber-alt` is the green used by the profile page despite its name.

### TEXT COLOUR (readability rule)
Text must stay dark and readable. `--slate` is not a body-text colour.

- Running text uses `--ink`: paragraphs, page intros and ledes, story excerpts, list items, bylines, dates and timestamps, captions, notes, hints, help text, empty-state lines, and table cells.
- `--slate` is reserved for very short subheadings only (eyebrows and micro labels: a few words, usually uppercase with letter-spacing), and for borders, rules, dividers, separators and icons.
- Never paint a paragraph or any running text with `--slate` or a low-opacity ink. It reads as washed out or disabled, and it lowers contrast.
- This is why early pages looked grey: `--slate` had been adopted as a general secondary text token across components. When in doubt, use `--ink`. A short label may still use `--slate`, but nothing longer than a few words.

### AUTHOR HANDBOOK (`/author-handbook/`)
Template `HOME/templates/HOME/author_handbook.html`, styles `HOME/static/home/css/doc-reader.css` plus `HOME/static/home/css/author-handbook.css`, script `HOME/static/home/js/author-handbook.js`.
- The default view is one plain vertical document: masthead, a short Contents list, then hairline-ruled sections.
- A `Read as slides` button in the masthead switches to a horizontal, snap-scrolling deck, one section per slide, for authors who prefer to page through it. A sticky bar with Previous, Next, the slide name and a Close button sits at the top while the deck is open. Arrow keys move, Escape closes. The script only adds this mode; without it the page is still a complete document.

### AUTHOR PORTFOLIO (`/portfolio/<id>/`)
Template `STAFF/templates/staff/portfolio.html`, styles `STAFF/static/staff/css/portfolio.css`, numbers computed in `STAFF/views.py`.
- Placard: a fixed 30% left strip on the nav background (picture, follow button, centred) split from the identity column by a thick brand line, on mobile and desktop alike. Identity column: role, name, email, contact icons (an empty social is skipped), quick facts (sex, team since, last promoted, most covered, last published), counts, follow note, editorial focus.
- Floating buttons on this page are the author's own (email plus filled socials) via the `floating_social` block, not the project's.
- Key numbers strip: eight tiles, the six totals plus author rank (among active authors by stories posted) and most viewed story.
- Charts, all real data and pure HTML/SVG: recent story reach, coverage ranking, publishing rhythm (last 6 months), readership donut (views by category), reader response (views against readers, likes, comments, saves).
- Cards sit on a 12 column grid from 720px and use container queries, so they adapt to their own width.

### PROFILE PICTURE UPLOAD (`/profile/`)
Template `HOME/templates/HOME/profile.html`, styles `HOME/static/home/css/profile.css`, script in the "profile avatar" section of `HOME/static/home/js/interactions.js`.
- The picture is updated from a file only, through the single Upload avatar (file) button. There is no option to paste an image link.
- Picking a file never uploads it. It opens the Adjust photo window: drag to reposition, slider, mouse wheel or pinch to resize, live circular preview. Nothing is sent until Confirm upload is pressed. Cancel or Escape throws the choice away.
- What is sent is the framed square, cut in the browser to a 512 x 512 JPEG, so the file is small and is exactly what the preview showed.
- Each account owns one avatar asset in Cloudinary (`abureport/avatars/user_<id>`). A new upload overwrites it and never adds another image (see `SERVICE_INTERNAL/images.py`).

### AUTHOR ANALYTICS TAB (`/profile/analytics/`)
Templates `HOME/templates/HOME/profile.html`, `HOME/templates/HOME/profile_analytics.html` and `HOME/templates/HOME/partials/profile_analytics_panel.html`, styles `HOME/static/home/css/profile-analytics.css`, script `HOME/static/home/js/profile-analytics.js`, data builder `HOME/author_analytics.py`.
- The green **View analytics** button sits first in the profile jump links. It uses `--brand` for its border and glow, keeps the toolbar and jump links in place, and fetches the panel only on the first open. Later clicks jump to the panel already on the page. Returning to the profile restores the lazy fetch for the next visit.
- HTMX swaps `#profile-content` when the header says `HX-Request: true`; a direct URL renders a complete page. `hx-push-url` keeps the browser Back button working across the panel, ranges and the profile.
- The panel shows six KPI tiles, a sortable own-story table, three rank cards, an overall position, a source breakdown and two Google name rows. 7, 30 and 90 days filter all of them. Admin users get an author dropdown whose value is kept only in the session.
- Source labels come from `SERVICE_INTERNAL/traffic.py`. The screen states that Referer is the primary signal and UTM is the fallback. Every displayed count comes from real engagement rows plus pending cache rows. There is no chart and no invented sample data.

### EDITOR PREVIEW AND CLEAR CONTROLS (`/add-news/`, `/profile/stories/<id>/edit/`)
Templates `HOME/templates/HOME/add_news.html` and `HOME/templates/HOME/edit_news.html`; scripts `HOME/static/home/js/add-news-editor.js`, `HOME/static/home/js/edit-news-editor.js` and `HOME/static/home/js/editor-clear-writeup.js`; styles `HOME/static/home/css/add-news.css` and `blog/css/story-detail.css`.
- The preview reuses the published story layout and stylesheet. Empty values become plain placeholder labels and the word count is the only metric. Views, likes, share controls, bookmarks, follows, rails, adverts and comments are omitted because they are live page features, not draft content.
- The add page image row now carries the clear button in the place once used by the duplicate image row load button. The toolbar keeps its own **Load news** button and file input.
- Clear and revert both use the shared two-step dialog. Step one is Yes or No. Step two repeats the warning, shows "CALM DOWN AND READ IT PROPERLY", drains a bar for 1.5 seconds, and disables Yes until it finishes. No, Escape or a backdrop click changes nothing.
- Add clears every editor field, the selected upload and the local draft. Edit reverts every editable field, the selected upload and the local draft to the values rendered from the published story. Neither action sends a save request.

### IN-STORY ADVERT POPUP
JSON endpoint `blog:story_ads`, script `BLOG/static/blog/js/story-ads.js`, pool loader and cache key in `BLOG/views.py`.
- The popup is built with DOM nodes and textContent only. An advert with a real `AdvertReference` receives `view_url` and `click_url` pointing at the existing public tracking endpoints.
- The view pixel is fired only after the popup has been appended to the page. A `t` query value stops the browser reusing a cached GIF.
- A click uses the tracked `click_url` when it exists. Adverts without a reference keep their old landing or external link and are not counted in the database.
