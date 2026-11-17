# -*- coding: utf-8 -*-
import logging
import re
from markupsafe import Markup
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


def resolve_cc_manager_and_partner(env, unit_str, candidate_emp=None, target_ou=None):
    """
    Given a work unit / department / district name string from a letter's CC lines,
    resolves the corresponding manager hr.employee record, their official work_email,
    their res.users record, and their res.partner record.
    """
    if not unit_str or not isinstance(unit_str, str):
        return None
    unit_clean = unit_str.strip()
    if unit_clean.lower() in [
        'bunna bank s.c', 'bunna bank s.c.', 'bunna bank', 'head office',
        'bunna bank share company', 'respective chief offices', 'respective work units'
    ]:
        return None

    # 1. Candidate's own coach / manager if CC unit matches candidate's current work unit
    if candidate_emp:
        cand_unit = (
            getattr(candidate_emp, 'default_operating_unit_id', False) and candidate_emp.default_operating_unit_id.name or ''
        )
        if cand_unit and (cand_unit.lower() in unit_clean.lower() or unit_clean.lower() in cand_unit.lower()):
            mgr = candidate_emp.parent_id or candidate_emp.coach_id
            if mgr and (mgr.work_email or mgr.user_id):
                return _build_manager_dict(mgr)

    # 2. Target Operating Unit manager if CC unit matches target work unit
    if target_ou and hasattr(target_ou, 'name') and target_ou.name:
        if target_ou.name.lower() in unit_clean.lower() or unit_clean.lower() in target_ou.name.lower():
            if getattr(target_ou, 'manager_id', False) and target_ou.manager_id:
                return _build_manager_dict(target_ou.manager_id)

    # 3. Direct Operating Unit lookup
    OU = env['operating.unit'].sudo()
    ou = OU.search([('name', '=ilike', unit_clean)], limit=1)
    if not ou:
        ou = OU.search([('name', 'ilike', unit_clean)], limit=1)
    if not ou:
        short_name = re.sub(r'\s+(Directorate|Office|Branch|District)$', '', unit_clean, flags=re.IGNORECASE).strip()
        if len(short_name) >= 3:
            ou = OU.search([('name', 'ilike', short_name)], limit=1)

    if ou:
        if ou.manager_id:
            return _build_manager_dict(ou.manager_id)
        # Search director/manager employee inside this OU
        emps = env['hr.employee'].sudo().search([('default_operating_unit_id', '=', ou.id)])
        for e in emps:
            job = (e.job_position.name if hasattr(e, 'job_position') and e.job_position else getattr(e, 'job_name', False) or '')
            if any(w in str(job).lower() for w in ['director', 'manager', 'head']):
                return _build_manager_dict(e)
        if emps:
            parents = emps.mapped('parent_id').filtered(lambda p: bool(p.work_email or p.user_id))
            if parents:
                return _build_manager_dict(parents[0])

    # 4. Search hr.department
    Dept = env['hr.department'].sudo()
    dept = Dept.search([('name', 'ilike', unit_clean)], limit=1)
    if dept and dept.manager_id:
        return _build_manager_dict(dept.manager_id)
    if dept:
        dept_emps = env['hr.employee'].sudo().search([('department_id', '=', dept.id)])
        for e in dept_emps:
            job = (e.job_position.name if hasattr(e, 'job_position') and e.job_position else getattr(e, 'job_name', False) or '')
            if any(w in str(job).lower() for w in ['director', 'manager', 'head']):
                return _build_manager_dict(e)

    return None


def _build_manager_dict(mgr):
    work_email = (mgr.work_email or (mgr.user_id.email if mgr.user_id else False) or '').strip()
    partner = mgr.user_id.partner_id if mgr.user_id and mgr.user_id.partner_id else mgr.address_home_id
    if not partner and work_email:
        partner = mgr.env['res.partner'].sudo().search([('email', '=ilike', work_email)], limit=1)
    return {
        'employee': mgr,
        'name': mgr.name,
        'work_email': work_email,
        'user': mgr.user_id if mgr.user_id else False,
        'partner': partner or False,
    }


