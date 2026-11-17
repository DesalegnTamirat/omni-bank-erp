# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestChatbotTicket(TransactionCase):

    def _service(self):
        return self.env["helpdesk.social.channel"]

    def test_01_ticket_created_with_chatbot_channel(self):
        ticket = self._service().process_chatbot_request(
            {
                "subject": "Cannot log in to mobile banking",
                "description": "I get an error after entering my PIN",
                "full_name": "Chatbot Customer",
                "email": "chatbot.customer@example.com",
                "phone": "0911000111",
                "session_id": "test-session-1",
            }
        )
        self.assertTrue(ticket)
        self.assertEqual(ticket.channel_type, "chatbot")
        self.assertEqual(ticket.social_chat_id, "test-session-1")
        self.assertTrue(ticket.partner_id)
        self.assertEqual(ticket.partner_id.email, "chatbot.customer@example.com")
        self.assertIn("mobile banking", ticket.name)

    def test_02_same_session_does_not_duplicate(self):
        data = {"subject": "Card blocked", "session_id": "test-session-2"}
        first = self._service().process_chatbot_request(data)
        second = self._service().process_chatbot_request(data)
        self.assertEqual(first, second)

    def test_03_empty_request_creates_nothing(self):
        self.assertFalse(self._service().process_chatbot_request({}))

    def test_04_settings_team_is_applied(self):
        team = self.env["helpdesk.ticket.team"].create({"name": "Chatbot Team"})
        self.env["ir.config_parameter"].sudo().set_param("bunna_helpdesk.chatbot_team_id", str(team.id))
        ticket = self._service().process_chatbot_request(
            {"subject": "Statement request", "session_id": "test-session-4"}
        )
        self.assertEqual(ticket.team_id, team)

    def test_05_html_is_escaped(self):
        ticket = self._service().process_chatbot_request(
            {"description": "<script>alert(1)</script>", "session_id": "test-session-5"}
        )
        self.assertNotIn("<script>", ticket.description)
