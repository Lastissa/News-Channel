# REMAINING PHASE

## ADS MNGT 

## SERVICES MNGT

# REASON FOR ORDER OF OPERATION

First focus is on the ads mngt because its faster and easier to finish since there is already a scope available for it

# ADS MNGT - FULL
## TODO:
### Advertiser onboarding
In the /promote-your-bussiness/-> the page open a welcome with benefits of advertising with abureport and quick ux of "ready to promote your bussiness? create account to view up to date analytics and data about your adverts"

"advertise their product at just 255 Naira "

#### prices ordering
* **REGULAR:** create adverts that user see and place the banner on our news channel = 255 naira weekly
* **PRO:** regular + have a dedicated single page website build for your bussiness + analytics dashboard to track clicks, views, traffic coming from abureport itself, traffick coming from other clickes(differentiatable because by default abureport send utm_source to all its advert)= 500 naira weekly
* **ADVANCE:** premium user interface + multipage(sub path e.g /about/ etc , all custom) and desing for hooking user to your products (NB: WE CANNOT GURANTEE USER PURCHASING YOUR PRODUCT AT THE END BUT WE WILL TRY TO HOOK THEM) = 1000 weekly + free personalized domain + free SEO handling + all benefit from **PRO** = 1000

this plans are shown in the partner-with-us page/ alongisde the image(advertise with us image)

Special Launch promo: as we just launch - we are offering advance plan for just 500 , tap to get your discount (the tap already holds a message where advertiser send a prefilled whatsapp dm to contact support number and then the whatsap contact can generate a real refrence id for them ), **REFRENCE ID IS A CRYTOGRAPHIC SIGNATURE USED THAT IS USED AS THE PRYMARY KEY TO ACCESS THE ROW CARRYING DATE_CREATED, PLAN_NAME, ADVERTISER_ID(foreign key to auth - an extra feild is_advertiser boolean)**


----
* For The advance -  
---

---
**implementing paystack was rigid so swithcing to a more secure mean of payment** -> generate a refrence id at point of payment and the amount to pay based on what the potential advertiser have select from our advertising plan(all the )
* dedicated 

### Advertiser dashboard
- [x] Advertiser sign-up at `/auth/advertise/signup/`, tagged with `Auth.is_advertiser`.
- [x] Advertiser dashboard at `/advertise/dashboard/` showing real advert enquiries and an honest empty state for click/view performance.
- [x] Advertiser profiles default to the dashboard, with links back to the reader profile.
- [x] Issue one `AdvertReference` per advert. It is permanent, stored plaintext, and linked to an existing `Auth` account selected by email. Keep the plan expiry as a separate field.
- [x] Reference format: 16 characters = first 5 letters of the account email + `DDMMYY` + 5 random characters. Enforce uniqueness and show it only to the owner and ads staff.
- [x] Add reference issuance to the staff flow after payment is confirmed. Do not create duplicate references when the same email buys another advert; issue a new reference for each advert, not each account.
- [x] Require a signed-in account that owns the reference before showing analytics or advert controls. Registration logs users in without email verification, so the owner check must not rely on the email being verified.
- [x] Add `Auth.is_ads_staff`. Make it selectable on Create Staff and editable on staff detail, and use it to grant ads/PANEL access without granting full superuser rights.
- [x] Track advert clicks and views. On-site links should carry `utm_source=abureport`; classify external traffic separately so the dashboard can show on-site vs external performance.
- [x] Add advert lifecycle fields (status, start/end dates, plan, public page URL) and a staff view for pausing, renewing, and replacing an advert.
- [x] Keep `/ads/` staff-built on our domain. If raw HTML remains in use, validate or sanitise it before render and keep CSP report suppression scoped to `/ads/` only.
- [x] Keep the Home advert rail reader-driven: add autoplay, no numeric counter, and always horizontally scrollable.
- [x] Add a 32-second click-to-play advert preview to the promote page, with a local poster, native controls, and no autoplay.
- [x] Serve the promote flow from `ads.<domain>/` and 301 the old `/promote-your-bussiness/` URLs there, with ads-host canonical/social URLs and news-site links returning to the main domain.
- [x] Show `AdvertReference.subdomain` in Django admin list/search for ads staff review.

The ads desk lives at `/control/ads/` (admin, superuser or `Auth.is_ads_staff`). Tracking routes live under `/ads/view/<reference>/` and `/ads/click/<reference>/`; paused or expired references stop showing in the home rail and stop sending readers to the advertiser. Views are deduplicated per session/IP for an hour and clicks for five seconds, and raw IPs are never stored.

The public page is served from `https://ads.<domain>/` when `ADS_HOST` is set, or derived from the first public `ALLOWED_HOSTS` entry in production. Local, ngrok and test hosts keep the path until `ADS_HOST` is set explicitly. DNS and TLS for the ads subdomain still need to be added at the domain/hosting provider before the production host can resolve.

Follow-ups: targeted subdomain/ads-host/desk tests and any remaining advertiser analytics/dashboard gaps should be added or updated as the ads product scope is finalized.

### Analytics for advertiser

