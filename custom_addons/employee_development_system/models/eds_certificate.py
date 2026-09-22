# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class EdsCertificateRule(models.Model):
    _name = 'eds.certificate.rule'
    _description = 'EDS Certification Policy / Rule'
    _inherit = ['mail.thread']

    name = fields.Char(string='Rule Name', required=True)
    category = fields.Selection([
        ('developmental', 'Developmental'),
        ('values_ethics', 'Values & Ethics'),
        ('technical_compliance', 'Technical & Compliance'),
    ], string='Course Category Target', required=True)
    require_attendance = fields.Boolean(string='Require Attendance Minimum', default=True)
    min_attendance_pct = fields.Float(string='Minimum Attendance (%)', default=80.0)
    require_level2_pass = fields.Boolean(string='Require Level 2 Post-Assessment Pass', default=True)
    min_level2_score = fields.Float(string='Minimum Level 2 Score (%)', default=60.0)
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Policy Notes')

class EdsCertificate(models.Model):
    _name = 'eds.certificate'
    _description = 'EDS Training Completion Certificate'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    code = fields.Char(string='Certificate Number', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True, tracking=True)
    session_id = fields.Many2one('eds.session', string='Training Session', required=True, ondelete='cascade', tracking=True)
    course_id = fields.Many2one('eds.course', related='session_id.course_id', string='Course', store=True)
    issue_date = fields.Date(string='Issue Date', default=fields.Date.context_today, required=True, tracking=True)
    is_eligible = fields.Boolean(string='Eligible for Certification', compute='_compute_eligibility', store=True)
    eligibility_reason = fields.Text(string='Eligibility Details', compute='_compute_eligibility', store=True)
    file = fields.Binary(string='Certificate File (PDF)', attachment=True)
    file_name = fields.Char(string='File Name')
    issued_by = fields.Many2one('res.users', string='Issued By', default=lambda self: self.env.user)
    state = fields.Selection([
        ('pending', 'Pending Eligibility Check'),
        ('issued', 'Issued'),
        ('void', 'Voided'),
    ], string='Status', default='pending', required=True, tracking=True)

    @api.constrains('session_id', 'employee_id')
    def _check_unique_session_emp_cert(self):
        for rec in self:
            if rec.session_id and rec.employee_id:
                domain = [('session_id', '=', rec.session_id.id), ('employee_id', '=', rec.employee_id.id), ('id', '!=', rec.id)]
                if self.search_count(domain) > 0:
                    raise ValidationError(_("A certificate record already exists for participant %s in session %s.") % (
                        rec.employee_id.name, rec.session_id.name
                    ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].sudo().next_by_code('eds.certificate') or _('New')
        return super(EdsCertificate, self).create(vals_list)

    @api.depends('session_id', 'employee_id')
    def _compute_eligibility(self):
        for rec in self:
            if not rec.session_id or not rec.employee_id:
                rec.is_eligible = False
                rec.eligibility_reason = _("Missing session or participant data.")
                continue

            # Fetch matching rule
            category = rec.course_id.category if rec.course_id else 'developmental'
            rule = self.env['eds.certificate.rule'].search([('category', '=', category), ('active', '=', True)], limit=1)
            min_att = rule.min_attendance_pct if rule else 80.0
            req_l2 = rule.require_level2_pass if rule else True
            min_l2 = rule.min_level2_score if rule else 60.0

            # Calculate session attendance %
            attendance = self.env['eds.session.attendance'].search([
                ('session_id', '=', rec.session_id.id),
                ('employee_id', '=', rec.employee_id.id)
            ], limit=1)
            att_pct = attendance.attendance_percentage if attendance else (100.0 if attendance and attendance.attended else 0.0)

            # Calculate level 2 post-assessment pass
            l2_eval = self.env['eds.evaluation.level2'].search([
                ('session_id', '=', rec.session_id.id),
                ('employee_id', '=', rec.employee_id.id)
            ], limit=1)
            l2_passed = l2_eval.passed if l2_eval else False
            post_score = l2_eval.post_score if l2_eval else 0.0

            reasons = []
            eligible = True

            if att_pct < min_att:
                eligible = False
                reasons.append(_("Attendance %.1f%% below required %.1f%%.") % (att_pct, min_att))
            else:
                reasons.append(_("Attendance %.1f%% meets requirement (≥%.1f%%).") % (att_pct, min_att))

            if req_l2:
                if not l2_eval or post_score < min_l2:
                    eligible = False
                    reasons.append(_("Level 2 post-assessment score %.1f%% below required %.1f%%.") % (post_score, min_l2))
                else:
                    reasons.append(_("Level 2 score %.1f%% passed (≥%.1f%%).") % (post_score, min_l2))

            rec.is_eligible = eligible
            rec.eligibility_reason = "\n".join(reasons)

    def action_issue(self):
        for rec in self:
            rec._compute_eligibility()
            if not rec.is_eligible:
                raise ValidationError(_("Cannot issue certificate: participant is not eligible.\n%s") % rec.eligibility_reason)
            rec.state = 'issued'
            rec.issue_date = fields.Date.context_today(self)
            rec.message_post(body=_("Certificate %s successfully issued to %s.") % (rec.code, rec.employee_id.name))

    def action_void(self):
        for rec in self:
            rec.state = 'void'
            rec.message_post(body=_("Certificate %s voided.") % rec.code)
