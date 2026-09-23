"""
------------------------------------------------------------
#   SEND SINGLE EMAIL ONLY SECTION  
------------------------------------------------------------
"""

from SERVICE_INTERNAL.abstract import info_logger
import resend
from django.conf import settings

resend.api_key = getattr(settings, 'RESEND_API_KEY')

def _sendSingleMail(receiver, subject, html_message = None, message = None, sender='noreply', wait = False):
    """
    TODO:SET IT TO ASYNC MODE BEFORE PROD
    """
    domain='support@resend.dev'
    if wait:
        """WAIT FOR RESPONSE AND DO NOT FIRE AND FORGET"""
    
params = {
    # "from": "Testing <newme@abureport.com.ng>",
    "from": "Testing <newme@resend.dev>",
    "to": ["lastissa11@gmail.com"],
    "subject": "hello world",
    "html": "<strong>it works!</strong>",
}

# email = resend.Emails.send(params)
# print(email)

def _base_email(sender, receiver, message = None, html_message = None):
    "TODO: Create a html like with reusable component (head - Project identity), body: house content, footer-contact support details with no marketing advert"
    info_logger(msg=f"{sender} Sent A mail To {receiver}.")


def _try_send_login_email(user: object):
    """
    Receives the user queryset and look for the login alert
    if found, send email, else just comot eye
    #   LOGGER ALREADY SET UP
    """
    
    if user.receive_email_login_alert:
        #send mail
        email = resend.Emails.send(params)
        print(email)
        info_logger(msg=f"EMAIL: successfully sent login alert to {user.email} as they have reminder enanbled in their account")
    else:
        info_logger(msg=f"LOGIN ALERT: {user.email} logged in but no login alert was sent as they have it disabled")


def _try_send_password_reset_email(user: object, reset_link: str):
    """
    Receives the user and the freshly generated reset link and "sends" it.
    NO EXTERNAL MAIL PLATFORM IS WIRED YET, so the mail is printed to the
    terminal, same as the login alert above. The printed line carries the
    full link so the flow stays testable during development.
    """
    info_logger(msg=f"EMAIL (DUMMY, PRINTED TO TERMINAL): password reset requested for {user.email}")
    info_logger(msg=f"RESET LINK for {user.email}: {reset_link}")
    
