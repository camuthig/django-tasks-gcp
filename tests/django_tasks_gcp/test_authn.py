from unittest import mock

from django.test import RequestFactory
from django.test import SimpleTestCase

from django_tasks_gcp.authn import OIDCTokenAuth


class OIDCTokenAuthTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.RequestFactory = RequestFactory()

    def test_missing_authorization_header_returns_none(self):
        authn = OIDCTokenAuth(service_account_email=None)
        request = self.RequestFactory.post("/", data=b"{}", content_type="application/json")
        self.assertIsNone(authn.authenticate(request))

    def test_invalid_authorization_header_returns_none(self):
        authn = OIDCTokenAuth(service_account_email=None)

        request = self.RequestFactory.post("/", data=b"{}", content_type="application/json", HTTP_AUTHORIZATION="invalid")
        self.assertIsNone(authn.authenticate(request))

        request = self.RequestFactory.post("/", data=b"{}", content_type="application/json", HTTP_AUTHORIZATION="Token invalid")
        self.assertIsNone(authn.authenticate(request))

    @mock.patch("django_tasks_gcp.authn.id_token.verify_oauth2_token")
    def test_invalid_token_returns_none_when_verification_raises(self, mock_verify):
        mock_verify.side_effect = Exception("invalid token")
        authn = OIDCTokenAuth(service_account_email=None)

        request = self.RequestFactory.post(
            "/",
            data=b"{}",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer bad.token.value",
        )

        self.assertIsNone(authn.authenticate(request))
        mock_verify.assert_called_once()

    @mock.patch("django_tasks_gcp.authn.id_token.verify_oauth2_token")
    def test_email_mismatch_returns_none(self, mock_verify):
        mock_verify.return_value = {"email": "not-matching@example.com"}
        authn = OIDCTokenAuth(service_account_email="service@example.com")

        request = self.RequestFactory.post(
            "/",
            data=b"{}",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer good.token",
        )

        self.assertIsNone(authn.authenticate(request))
        mock_verify.assert_called_once()
        # Ensure it was called with the token stripped from "Bearer ..."
        args, kwargs = mock_verify.call_args
        self.assertEqual(args[0], "good.token")

    @mock.patch("django_tasks_gcp.authn.id_token.verify_oauth2_token")
    def test_valid_token_and_matching_email_returns_idinfo(self, mock_verify):
        idinfo = {"email": "service@example.com", "sub": "1234567890"}
        mock_verify.return_value = idinfo
        authn = OIDCTokenAuth(service_account_email="service@example.com")

        request = self.RequestFactory.post(
            "/",
            data=b"{}",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer valid.token",
        )

        result = authn.authenticate(request)
        self.assertEqual(result, idinfo)
        mock_verify.assert_called_once()
