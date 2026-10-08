# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrEmployeeChangeRequest(models.Model):
    """
    EM-067 to EM-075: Employee Master Data Change Request.
    Handles submission, validation, document verification, multi-stage approval,
    automated employee update, audit logging, and notifications.
    """
    _name = 'hr.employee.change.request'
    _description = 'Employee Master Data Change Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'

    name = fields.Char(
        string='Request Number',
        required=True,
        readonly=True,
        default=lambda self: _('New'),
        copy=False,
        tracking=True
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True
    )
    job_id = fields.Many2one(related='employee_id.job_id', string='Job Position', readonly=True)
    department_id = fields.Many2one(related='employee_id.department_id', string='Department', readonly=True)
    
    requested_by_id = fields.Many2one(
        'res.users',
        string='Requester',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True
    )
    request_date = fields.Datetime(
        string='Request Date',
        required=True,
        default=fields.Datetime.now,
        readonly=True
    )
    
    reviewed_by_id = fields.Many2one('res.users', string='Reviewed By', readonly=True, copy=False)
    review_date = fields.Datetime(string='Review Date', readonly=True, copy=False)
    
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approval_date = fields.Datetime(string='Approval Date', readonly=True, copy=False)
    
    rejected_by_id = fields.Many2one('res.users', string='Rejected By', readonly=True, copy=False)
    rejection_date = fields.Datetime(string='Rejection Date', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', copy=False, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, tracking=True)

    line_ids = fields.One2many(
        'hr.employee.change.request.line',
        'request_id',
        string='Field Changes',
        copy=True
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'hr_employee_change_req_rel',
        'request_id',
        'attachment_id',
        string='Supporting Documents',
        help="Upload required supporting legal or evidence documents (e.g. Legal Name Change document, Degree Certificate, Marriage Certificate)."
    )
    attachment_count = fields.Integer(string='Attachments', compute='_compute_attachment_count')
    requires_attachment_notice = fields.Text(string='Required Documents Notice', compute='_compute_requires_attachment_notice')

    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec.attachment_ids)

    @api.depends('line_ids', 'line_ids.requires_attachment')
    def _compute_requires_attachment_notice(self):
        for rec in self:
            required_lines = rec.line_ids.filtered(lambda l: l.requires_attachment)
            if required_lines:
                field_names = [l.field_description for l in required_lines if l.field_description]
                rec.requires_attachment_notice = _("Supporting documents required for: %s") % ", ".join(field_names)
            else:
                rec.requires_attachment_notice = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.employee.change.request') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        """ EM-069 & EM-071: Validate document requirement and submit for review. """
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_("Please add at least one field change line before submitting."))

            # EM-069: Check mandatory document attachments
            required_lines = rec.line_ids.filtered(lambda l: l.requires_attachment)
            if required_lines and not rec.attachment_ids:
                missing_fields = ", ".join(required_lines.mapped('field_description'))
                raise ValidationError(_(
                    "Supporting document attachment is mandatory for the following requested changes: %s.\n\n"
                    "Please upload the required supporting evidence document under 'Supporting Documents' before submitting."
                ) % missing_fields)

            # Validation for Divorced marital status transition: former_spouse_name requirement
            divorce_line = rec.line_ids.filtered(lambda l: l.field_name == 'marital' and (l.new_value_selection == 'divorced' or l.new_value == 'Divorced'))
            if divorce_line:
                former_spouse_line = rec.line_ids.filtered(lambda l: l.field_name == 'former_spouse_name' and (l.new_value or l.new_value_selection))
                current_former_spouse = rec.employee_id.former_spouse_name
                if not former_spouse_line and not current_former_spouse:
                    raise ValidationError(_(
                        "When changing Marital Status to 'Divorced', you must also provide the Former Spouse Name.\n"
                        "Please add a change line for 'Former Spouse Name'."
                    ))

            rec.write({
                'state': 'submitted',
            })
            rec._notify_state_change('submitted')

    def action_review(self):
        """ EM-071: Mark request as reviewed by HR Officer. """
        for rec in self:
            rec.write({
                'state': 'under_review',
                'reviewed_by_id': self.env.user.id,
                'review_date': fields.Datetime.now(),
            })
            rec._notify_state_change('under_review')

    def action_approve(self):
        """
        EM-071, EM-073, EM-074, EM-075:
        Approve request, write changes directly to hr.employee, log audit history, and notify user.
        """
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_("No change lines found to approve."))

            # 1. Update Employee Record fields
            emp = rec.employee_id
            values_to_write = {}
            for line in rec.line_ids:
                f_name = line.field_name
                if not f_name:
                    continue
                
                # Format string value back into field type if needed
                field_obj = emp._fields.get(f_name)
                if not field_obj:
                    continue

                raw_val = line.new_value_selection if (line.is_selection and line.new_value_selection) else line.new_value
                casted_val = raw_val

                if field_obj.type == 'selection':
                    sel_options = []
                    if hasattr(field_obj, 'selection'):
                        sel = field_obj.selection
                        if callable(sel):
                            sel_options = sel(emp)
                        elif isinstance(sel, list):
                            sel_options = sel
                    dict_options = dict(sel_options)
                    rev_dict = {v: k for k, v in dict_options.items()}
                    if raw_val in dict_options:
                        casted_val = raw_val
                    elif raw_val in rev_dict:
                        casted_val = rev_dict[raw_val]
                elif field_obj.type == 'boolean':
                    casted_val = raw_val.lower() in ('true', '1', 'yes', 't') if raw_val else False
                elif field_obj.type == 'integer':
                    casted_val = int(raw_val) if raw_val else 0
                elif field_obj.type == 'float':
                    casted_val = float(raw_val) if raw_val else 0.0
                elif field_obj.type in ('date', 'datetime'):
                    casted_val = raw_val if raw_val else False
                elif field_obj.type == 'many2one':
                    if raw_val and raw_val.isdigit():
                        casted_val = int(raw_val)
                    else:
                        casted_val = False

                values_to_write[f_name] = casted_val

            # Auto-handle marital status transition to divorced
            if values_to_write.get('marital') == 'divorced':
                values_to_write['is_previously_married'] = True
                if emp.spouse_complete_name and not emp.former_spouse_name and 'former_spouse_name' not in values_to_write:
                    values_to_write['former_spouse_name'] = emp.spouse_complete_name

            if values_to_write:
                emp.sudo().write(values_to_write)

            # 2. Create Audit History Log (EM-073)
            history_obj = self.env['hr.employee.change.history'].sudo()
            for line in rec.line_ids:
                val_display = line.new_value or line.new_value_selection
                history_obj.create({
                    'employee_id': emp.id,
                    'change_request_id': rec.id,
                    'field_id': line.field_id.id if line.field_id else False,
                    'field_name': line.field_name,
                    'field_description': line.field_description,
                    'old_value': line.old_value,
                    'new_value': val_display,
                    'change_type': line.change_type,
                    'applied_by_id': self.env.user.id,
                    'applied_date': fields.Datetime.now(),
                    'notes': _("Approved via Master Data Change Request %s") % rec.name,
                })

            # 3. Update Request status
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })

            # 4. Notify Relevant Users (EM-075)
            rec._notify_state_change('approved')
            emp.message_post(body=_("Master Data updated via Change Request %s (Approved by %s).") % (rec.name, self.env.user.name))

    def action_reject(self):
        """ EM-071, EM-075: Reject change request with reason and notify user. """
        self.ensure_one()
        if not self.rejection_reason:
            raise ValidationError(_("Please provide a rejection reason before rejecting the request."))

        self.write({
            'state': 'rejected',
            'rejected_by_id': self.env.user.id,
            'rejection_date': fields.Datetime.now(),
        })

        # EM-075: Send notification to requester
        self._notify_state_change('rejected')

    def _notify_state_change(self, new_state):
        """ EM-075: Send notifications to requester, employee, and HR officers on state changes. """
        for rec in self:
            recip_partners = self.env['res.partner']
            hr_users = self.env['res.users']

            # Add Requester and Employee partners
            if rec.requested_by_id and rec.requested_by_id.partner_id:
                recip_partners |= rec.requested_by_id.partner_id
            if rec.employee_id:
                if rec.employee_id.user_id and rec.employee_id.user_id.partner_id:
                    recip_partners |= rec.employee_id.user_id.partner_id
                if hasattr(rec.employee_id, 'hr_officer_id') and rec.employee_id.hr_officer_id:
                    hr_users |= rec.employee_id.hr_officer_id

            if new_state == 'submitted':
                # Add HR Officers & HR Managers groups
                for xmlid in ['hr.group_hr_user', 'hr.group_hr_manager']:
                    g = self.env.ref(xmlid, raise_if_not_found=False)
                    if g and g.user_ids:
                        hr_users |= g.user_ids

                recip_partners |= hr_users.mapped('partner_id')

                msg = _(
                    "Employee Master Data Change Request %s has been SUBMITTED for review by %s.\n"
                    "Employee: %s\n"
                    "Requested Changes: %s"
                ) % (
                    rec.name,
                    self.env.user.name,
                    rec.employee_id.name if rec.employee_id else '',
                    ", ".join(rec.line_ids.mapped('field_description')) if rec.line_ids else ''
                )
                subj = _("Change Request Submitted: %s") % rec.name

                # Schedule Odoo Activity for HR Officers / Managers
                activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
                for u in hr_users:
                    if u != self.env.user:
                        try:
                            rec.sudo().activity_schedule(
                                activity_type_id=activity_type.id if activity_type else False,
                                summary=_("Change Request Pending Review: %s") % rec.name,
                                note=msg,
                                user_id=u.id,
                            )
                        except Exception:
                            pass

            elif new_state == 'under_review':
                msg = _(
                    "Employee Master Data Change Request %s is now UNDER REVIEW by HR Officer %s."
                ) % (rec.name, self.env.user.name)
                subj = _("Change Request Under Review: %s") % rec.name

            elif new_state == 'approved':
                msg = _(
                    "Employee Master Data Change Request %s has been APPROVED by %s.\n"
                    "The requested employee profile updates have been applied automatically."
                ) % (rec.name, self.env.user.name)
                subj = _("Change Request Approved: %s") % rec.name
                try:
                    rec.sudo().action_feedback(feedback=_("Approved & Applied"))
                except Exception:
                    pass

            elif new_state == 'rejected':
                msg = _(
                    "Employee Master Data Change Request %s was REJECTED by %s.\n"
                    "Rejection Reason: %s"
                ) % (rec.name, self.env.user.name, rec.rejection_reason or _("No reason provided"))
                subj = _("Change Request Rejected: %s") % rec.name
                try:
                    rec.sudo().action_feedback(feedback=_("Rejected"))
                except Exception:
                    pass
            else:
                continue

            partner_ids = [p.id for p in recip_partners if p]

            msg_record = rec.message_post(
                body=msg,
                subject=subj,
                partner_ids=partner_ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

            # Ensure notification lands in Odoo Discuss Inbox (/odoo/discuss) using elevated privileges
            if msg_record and partner_ids:
                notifs = self.env['mail.notification'].sudo().search([
                    ('mail_message_id', '=', msg_record.id),
                    ('res_partner_id', 'in', partner_ids)
                ])
                if notifs:
                    notifs.sudo().write({
                        'notification_type': 'inbox',
                        'is_read': False,
                    })

            # Post Direct Message into Discuss App Direct Chat Channel for each recipient
            sender_partner = self.env.user.partner_id
            for p in recip_partners:
                if p and p != sender_partner:
                    try:
                        partners = list({p.id, sender_partner.id})
                        if len(partners) == 2:
                            ch = self.env['discuss.channel'].sudo()._get_or_create_chat(partners_to=partners)
                            if ch:
                                ch.sudo().message_post(
                                    body=msg,
                                    message_type='comment',
                                    subtype_xmlid='mail.mt_comment',
                                )
                    except Exception:
                        pass

    def action_reset_to_draft(self):
        for rec in self:
            rec.write({'state': 'draft'})


class HrEmployeeChangeRequestLine(models.Model):
    """
    EM-068: Individual Field-level Change Lines (Old vs New value comparison).
    """
    _name = 'hr.employee.change.request.line'
    _description = 'Employee Change Request Detail Line'
    _order = 'request_id, id'

    request_id = fields.Many2one('hr.employee.change.request', string='Change Request', required=True, ondelete='cascade')
    field_id = fields.Many2one(
        'ir.model.fields',
        string='Field',
        required=True,
        domain="[('model', '=', 'hr.employee')]",
        ondelete='cascade'
    )
    field_name = fields.Char(related='field_id.name', string='Technical Field Name', store=True, readonly=True)
    field_description = fields.Char(related='field_id.field_description', string='Field Description', readonly=True)
    field_ttype = fields.Char(string='Field Type', compute='_compute_field_ttype', store=True)
    
    is_selection = fields.Boolean(string='Is Selection Field', compute='_compute_is_selection', store=True)
    new_value_selection = fields.Selection(
        selection='_get_new_value_selection_options',
        string='New Requested Value (Selection)'
    )

    old_value = fields.Text(string='Current Value', readonly=True, compute='_compute_old_value', store=True)
    new_value = fields.Text(string='New Requested Value')
    
    change_type = fields.Selection([
        ('name', 'Name Change'),
        ('education', 'Education & Qualifications'),
        ('marital', 'Marital Status'),
        ('dependent', 'Dependents / Relatives'),
        ('contact', 'Phone & Email'),
        ('emergency', 'Emergency Contact'),
        ('address', 'Residential Address'),
        ('work_permit', 'Work Permit & Visa'),
        ('job_org', 'Job & Organizational'),
        ('other', 'Other Field'),
    ], string='Category', default='other', compute='_compute_change_type', store=True, readonly=False)

    requires_attachment = fields.Boolean(
        string='Attachment Required',
        compute='_compute_requires_attachment',
        store=True,
        help="Calculated based on field configuration rules."
    )

    @api.depends('field_id', 'field_id.ttype')
    def _compute_field_ttype(self):
        for rec in self:
            rec.field_ttype = rec.field_id.ttype if rec.field_id else False

    @api.depends('field_id', 'field_name')
    def _compute_change_type(self):
        name_map = {
            'name': 'name',
            'first_name': 'name',
            'last_name': 'name',
            'study_field': 'education',
            'study_school': 'education',
            'certificate': 'education',
            'marital': 'marital',
            'marital_status': 'marital',
            'children': 'dependent',
            'mobile_phone': 'contact',
            'work_phone': 'contact',
            'work_email': 'contact',
            'private_email': 'contact',
            'phone': 'contact',
            'emergency_contact': 'emergency',
            'emergency_phone': 'emergency',
            'private_street': 'address',
            'private_city': 'address',
            'private_country_id': 'address',
            'permit_no': 'work_permit',
            'work_permit_expiration_date': 'work_permit',
            'visa_no': 'work_permit',
            'visa_expire': 'work_permit',
            'has_work_permit': 'work_permit',
        }
        for rec in self:
            if rec.field_name and rec.field_name in name_map:
                rec.change_type = name_map[rec.field_name]
            elif rec.field_name and ('marital' in rec.field_name or 'marit' in rec.field_name):
                rec.change_type = 'marital'
            elif rec.field_name and ('permit' in rec.field_name or 'visa' in rec.field_name):
                rec.change_type = 'work_permit'
            elif rec.field_name and ('name' in rec.field_name):
                rec.change_type = 'name'
            elif rec.field_name and ('educat' in rec.field_name or 'degree' in rec.field_name):
                rec.change_type = 'education'
            elif rec.field_name and ('phone' in rec.field_name or 'email' in rec.field_name):
                rec.change_type = 'contact'
            elif rec.field_name and ('address' in rec.field_name or 'street' in rec.field_name or 'city' in rec.field_name):
                rec.change_type = 'address'
            elif rec.field_name and ('emergency' in rec.field_name):
                rec.change_type = 'emergency'
            else:
                rec.change_type = 'other'

    @api.depends('field_id', 'change_type')
    def _compute_requires_attachment(self):
        config_obj = self.env['hr.employee.change.field.config'].sudo()
        for rec in self:
            req = False
            if rec.field_id:
                cfg = config_obj.search([('field_id', '=', rec.field_id.id), ('active', '=', True)], limit=1)
                if cfg:
                    req = cfg.requires_attachment
                else:
                    if rec.change_type in ('name', 'education', 'marital', 'dependent', 'work_permit'):
                        req = True
            rec.requires_attachment = req

    @api.depends('field_id', 'field_id.ttype')
    def _compute_is_selection(self):
        for rec in self:
            rec.is_selection = bool(rec.field_id and rec.field_id.ttype == 'selection')

    def _get_new_value_selection_options(self):
        field_id = self.env.context.get('default_field_id')
        if not field_id and self:
            field_id = self[0].field_id.id if self[0].field_id else False

        if field_id:
            field_obj = self.env['ir.model.fields'].sudo().browse(field_id)
            if field_obj and field_obj.model == 'hr.employee' and field_obj.ttype == 'selection':
                emp_field = self.env['hr.employee']._fields.get(field_obj.name)
                if emp_field and hasattr(emp_field, 'selection'):
                    sel = emp_field.selection
                    if callable(sel):
                        return sel(self.env['hr.employee'])
                    elif isinstance(sel, list):
                        return sel

        return [
            ('single', 'Single'),
            ('married', 'Married'),
            ('cohabitant', 'Legal Cohabitant'),
            ('widower', 'Widower'),
            ('divorced', 'Divorced'),
            ('male', 'Male'),
            ('female', 'Female'),
            ('other', 'Other'),
            ('physical', 'Physical'),
            ('visual', 'Visual'),
            ('hearing', 'Hearing'),
            ('mild', 'Mild'),
            ('moderate', 'Moderate'),
            ('severe', 'Severe'),
            ('yes', 'Yes'),
            ('no', 'No'),
        ]

    @api.depends('field_id', 'request_id.employee_id')
    def _compute_old_value(self):
        for rec in self:
            if rec.request_id.employee_id and rec.field_name:
                emp = rec.request_id.employee_id
                val = getattr(emp, rec.field_name, False)
                if val is False or val is None:
                    rec.old_value = ""
                elif rec.field_id and rec.field_id.ttype == 'selection':
                    emp_field = emp._fields.get(rec.field_name)
                    sel_options = []
                    if emp_field and hasattr(emp_field, 'selection'):
                        sel = emp_field.selection
                        if callable(sel):
                            sel_options = sel(emp)
                        elif isinstance(sel, list):
                            sel_options = sel
                    dict_options = dict(sel_options)
                    rec.old_value = dict_options.get(val, str(val))
                elif hasattr(val, 'display_name'):
                    rec.old_value = val.display_name
                elif isinstance(val, bool):
                    rec.old_value = "Yes" if val else "No"
                else:
                    rec.old_value = str(val)
            else:
                rec.old_value = ""

    @api.onchange('new_value_selection')
    def _onchange_new_value_selection(self):
        if self.is_selection and self.new_value_selection:
            if self.field_id and self.field_name and self.request_id.employee_id:
                emp_field = self.request_id.employee_id._fields.get(self.field_name)
                sel_options = []
                if emp_field and hasattr(emp_field, 'selection'):
                    sel = emp_field.selection
                    if callable(sel):
                        sel_options = sel(self.request_id.employee_id)
                    elif isinstance(sel, list):
                        sel_options = sel
                dict_options = dict(sel_options)
                label = dict_options.get(self.new_value_selection, self.new_value_selection)
                self.new_value = label
            else:
                self.new_value = self.new_value_selection

    @api.onchange('field_id')
    def _onchange_field_id_set_old_value(self):
        if self.request_id.employee_id and self.field_id and self.field_id.name:
            emp = self.request_id.employee_id
            val = getattr(emp, self.field_id.name, False)
            if val is False or val is None:
                self.old_value = ""
            elif self.field_id.ttype == 'selection':
                emp_field = emp._fields.get(self.field_id.name)
                sel_options = []
                if emp_field and hasattr(emp_field, 'selection'):
                    sel = emp_field.selection
                    if callable(sel):
                        sel_options = sel(emp)
                    elif isinstance(sel, list):
                        sel_options = sel
                dict_options = dict(sel_options)
                self.old_value = dict_options.get(val, str(val))
            elif hasattr(val, 'display_name'):
                self.old_value = val.display_name
            elif isinstance(val, bool):
                self.old_value = "Yes" if val else "No"
            else:
                self.old_value = str(val)
