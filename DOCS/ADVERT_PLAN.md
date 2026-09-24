# ADVERTS / PROMOTION PLAN FOR END USER AND AD OWNER

this file treats two people with teo different pov 
* People Looking to Post Their Advert On Our Platform = partners
* How to Servce those advert to people that are goign to use our platform. = endusers

## PARTNERS
They often meet us at the promote page where they get to view our prices & structure to tailor their bussiness for endusers.

__Their Login Page is designed as promote/login that send a post to check if user exist, it takes the email and prefix it with 'promote-' so it can match if any partner exist__
.
 __after choosing a plan, they get taken to promote/register where the url already carry the plan they choose and ask for their email and password, in the view that collect the email and password and send a post request to the the view in charge, the view in charge takes the details and prefix the email with 'promote-' so incase the user is a regular user who already have an account and wanted to choose plan with us, there wont be any issue, only create the auth user model__
AUTHENTICATION: __PARTNERS are not using the regular __

Types of Plan we will offer
* standard plan: this plan inform the user their add shows in news page, a dashboard for analytics(a signed encrypted endkey they should not share with anyone will be given to them to login to their dashboard), max of 10 ads before unalbe to upload ads again and they either upgrade or just stay like that till expiry, price is 1k Naira/month 

* standard + : every thing in standard except they  