def strip_html_tags(html_text):
    """
    Strips HTML tags and converts markup to clean, readable plain text for notifications and Discuss.
    Converts <br>, <p>, <div>, <li> to clean newlines and removes all remaining tags.
    """
    if not html_text:
        return ""
    text = str(html_text)
    # Convert line breaks and paragraph ends to newlines
    text = re.sub(r'<\s*br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</\s*(p|div|li|tr|h[1-6])\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*(p|div|li|tr|h[1-6])[^>]*>', '', text, flags=re.IGNORECASE)
    # Remove all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode common HTML entities
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
    # Clean up excess consecutive blank lines while preserving line structure
    lines = [line.strip() for line in text.split('\n')]
    cleaned = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                cleaned.append('')
                prev_empty = True
        else:
            cleaned.append(line)
            prev_empty = False
    return '\n'.join(cleaned).strip()


def dispatch_letter_cc_notifications(record, cc_lines, letter_title, letter_subject, details_html, attachment_ids=None, candidate_emp=None, target_ou=None):
    """
    Dispatches both Discuss (Inbox notification, Direct Message & Chatter mention) and Email (to manager's work_email)
    to the respective managers of every operating unit / department listed in cc_lines.
    """
    env = record.env
    mail_server = env['ir.mail_server'].sudo().search([('active', '=', True)], order='sequence, id', limit=1)
    cfg_from = env['ir.config_parameter'].sudo().get_param('mail.default.from')
    sender_email = (cfg_from or (mail_server.smtp_user if mail_server else False) or 'natnael.negussie@bunnabanksc.com').strip()
    sender_formatted = f'"Bunna Bank Recruitment" <{sender_email}>'

    # Determine thread record that supports chatter
    thread_record = None
    if hasattr(record, 'message_post'):
        thread_record = record
    elif hasattr(record, 'new_int_sel_cand') and record.new_int_sel_cand and hasattr(record.new_int_sel_cand, 'message_post'):
        thread_record = record.new_int_sel_cand
    elif hasattr(record, 'emp_name') and record.emp_name and hasattr(record.emp_name, 'message_post'):
        thread_record = record.emp_name
    elif hasattr(record, 'vacancy_id') and record.vacancy_id and hasattr(record.vacancy_id, 'message_post'):
        thread_record = record.vacancy_id

    notified_emails = set()
    notified_partners = env['res.partner']
    results = []

    for cc_line in cc_lines:
        mgr_data = resolve_cc_manager_and_partner(env, cc_line, candidate_emp=candidate_emp, target_ou=target_ou)
        if not mgr_data:
            _logger.info("Could not resolve CC manager for line: %s", cc_line)
            continue

        mgr_name = mgr_data['name']
        work_email = mgr_data['work_email']
        partner = mgr_data['partner']

        # Ensure partner exists for Discuss delivery if we have work_email
        if not partner and work_email:
            partner = env['res.partner'].sudo().create({
                'name': mgr_name,
                'email': work_email,
            })
            mgr_data['partner'] = partner

        # 1. Send Email to Manager's Official Work Email
        if work_email and work_email.lower() not in notified_emails:
            notified_emails.add(work_email.lower())
            email_body = (
                f"<div style='font-family: Arial, sans-serif; font-size: 14px; color: #222222; line-height: 1.6; max-width: 650px;'>"
                f"<p>Dear <strong>{mgr_name}</strong>,</p>"
                f"<p>Please be informed that your work unit / directorate <b>{cc_line}</b> has been placed in <b>CC</b> "
                f"on the official <strong>{letter_title}</strong> issued by Bunna Bank S.C.</p>"
                f"<div style='background-color: #f8f9fa; border-left: 4px solid #4A2E1A; padding: 12px; margin: 15px 0;'>"
                f"{details_html}"
                f"</div>"
                f"<p>Please find attached the official copy of the letter for your information, records, and necessary action.</p>"
                f"<br/>"
                f"<p style='margin-bottom: 2px;'>Sincerely yours,</p>"
                f"<strong>{env.user.name or 'Human Resources Management'}</strong><br/>"
                f"<strong>Bunna Bank S.C.</strong>"
                f"</div>"
            )

            mail_vals = {
                'subject': f"[CC Notice] {letter_subject} - {cc_line}",
                'body_html': email_body,
                'email_from': sender_formatted,
                'email_to': work_email,
                'reply_to': sender_formatted,
                'mail_server_id': mail_server.id if mail_server else False,
                'attachment_ids': [(6, 0, attachment_ids)] if attachment_ids else [],
            }
            try:
                mail = env['mail.mail'].sudo().create(mail_vals)
                mail.send()
                results.append(f"{mgr_name} ({work_email})")
            except Exception as e:
                _logger.warning("Failed to dispatch CC email to %s: %s", work_email, e)

        # 2. Discuss Notification (Direct Message & Inbox Notification)
        if partner:
            notified_partners |= partner
            details_clean = strip_html_tags(details_html)
            cc_line_clean = strip_html_tags(cc_line)
            letter_title_clean = strip_html_tags(letter_title)
            discuss_body = (
                f"📌 CC Notification: {letter_title_clean}\n\n"
                f"Dear {mgr_name} (Manager of {cc_line_clean}),\n\n"
                f"You are copied on the official {letter_title_clean}.\n\n"
                f"{details_clean}\n\n"
                f"Please review the attached official letter."
            )

            # 2a. Post 1-on-1 Discuss Direct Message (DM) to manager
            if 'discuss.channel' in env and partner.id != env.user.partner_id.id:
                try:
                    chat_channel = env['discuss.channel'].sudo()._get_or_create_chat(
                        partners_to=[env.user.partner_id.id, partner.id]
                    )
                    if chat_channel:
                        dm_msg = chat_channel.sudo().message_post(
                            body=discuss_body,
                            subject=f"[CC Notification] {letter_subject}",
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment',
                            attachment_ids=attachment_ids or [],
                        )
                        dm_notifs = env['mail.notification'].sudo().search([
                            ('mail_message_id', '=', dm_msg.id),
                            ('res_partner_id', '=', partner.id),
                        ])
                        if dm_notifs:
                            dm_notifs.write({
                                'notification_type': 'inbox',
                                'notification_status': 'sent',
                                'is_read': False,
                            })
                except Exception as dm_err:
                    _logger.warning("Could not dispatch Discuss DM to partner %s: %s", partner.id, dm_err)

            # 2b. Notify on thread record if available
            if thread_record:
                try:
                    if hasattr(thread_record, 'message_notify'):
                        notif_msg = thread_record.sudo().message_notify(
                            partner_ids=[partner.id],
                            subject=f"[CC Notification] {letter_subject}",
                            body=discuss_body,
                            email_from=sender_formatted,
                            email_layout_xmlid="mail.mail_notification_light",
                        )
                        if notif_msg:
                            notifs = env['mail.notification'].sudo().search([
                                ('mail_message_id', '=', notif_msg.id),
                                ('res_partner_id', '=', partner.id),
                            ])
                            if notifs:
                                notifs.write({
                                    'notification_type': 'inbox',
                                    'notification_status': 'sent',
                                })
                except Exception as notif_err:
                    _logger.warning("Could not message_notify partner %s: %s", partner.id, notif_err)

    # 3. Post summary in record chatter with @mentions
    if thread_record and notified_partners:
        mentions = " ".join([f'<a href="#" data-oe-model="res.partner" data-oe-id="{p.id}">@{p.name}</a>' for p in notified_partners])
        chatter_summary = (
            f"<p><b>📬 Letter Dispatched &amp; CC Notifications Sent</b></p>"
            f"<p>Official {letter_title} has been sent to the recipient, and CC notifications have been delivered via Discuss Inbox and work email to CC Managers: {mentions}.</p>"
        )
        try:
            thread_record.sudo().message_post(
                body=Markup(chatter_summary),
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                attachment_ids=attachment_ids or [],
            )
        except Exception as e:
            _logger.warning("Failed to post chatter CC summary: %s", e)

    return results
