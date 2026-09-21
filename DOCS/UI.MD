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

### AUTHOR PORTFOLIO (`/portfolio/<id>/`)
Template `STAFF/templates/staff/portfolio.html`, styles `STAFF/static/staff/css/portfolio.css`, numbers computed in `STAFF/views.py`.
- Placard: a fixed 30% left strip on the nav background (picture, follow button, centred) split from the identity column by a thick brand line, on mobile and desktop alike. Identity column: role, name, email, contact icons (an empty social is skipped), quick facts (sex, team since, last promoted, most covered, last published), counts, follow note, editorial focus.
- Floating buttons on this page are the author's own (email plus filled socials) via the `floating_social` block, not the project's.
- Key numbers strip: eight tiles, the six totals plus author rank (among active authors by stories posted) and most viewed story.
- Charts, all real data and pure HTML/SVG: recent story reach, coverage ranking, publishing rhythm (last 6 months), readership donut (views by category), reader response (views against readers, likes, comments, saves).
- Cards sit on a 12 column grid from 720px and use container queries, so they adapt to their own width.
