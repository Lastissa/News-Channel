# ARCHITECHTURE.MD
Project blueprint and decisions are documented here and on every update made to this project, revision are made here , also click on [footer](#footer) for last updated date and information on last changes made

## TABLE OF CONTENT

  * [Main scope](#main-scope)
  * [Sepration of concern](#sepration-of-concern)

  
## MAIN SCOPE
This project serves as a community services, i realized if i cant give money back to the community i come from yet, i can at least contribute to the development of student awareness online by creating a platform that helps student aware of what is happening around them both in a convinience method.
in collaboration with an accomplice of mine who have the required attentions and me that have the skills to build this, we decided to bring this project to live with one sole purpose "**MAKE INFORATION AFFORDABLE**".

## SEPRATION OF CONCERN
All apps defined inside this project are mobile meaning they can be moved without affecting the monolithical apporach this project utilize
```micro-service
AUTHENTICATION/
```
> Managing who and what you can do, seprated as currently its session based but when scalability arise, i can easily migrate it to any other authentication type.

```micro-service
admin/
```
> Manages every access admin has to this entire project, this is only seprated for code structurability not for future migration as the admin app will always be a part of the monolith

```micro-service
staff/
```
> Similar to the admin app but this ones have limited access to writing reports, category under which report fall to, creating a bio inside the project , having their own dedicated profile where all their article can be collated and they can share it as a resume since the og metadata will carry their bio, post count, views summation, profile picture and role
look into [database-structure](#) for more info on this, *The admin is also regarded as a staff as they are staff and admin at the same time so they also can have their own profile*

```micro-service
blog/
```
>  All blogs, news, etc data will be displayed and served through this app as its core purpose is to serve user interface 

```micro-service
api-v1/
```
> This project also allow external users to create their own application off it as it can also stand as a standalone api (*NOT IN THIS MVP CURRRENT AIM AS CURRENTLY IM FOCUSING ON WEB APPLICATION ONLY*)

## USER INTERFACE STRUCTURE
The ui target and response perfectly to both mobile and desktop, with mobile first css and all templates extending the base template [structure in ui.md](UI.MD)

## FOOTER

