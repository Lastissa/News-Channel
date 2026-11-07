import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse


LEGACY_REPORT = {
    "csp-report": {
        "document-uri": "https://abureport.com.ng/story/example/",
        "violated-directive": "img-src",
        "blocked-uri": "https://images.example.com/photo.jpg",
        "source-file": "https://abureport.com.ng/static/home/js/app.js",
        "line-number": 12,
        "column-number": 4,
        "script-sample": "",
        "disposition": "report",
        "status-code": 200,
    }
}

REPORTING_REPORT = [
    {
        "type": "csp-violation",
        "body": {
            "documentURL": "https://abureport.com.ng/",
            "effectiveDirective": "script-src",
            "blockedURL": "inline",
            "sourceFile": "https://abureport.com.ng/",
            "lineNumber": 3,
            "columnNumber": 1,
            "sample": "alert(1)",
            "disposition": "report",
            "statusCode": 200,
        },
    }
]


@override_settings(
    CSP_REPORT_ENABLED=True,
    CSP_REPORT_EMAIL="lastissa11@gmail.com",
    CSP_REPORT_MAX_BYTES=16 * 1024,
    CSP_REPORT_DEDUPE_SECONDS=60 * 60,
    CSP_REPORT_MAX_EMAILS_PER_HOUR=20,
    MAINTENANCE_MODE="FALSE",
)
class CSPReportTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_security_header_advertises_the_report_endpoint(self):
        response = self.client.get("/robots.txt")

        self.assertEqual(response.status_code, 200)
        policy = response["Content-Security-Policy-Report-Only"]
        self.assertIn("report-uri", policy)
        self.assertIn(reverse("csp_report"), policy)
        self.assertEqual(
            response["Reporting-Endpoints"],
            f'csp-endpoint="http://testserver{reverse("csp_report")}"',
        )

    @patch("SERVICE_INTERNAL.email_single._try_send_csp_report_email")
    def test_legacy_csp_report_sends_one_email(self, send_email):
        response = self.client.post(
            reverse("csp_report"),
            data=json.dumps(LEGACY_REPORT),
            content_type="application/csp-report",
        )

        self.assertEqual(response.status_code, 204)
        send_email.assert_called_once()
        report = send_email.call_args.args[0]
        self.assertEqual(report["violated_directive"], "img-src")
        self.assertEqual(report["blocked_uri"], "https://images.example.com/photo.jpg")

    @patch("SERVICE_INTERNAL.email_single._try_send_csp_report_email")
    def test_reporting_api_payload_sends_one_email(self, send_email):
        response = self.client.post(
            reverse("csp_report"),
            data=json.dumps(REPORTING_REPORT),
            content_type="application/reports+json",
        )

        self.assertEqual(response.status_code, 204)
        send_email.assert_called_once()
        report = send_email.call_args.args[0]
        self.assertEqual(report["violated_directive"], "script-src")
        self.assertEqual(report["script_sample"], "alert(1)")

    @patch("SERVICE_INTERNAL.email_single._try_send_csp_report_email")
    def test_duplicate_report_is_deduplicated(self, send_email):
        for _ in range(2):
            response = self.client.post(
                reverse("csp_report"),
                data=json.dumps(LEGACY_REPORT),
                content_type="application/csp-report",
            )
            self.assertEqual(response.status_code, 204)

        send_email.assert_called_once()

    @override_settings(CSP_REPORT_MAX_EMAILS_PER_HOUR=1)
    @patch("SERVICE_INTERNAL.email_single._try_send_csp_report_email")
    def test_hourly_email_cap(self, send_email):
        first = json.loads(json.dumps(LEGACY_REPORT))
        first["csp-report"]["blocked-uri"] = "https://one.example/a.png"
        second = json.loads(json.dumps(LEGACY_REPORT))
        second["csp-report"]["blocked-uri"] = "https://two.example/b.png"

        for payload in (first, second):
            response = self.client.post(
                reverse("csp_report"),
                data=json.dumps(payload),
                content_type="application/csp-report",
            )
            self.assertEqual(response.status_code, 204)

        send_email.assert_called_once()

    @patch("SERVICE_INTERNAL.email_single._try_send_csp_report_email")
    def test_malformed_payload_is_rejected_without_email(self, send_email):
        response = self.client.post(
            reverse("csp_report"),
            data="{not json",
            content_type="application/csp-report",
        )

        self.assertEqual(response.status_code, 400)
        send_email.assert_not_called()

    @patch("SERVICE_INTERNAL.email_single._try_send_csp_report_email")
    def test_oversized_payload_is_rejected(self, send_email):
        with override_settings(CSP_REPORT_MAX_BYTES=10):
            response = self.client.post(
                reverse("csp_report"),
                data=json.dumps(LEGACY_REPORT),
                content_type="application/csp-report",
            )

        self.assertEqual(response.status_code, 413)
        send_email.assert_not_called()

    @override_settings(CSP_REPORT_ENABLED=False)
    def test_report_endpoint_can_be_disabled(self):
        response = self.client.get("/robots.txt")

        policy = response["Content-Security-Policy-Report-Only"]
        self.assertNotIn("report-uri", policy)
        self.assertNotIn("report-to", policy)
        self.assertNotIn("Reporting-Endpoints", response)

    @override_settings(CSP_REPORT_EMAIL="alerts@example.com")
    @patch("SERVICE_INTERNAL.email_single._dispatch_email")
    def test_email_builder_uses_configured_recipient(self, dispatch_email):
        from SERVICE_INTERNAL.email_single import _try_send_csp_report_email

        _try_send_csp_report_email(
            {
                "document_uri": "https://abureport.com.ng/",
                "violated_directive": "img-src",
                "blocked_uri": "https://images.example.com/photo.jpg",
                "source_file": "https://abureport.com.ng/static/home/js/app.js",
                "line_number": "12",
                "column_number": "4",
                "script_sample": "",
                "disposition": "report",
                "status_code": "200",
            }
        )

        dispatch_email.assert_called_once()
        recipient = dispatch_email.call_args.args[0]
        subject = dispatch_email.call_args.kwargs["subject"]
        html_message = dispatch_email.call_args.kwargs["html_message"]
        self.assertEqual(recipient, "alerts@example.com")
        self.assertIn("CSP violation", subject)
        self.assertIn("img-src", subject)
        self.assertIn("images.example.com", html_message)
