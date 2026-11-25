"""
USIN VTPASS CURRENTLY
"""

import requests, json

# WAEC RESULT CHECKER
sandbox_url = "https://sandbox.vtpass.com/api/service-variations?serviceID=waec"
live_url = "https://vtpass.com/api/service-variations?serviceID=waec"

a = requests.get(sandbox_url)
print(json.loads(a.text))
