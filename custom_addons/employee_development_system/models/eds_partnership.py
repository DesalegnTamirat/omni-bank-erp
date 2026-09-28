# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class EdsLearningPartnership(models.Model):
    """Learning partnership & institutional MoU management (FREDS069 - FREDS072)."""
    _name = 'eds.learning.partnership'
    _description = 'Learning Partnership & MoU'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'
    _rec_name = 'partner_name'

    partner_name = fields.Char(string='Partner Institution / Organization', required=True, tracking=True)
    partner_type = fields.Selection([
        ('university', 'University / Academic Institution'),
        ('professional_body', 'Professional Institute / Certification Body'),
        ('tech_vendor', 'Technology / Solution Vendor'),
        ('consultancy', 'Specialized Training Consultancy'),
        ('banking_institute', 'Banking / Financial Training Academy'),
    ], string='Institution Type', default='banking_institute', required=True, tracking=True)
    mou_reference = fields.Char(string='MoU / Agreement Reference Number', tracking=True)
    contact_person = fields.Char(string='Partner Contact Person')
    contact_email = fields.Char(string='Email')
    contact_phone = fields.Char(string='Phone')
    country_id = fields.Many2one('res.country', string='Country')
    start_date = fields.Date(string='Agreement Start Date', required=True, tracking=True)
    end_date = fields.Date(string='Agreement Expiry Date', tracking=True)
    scope_of_partnership = fields.Text(string='Scope of Partnership & Cooperation')
    mou_document = fields.Binary(string='Signed MoU Document (PDF)', attachment=True)
    mou_document_name = fields.Char(string='Filename')
    performance_rating = fields.Selection([
        ('5', '5 - Strategic Value & High Satisfaction'),
        ('4', '4 - Very Good Collaboration'),
        ('3', '3 - Satisfactory Delivery'),
        ('2', '2 - Needs Attention'),
        ('1', '1 - Underperforming'),
    ], string='Partnership Performance Rating', default='4', tracking=True)
    state = fields.Selection([
        ('draft', 'Exploratory / Draft MoU'),
        ('active', 'Active Partnership'),
        ('expired', 'Expired'),
        ('terminated', 'Terminated'),
    ], string='Status', default='draft', required=True, tracking=True)
    notes = fields.Text(string='Review Notes & Next Steps')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    def action_activate(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'draft':
                raise UserError(_('Only draft partnership agreements can be activated.'))
            rec.state = 'active'
            rec.message_post(body=_("Partnership with '%s' is now active.") % rec.partner_name)

    def action_expire(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'active':
                raise UserError(_('Only active partnerships can be expired.'))
            rec.state = 'expired'
            rec.message_post(body=_("Partnership agreement expired."))

    def action_terminate(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state not in ('draft', 'active'):
                raise UserError(_('Only draft or active partnerships can be terminated.'))
            rec.state = 'terminated'
            rec.message_post(body=_("Partnership terminated."))
