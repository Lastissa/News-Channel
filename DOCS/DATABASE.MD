# DATABASE
Every structure to how the database will be desinged will be listed here and for security reasons, details will not be added, just an hint on how the structure is.

## MAIN AUTHENTICATION TABLE
> For validating who is who

| Name | Purpose |
|---|---|
| `email` | Stores the user's unique email address and identifies the account. |
| `password` | for security |
| `date_joined` | Records when the account was created. |
| `is_staff` | Determines whether the user has staff access. |
| `is_superuser` | Determines whether the user has superuser privileges. |
| `is_admin` | Identifies whether the user has administrative privileges. |
| `is_active` | Determines whether the account is currently active and allowed to authenticate. |
| `receive_email_login_alert` | Determines whether the user receives email alerts when a login occurs. |
| `send_newsletter` | Determines whether the user has opted to receive newsletters. |
| `profile_img` | for recognition and identification. Optional |

## PASSWORD RESET KEY TABLE

> One live password reset link per account. The reset link is stateless (email + key + sign), so before any password update the trio must still match a row here; the row is deleted the moment the password changes, making every link single use.

| Name | Purpose |
|---|---|
| `user` | The account the link belongs to. One row per account. |
| `key` | The 6 digit numeric half of the reset link. |
| `sign` | The 10 character alphanumeric half of the reset link. |
| `created_at` | Records when the link was generated. |

## BLOG/NEWS TABLE

> Houses every post / journalis content posted by staffs /admins

| Name | Purpose |
|---|---|
| `author` | Identifies the staff/admin account that created the post. |
| `image_1` | Stores the URL of the primary image associated with the post. The overview |
| `category` | Identifies the category of the post. *categories is subject to change*|
| `heading` | Stores the title or heading of the post. |
| `content` | Stores the main content of the post. |
| `views` | Tracks the number of times the post has been viewed. |
| `date_created` | Records when the post was created. |

## COMMENT TABLE

> Houses comments / feedback made under blog posts

| Name | Purpose |
|---|---|
| `author` | Identifies the user who made the comment. |
| `blog` | Identifies the blog post that the comment belongs to. |
| `content` | Stores the comment / feedback content. |