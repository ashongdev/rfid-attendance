"""
    Dreema Configuration Hook.
    Use these methods to customize the framework's behavior.
"""

from dreema import security, responses

""" 
    AUTHENTICATION
    Register your custom async authentication function here.
"""
# security.setAuthHandler(handler)



""" 
    EXTEND CODES
    Add app-specific status codes and messages:
"""
# responses.extendCodes({'PAYMENT_ERR': -100},...)
# responses.extendMessages({'PAYMENT_ERR': 'Payment failed from provider'},...)

