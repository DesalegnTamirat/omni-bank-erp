# -*- coding: utf-8 -*-
"""Scenarios 1-8 of the SMS / Email notification requirement.

The cbs_integration row used here is a throw-away TEST row (environment
'SMS_TEST', fake values) created inside the test transaction and rolled back
afterwards; the real 'SMS' row of odoo_dev is never touched. The gateway HTTP
call is mocked, no real SMS is sent.
"""
import os
from unittest.mock import MagicMock, patch

import requests

from odoo.tests.common import TransactionCase

POST = "odoo.addons.bunna_helpdesk.models.cbs_sms_service.requests.post"
TEST_ENV = "SMS_TEST"
URL_1 = "http://sms-gateway.test.invalid/sms"
URL_2 = "http://sms-gateway-changed.test.invalid/send"


def _ok_response(status=200, payload=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {"status": "success"}
    resp.text = "ok"
    return resp


class TestSmsEmailNotifications(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cr = cls.env.cr
        # table may not exist in a fresh test DB; it exists in odoo_dev (IF NOT EXISTS keeps it)
        cr.execute(
            """CREATE TABLE IF NOT EXISTS cbs_integration (
                   username varchar, password varchar, endpoint varchar,
                   environment varchar, status varchar)"""
        )
        cr.execute(
            "INSERT INTO cbs_integration (username, password, endpoint, environment, status) "
            "VALUES (%s, %s, %s, %s, 'true')",
            ("test_user", "test_secret_pw", URL_1, TEST_ENV),
        )
        cls.env["ir.config_parameter"].sudo().set_param("bunna_helpdesk.sms_environment", TEST_ENV)
        # make sure the Settings screen values do not override the test table row
        cls.env["ir.config_parameter"].sudo().set_param("bunna_helpdesk.sms_endpoint", "")
        cls.stage_new = cls.env.ref("bunna_helpdesk.helpdesk_ticket_stage_new")
        cls.stage_progress = cls.env.ref("bunna_helpdesk.helpdesk_ticket_stage_in_progress")
        cls.stage_done = cls.env.ref("bunna_helpdesk.helpdesk_ticket_stage_done")

    def _ticket(self, phone="0911223344", email="customer@example.com"):
        partner = self.env["res.partner"].create(
            {"name": "Test Customer", "phone": phone or False, "email": email or False}
        )
        return self.env["helpdesk.ticket"].create({
            "name": "Test request",
            "description": "<p>Test</p>",
            "partner_id": partner.id,
            "partner_phone": phone or False,
            "stage_id": self.stage_new.id,
        })

    def _emails(self, ticket, word):
        return self.env["mail.mail"].search(
            [("subject", "ilike", "Service Request %s %s" % (ticket.number, word))]
        )

    # TEST 1: Manual Accept SMS and Email
    def test_01_accept_sms_and_email(self):
        ticket = self._ticket()
        # Changing stage alone must NOT send automatic notification
        with patch(POST, return_value=_ok_response()) as post:
            ticket.write({"stage_id": self.stage_progress.id})
        self.assertEqual(ticket.stage_id, self.stage_progress)
        post.assert_not_called()
        self.assertFalse(ticket.acceptance_sms_sent)

        # Explicit header action sends SMS
        ticket.header_action = "accept"
        ticket.header_channel = "sms"
        with patch(POST, return_value=_ok_response()) as post:
            ticket.action_execute_header_notification()
        self.assertEqual(post.call_count, 1)
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["url"], URL_1)
        self.assertEqual(kwargs["auth"], ("test_user", "test_secret_pw"))
        self.assertIn("2519" + "11223344", kwargs["data"])
        self.assertIn(ticket.number, kwargs["data"])
        self.assertIn("accepted", kwargs["data"])
        self.assertTrue(ticket.acceptance_sms_sent)
        self.assertTrue(ticket.acceptance_email_sent)
        self.assertEqual(ticket.acceptance_sent_channel, "sms")

    # TEST 2: No mobile number
    def test_02_no_mobile(self):
        ticket = self._ticket(phone=False)
        ticket.write({"stage_id": self.stage_progress.id})
        with patch(POST, return_value=_ok_response()) as post:
            ticket.action_accept_ticket_channel()
        post.assert_not_called()
        self.assertFalse(ticket.acceptance_sms_sent)

    # TEST 3: Accept via Email
    def test_03_accept_via_email(self):
        ticket = self._ticket()
        ticket.acceptance_channel = "email"
        with patch(POST, return_value=_ok_response()) as post:
            ticket.action_accept_ticket_channel()
        post.assert_not_called()
        self.assertTrue(ticket.acceptance_email_sent)
        self.assertTrue(ticket.acceptance_sms_sent)
        self.assertEqual(ticket.acceptance_sent_channel, "email")
        self.assertEqual(len(self._emails(ticket, "Accepted")), 1)

    # TEST 4: Gateway down during manual send
    def test_04_gateway_down(self):
        ticket = self._ticket()
        ticket.write({"stage_id": self.stage_progress.id})
        with patch(POST, side_effect=requests.exceptions.ConnectionError("boom")), \
                self.assertLogs("odoo.addons.bunna_helpdesk.models.cbs_sms_service", "ERROR") as logs:
            ticket.action_send_acceptance_sms()
        self.assertFalse(ticket.acceptance_sms_sent)
        self.assertNotIn("test_secret_pw", "\n".join(logs.output))

    def test_04b_http_error_and_bad_response(self):
        svc = self.env["bunna.sms.service"]
        with patch(POST, return_value=_ok_response(500)):
            self.assertFalse(svc.send_sms("0911223344", "x", TEST_ENV)["success"])
        with patch(POST, return_value=_ok_response(200, {"status": "failed", "message": "bad"})):
            self.assertFalse(svc.send_sms("0911223344", "x", TEST_ENV)["success"])
        with patch(POST, side_effect=requests.exceptions.Timeout()):
            self.assertFalse(svc.send_sms("0911223344", "x", TEST_ENV)["success"])

    def test_04c_config_missing(self):
        res = self.env["bunna.sms.service"].send_sms("0911223344", "x", "NO_SUCH_ENV")
        self.assertFalse(res["success"])
        self.assertIn("cbs_integration", res["detail"])

    # TEST 5 + TEST 6: Done stage and manual completion notification
    def test_05_06_completion_manual_after_done(self):
        ticket = self._ticket()
        with patch(POST, return_value=_ok_response()) as post:
            # Stage transitions do NOT automatically send
            ticket.write({"stage_id": self.stage_progress.id})
            ticket.write({"stage_id": self.stage_done.id})
            post.assert_not_called()
            self.assertFalse(ticket.completion_sms_sent)

            # Manual Done SMS notification
            ticket.header_action = "done"
            ticket.header_channel = "sms"
            ticket.action_execute_header_notification()
            self.assertEqual(post.call_count, 1)
            self.assertIn("completed", post.call_args.kwargs["data"])
            self.assertTrue(ticket.completion_sms_sent and ticket.completion_email_sent)
            self.assertEqual(ticket.done_sent_channel, "sms")

            # Unrelated edits after completion send nothing
            ticket.write({"name": "renamed", "priority": "1"})
            ticket.write({"stage_id": self.stage_done.id})
            self.assertEqual(post.call_count, 1)

    def test_06b_unrelated_update_after_accept(self):
        ticket = self._ticket()
        with patch(POST, return_value=_ok_response()) as post:
            ticket.write({"stage_id": self.stage_progress.id})
            ticket.write({"name": "other"})
        post.assert_not_called()

    def test_09_manual_retry(self):
        ticket = self._ticket()
        ticket.write({"stage_id": self.stage_progress.id})
        with patch(POST, side_effect=requests.exceptions.Timeout()):
            ticket.action_send_acceptance_sms()
        self.assertFalse(ticket.acceptance_sms_sent)
        with patch(POST, return_value=_ok_response()) as post:
            ticket.action_send_acceptance_sms()
        self.assertEqual(post.call_count, 1)
        self.assertTrue(ticket.acceptance_sms_sent)

    # TEST 7
    def test_07_no_credentials_in_source(self):
        root = os.path.dirname(os.path.dirname(__file__))
        this = os.path.abspath(__file__)
        for folder, _dirs, files in os.walk(root):
            for fname in files:
                path = os.path.join(folder, fname)
                if path == this or not fname.endswith((".py", ".xml", ".js", ".csv", ".md")):
                    continue
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                self.assertNotIn("10.1.13.217", content, path)
                self.assertNotIn("8089/sms", content, path)

    # TEST 8
    def test_08_endpoint_change_is_picked_up(self):
        svc = self.env["bunna.sms.service"]
        with patch(POST, return_value=_ok_response()) as post:
            svc.send_sms("0911223344", "hello", TEST_ENV)
            self.assertEqual(post.call_args.kwargs["url"], URL_1)
            self.env.cr.execute(
                "UPDATE cbs_integration SET endpoint = %s WHERE environment = %s", (URL_2, TEST_ENV))
            svc.send_sms("0911223344", "hello", TEST_ENV)
            self.assertEqual(post.call_args.kwargs["url"], URL_2)

    def test_10_mobile_normalisation(self):
        n = self.env["bunna.sms.service"].normalize_mobile
        self.assertEqual(n("0911223344"), "251911223344")
        self.assertEqual(n("+251 91 122 3344"), "251911223344")
        self.assertEqual(n("911223344"), "251911223344")
        self.assertEqual(n("0711223344"), "251711223344")
        self.assertFalse(n("12345"))
        self.assertFalse(n(False))

    # TEST 11: ticket phone / email win over the customer record
    def test_11_ticket_contact_has_priority(self):
        ticket = self._ticket(phone="0911223344", email="partner@example.com")
        ticket.write({"partner_phone": "0922334455", "partner_email": "ticket@example.com"})
        with patch(POST, return_value=_ok_response()) as post:
            ticket.action_send_acceptance_sms()
        self.assertIn("251922334455", post.call_args.kwargs["data"])

    # TEST 12: invalid ticket phone falls back to the customer's valid mobile
    def test_12_invalid_ticket_phone_falls_back(self):
        ticket = self._ticket(phone="0911223344")
        ticket.write({"partner_phone": "12345"})
        with patch(POST, return_value=_ok_response()) as post:
            ticket.action_send_acceptance_sms()
        self.assertEqual(post.call_count, 1)
        self.assertIn("251911223344", post.call_args.kwargs["data"])
        self.assertTrue(ticket.acceptance_sms_sent)

    # TEST 13: manual completion email on Done
    def test_13_done_manual_email(self):
        ticket = self._ticket()
        ticket.write({"stage_id": self.stage_done.id})
        ticket.done_channel = "email"
        ticket.action_done_ticket_channel()
        self.assertEqual(len(self._emails(ticket, "Completed")), 1)

    # TEST 14: URL from Settings overrides the table endpoint, credentials stay from the table
    def test_14_settings_url_overrides_table_endpoint(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "bunna_helpdesk.sms_endpoint", "http://from-settings.test.invalid/send")
        ticket = self._ticket()
        with patch(POST, return_value=_ok_response()) as post:
            ticket.action_send_acceptance_sms()
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["url"], "http://from-settings.test.invalid/send")
        self.assertEqual(kwargs["auth"], ("test_user", "test_secret_pw"))

    # TEST 15: with an empty Settings URL the table endpoint is used
    def test_15_table_endpoint_when_setting_empty(self):
        self.env["ir.config_parameter"].sudo().set_param("bunna_helpdesk.sms_endpoint", "")
        ticket = self._ticket()
        with patch(POST, return_value=_ok_response()) as post:
            ticket.action_send_acceptance_sms()
        self.assertEqual(post.call_args.kwargs["url"], URL_1)
        self.assertEqual(post.call_args.kwargs["auth"], ("test_user", "test_secret_pw"))

    # TEST 16: pgcrypto cbs_encode / cbs_decode on encrypted cbs_integration password
    def test_16_pgcrypto_encode_decode_credentials(self):
        cr = self.env.cr
        # Create row in cbs_integration: username and endpoint plain, password encrypted
        cr.execute(
            """
            INSERT INTO cbs_integration (username, password, endpoint, environment, status)
            VALUES ('pgp_user', cbs_encode('pgp_secret_pw'), %s, 'PGP_TEST', 'true')
            """,
            (URL_1,)
        )
        conf = self.env["cbs.integration.config"].get_config("PGP_TEST")
        self.assertTrue(conf, "Config row should be found and password decrypted")
        self.assertEqual(conf["username"], "pgp_user")
        self.assertEqual(conf["password"], "pgp_secret_pw")
        self.assertEqual(conf["endpoint"], URL_1)
