import abc
from typing import Any

from django.http import HttpRequest
from google.auth.transport import requests
from google.oauth2 import id_token

class ViewAuth(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def authenticate(self, request: HttpRequest) -> Any | None:
        pass

class OIDCTokenAuth(ViewAuth):
    def __init__(self, service_account_email: str | None):
        self.service_account_email = service_account_email

    def authenticate(self, request: HttpRequest) -> Any | None:
        token = request.headers.get("Authorization")
        if not token:
            return None

        token = token.split(" ")[1]

        try:
            idinfo = id_token.verify_oauth2_token(token, requests.Request())

            if self.service_account_email and idinfo["email"] != self.service_account_email:
                return None

            return idinfo
        except BaseException as e:
            return None
