from datetime import datetime, timedelta
from django.http import HttpResponse
from gateway.models import SendSMS
from therapyedge.tests.utils import random_string

class Gateway(object):
    """Dummy gateway we used to monkey patch the real RPC gateway so we can write
    our test code against something we control"""
    
    def send_sms(self, msisdns, smstexts, delivery=None, expiry=None,
                        priority='standard', receipt='Y'):
        delivery = delivery or datetime.now()
        expiry = expiry or (datetime.now() + timedelta(days=1))
        send_sms_ids = [SendSMS.objects.create(msisdn=msisdn, \
                                        smstext=smstext, \
                                        delivery=delivery, \
                                        expiry=expiry, \
                                        priority=priority, \
                                        receipt=receipt, \
                                        identifier=random_string()[:8]).pk
                            for (msisdn, smstext) in zip(msisdns, smstexts)]
        # Return a Django QuerySet instead of a list of Django objects
        # allowing us to chain the QS later on
        return SendSMS.objects.filter(pk__in=send_sms_ids)


# yuck
from gateway.backends.opera.backend import sms_receipt_handler
gateway = Gateway()
