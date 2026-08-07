# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
import re
import logging
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


# NOTE: the 'service.request.type' model previously defined here was removed
# to avoid a duplicate _name declaration conflicting with service_request_type.py,
# which is the authoritative definition (see service_request_type.py).


class ServiceRequestEmployee(models.Model):
    _name = "employee.service.request"
    _description = "Employee Service Request"
    _rec_name = "reference"

    # =========================================================================
    # FIELDS
    # =========================================================================
    reference = fields.Char(
        string='Ref',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )

    status = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
    ], default='draft', readonly=True)

    sr_type = fields.Many2one("service.request.type", string="Request Type")

    sr_category = fields.Selection([
        ("Transfer",            "Transfer"),
        ("Others",              "Others"),
        ("Resignation",         "Resignation"),
        ("Self Service Letter", "Self Service Letter"),
    ], string="SR Category")

    letter_name = fields.Selection([
        ("Guarantee Letter", "Guarantee Letter"),
        ("Support Letter",   "Support Letter"),
    ], string="Letter Name")

    requestor = fields.Many2one("hr.employee", string="Requestor")

    requesting_work_unit = fields.Many2one(
        "operating.unit",
        string="Requesting Work Unit",
        readonly=True,
    )

    authorizing_office = fields.Selection([
        ("head_office",              "Head Office"),
        ("adama_area_office",        "Adama Area Office"),
        ("debre_markos_area_office", "Debre Markos Area Office"),
        ("debre_brehan_area_office", "Debre Brehan Area Office"),
        ("hawassa_area_office",      "Hawassa Area Office"),
        ("jimma_area_office",        "Jimma Area Office"),
        ("bahir_dar_district_office","Bahir Dar District Office"),
        ("east_aa_district_office",  "East AA District Office"),
        ("west_aa_district_office",  "West AA District Office"),
        ("south_aa_district_office", "South AA District Office"),
        ("dessie_district_office",   "Dessie District Office"),
        ("mekelle_district_office",  "Mekelle District Office"),
    ], string="Authorizing Office", required=True, default="head_office")

    sr_date = fields.Date(string="SR Date", default=fields.Date.context_today)

    expecting_date = fields.Date(
        string="Application Date",
        default=fields.Date.context_today,
        readonly=True,
    )

    sr_comments = fields.Text(string="Request Details", required=True)

    attachment = fields.Many2many(
        'ir.attachment',
        'ir_emp_service_req_attachment_rel',
        'emp_ser_attach_ids',
        string="Attachment",
    )

    authorizer_id = fields.Many2one("hr.employee", string="Authorizer", ondelete="set null")

    # -------------------------------------------------------------------------
    # Employee information – all populated in default_get
    # -------------------------------------------------------------------------
    employee_id = fields.Many2one("hr.employee", string="Employee Name", readonly=True)

    employee_manager   = fields.Char(string="Manager",       readonly=True)
    manager_user_id    = fields.Integer(string="Manager User ID",    readonly=True)
    manager_partner_id = fields.Integer(string="Manager Partner ID", readonly=True)

    employee_work_unit = fields.Char(string="Employee Work Unit", readonly=True)
    employee_position  = fields.Many2one("hr.job",         string="Position", readonly=True)
    employee_grade     = fields.Many2one("employee.grade", string="Grade",    readonly=True)
    employee_category  = fields.Char(string="Category",  readonly=True)
    employee_gender    = fields.Char(string="Gender",    readonly=True)
    employee_mail      = fields.Char(string="Email",     readonly=True)
    employee_phone     = fields.Char(string="Phone Number", readonly=True)

    # -------------------------------------------------------------------------
    # Acting / Transfer
    # -------------------------------------------------------------------------
    acting_vacant_position    = fields.Many2one("hr.job",       string="Vacant Position (Acting)")
    acting_suggested_employee = fields.Many2one("hr.employee",  string="Suggested Employee (Acting)")
    transfer_ou1 = fields.Many2one("operating.unit", string="Requested Operating Unit (Transfer)")
    transfer_ou2 = fields.Many2one("operating.unit", string="Preferred Location 2")
    transfer_ou3 = fields.Many2one("operating.unit", string="Preferred Location 3")
    start_date = fields.Date(string="Start Date")
    end_date   = fields.Date(string="End Date")

    # -------------------------------------------------------------------------
    # Guarantee Letter
    # -------------------------------------------------------------------------
    name_of_the_external_person = fields.Char(string="Name of the external Person")
    name_of_the_organization    = fields.Char(string="Name of the Organization")
    organization_address        = fields.Char(string="Organization Address")
    organization_email_address  = fields.Char(string="Organization Email Address")
    sub_city     = fields.Char(string="Sub City")
    woreda       = fields.Char(string="Woreda")
    kebele       = fields.Char(string="Kebele")
    phone_number = fields.Char(string="Phone Number")

    # -------------------------------------------------------------------------
    # Support Letter
    # -------------------------------------------------------------------------
    support           = fields.Char(string="Support")
    organization_name = fields.Char(string="Organization Name")
    salary            = fields.Float(string="Salary")
    permanent_emp     = fields.Boolean(string="Permanent Employee")
    job_position      = fields.Char(string="Job Position")

    # -------------------------------------------------------------------------
    # Extension Fields
    # -------------------------------------------------------------------------
    rejection_reason = fields.Text(
        string="Reason for Rejection", readonly=True, copy=False
    )
    pobox = fields.Char(string="P.O. Box")
    ref_num = fields.Char(string="Reference Number (External Letter)")
    type_guarantee = fields.Selection([('in', 'In'), ('out', 'Out')], string="Type of Guarantee")
    effective_date = fields.Date(string="Effective Date")
    guarantee_amount = fields.Float(string="Guarantee Amount")

    # =========================================================================
    # ONCHANGES / SYNC LOGIC
    # =========================================================================

    @api.onchange('letter_name')
    def _onchange_letter_name(self):
        if self.letter_name and self.sr_category == 'Self Service Letter':
            sr_type_model = self.env['service.request.type']
            domain = []
            if 'name' in sr_type_model._fields:
                domain.append(('name', '=', self.letter_name))
            if 'sr_type' in sr_type_model._fields:
                domain.append(('sr_type', '=', self.letter_name))

            search_domain = ['|'] * (len(domain) - 1) + domain if len(domain) > 1 else domain
            sr_type_rec = sr_type_model.search(search_domain, limit=1)
            if not sr_type_rec:
                create_vals = {}
                if 'name' in sr_type_model._fields:
                    create_vals['name'] = self.letter_name
                if 'sr_type' in sr_type_model._fields:
                    create_vals['sr_type'] = self.letter_name
                sr_type_rec = sr_type_model.create(create_vals)
            self.sr_type = sr_type_rec.id

    def _sync_sr_type_from_letter_name_vals(self, vals):
        letter_name = vals.get('letter_name') or (self.letter_name if self else False)
        sr_category = vals.get('sr_category') or (self.sr_category if self else False)
        if letter_name and sr_category == 'Self Service Letter':
            sr_type_model = self.env['service.request.type']
            domain = []
            if 'name' in sr_type_model._fields:
                domain.append(('name', '=', letter_name))
            if 'sr_type' in sr_type_model._fields:
                domain.append(('sr_type', '=', letter_name))

            search_domain = ['|'] * (len(domain) - 1) + domain if len(domain) > 1 else domain
            sr_type_rec = sr_type_model.search(search_domain, limit=1)
            if not sr_type_rec:
                create_vals = {}
                if 'name' in sr_type_model._fields:
                    create_vals['name'] = letter_name
                if 'sr_type' in sr_type_model._fields:
                    create_vals['sr_type'] = letter_name
                sr_type_rec = sr_type_model.create(create_vals)
            vals['sr_type'] = sr_type_rec.id

    # =========================================================================
    # AUTO-POPULATE FROM LOGGED-IN EMPLOYEE
    # =========================================================================

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1
        )
        if not employee:
            return res

        manager = employee.coach_id.sudo() or employee.parent_id.sudo()

        requesting_wu_id = False
        work_unit_name   = ''
        if hasattr(employee, 'default_operating_unit_id') and employee.default_operating_unit_id:
            requesting_wu_id = employee.default_operating_unit_id.id
            work_unit_name   = employee.default_operating_unit_id.name

        position_id = False
        if hasattr(employee, 'job_id') and employee.job_id:
            position_id = employee.job_id.id

        category_name = ''
        if employee.grade_id and employee.grade_id.category:
            category_name = employee.grade_id.category
        elif hasattr(employee, 'contract_id') and employee.contract_id and employee.contract_id.employee_category:
            category_name = employee.contract_id.employee_category.name

        grade_id = False
        if employee.grade_id:
            grade_id = employee.grade_id.id

        manager_partner_id = 0
        if manager and manager.user_id and manager.user_id.partner_id:
            manager_partner_id = manager.user_id.partner_id.id

        res.update({
            'requestor':            employee.id,
            'employee_id':          employee.id,
            'requesting_work_unit': requesting_wu_id,
            'employee_manager':     manager.name if manager else '',
            'manager_user_id':      manager.user_id.id if manager and manager.user_id else 0,
            'manager_partner_id':   manager_partner_id,
            'employee_work_unit':   work_unit_name,
            'employee_position':    position_id,
            'employee_grade':       grade_id,
            'employee_category':    category_name,
            'employee_gender':      employee.sex or '',
            'employee_mail':        employee.work_email or '',
            'employee_phone':       employee.work_phone or employee.phone_num or '',
        })
        return res

    # =========================================================================
    # CREATE / WRITE
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['reference'] = _('New')
            if not vals.get('requestor'):
                emp = self.env['hr.employee'].search(
                    [('user_id', '=', self.env.uid)], limit=1
                )
                if emp:
                    vals.setdefault('requestor',   emp.id)
                    vals.setdefault('employee_id', emp.id)
            self._sync_sr_type_from_letter_name_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        for record in self:
            record._sync_sr_type_from_letter_name_vals(vals)
        return super().write(vals)

    # =========================================================================
    # SEQUENCE HELPER
    # =========================================================================

    def _assign_reference_if_new(self):
        if self.reference == _('New'):
            next_ref = (
                self.env['ir.sequence'].next_by_code('employee.service.request')
                or _('New')
            )
            self.sudo().write({'reference': next_ref})

    # =========================================================================
    # VALIDATION HELPERS
    # =========================================================================

    def _check_guarantee_fields(self):
        required = {
            'name_of_the_external_person': 'Name of the external Person',
            'name_of_the_organization':    'Name of the Organization',
            'organization_address':        'Organization Address',
        }
        missing = [label for field, label in required.items() if not getattr(self, field)]

        email = self.organization_email_address
        pobox_val = self.pobox

        if not email and not pobox_val:
            raise ValidationError(
                _("Either Organization Email Address or P.O. Box must be provided.")
            )

        if missing:
            raise ValidationError(
                _('The following Guarantee Information fields are required:\n• ')
                + '\n• '.join(missing)
            )

    def _validate_phone(self, phone):
        cleaned = phone.replace(' ', '').replace('-', '')
        if not re.match(r'^\+?[0-9]{7,15}$', cleaned):
            raise ValidationError(
                'Phone Number is invalid.\n'
                'Accepted formats: +251XXXXXXXXX, 09XXXXXXXX, or any 7-15 digit number.'
            )

    def _validate_email(self, email):
        if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-]{2,}$', email.strip()):
            raise ValidationError(
                'Organization Email Address is invalid.\n'
                'Example: contact@organization.com'
            )

    # =========================================================================
    # FETCH
    # =========================================================================

    def action_fetch_employee_data(self):
        """Fetch/reload the service request form and refresh employee data"""
        self.ensure_one()

        # Refresh the employee information from the current logged-in user
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1
        )

        if not employee:
            raise UserError(_('No employee record found for the current user.'))

        # Update employee-related read-only fields with fresh data
        manager = employee.coach_id.sudo() or employee.parent_id.sudo()

        position_id = False
        if hasattr(employee, 'job_id') and employee.job_id:
            position_id = employee.job_id.id

        category_name = ''
        if employee.grade_id and employee.grade_id.category:
            category_name = employee.grade_id.category
        elif hasattr(employee, 'contract_id') and employee.contract_id and employee.contract_id.employee_category:
            category_name = employee.contract_id.employee_category.name

        grade_id = False
        if employee.grade_id:
            grade_id = employee.grade_id.id

        work_unit_name = ''
        if hasattr(employee, 'default_operating_unit_id') and employee.default_operating_unit_id:
            work_unit_name = employee.default_operating_unit_id.name

        # Update the record with refreshed employee data
        self.write({
            'employee_manager': manager.name if manager else '',
            'employee_work_unit': work_unit_name,
            'employee_position': position_id,
            'employee_grade': grade_id,
            'employee_category': category_name,
            'employee_gender': employee.sex or '',
            'employee_mail': employee.work_email or '',
            'employee_phone': employee.work_phone or employee.phone_num or '',
        })

        # Reload and return the form view
        return {
            'name': _('Service Request'),
            'type': 'ir.actions.act_window',
            'res_model': 'employee.service.request',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'main',
            'context': self.env.context,
        }

    # =========================================================================
    # NOTIFY
    # =========================================================================

    def notify(self):
        self.ensure_one()

        # ----- Step 1: Input/Limit Validation --------------------------------
        if self.sr_category == "Self Service Letter":
            if self.letter_name == "Guarantee Letter":
                self._check_guarantee_fields()
                if self.phone_number:
                    self._validate_phone(self.phone_number)
                if self.organization_email_address:
                    self._validate_email(self.organization_email_address)

                # Guarantee Letter validation rules from extension
                active_guarantees_count = self.env['guarentees.details'].search_count([
                    ('employee_id', '=', self.employee_id.id),
                    ('type', '=', 'external'),
                    ('state', '=', 'active'),
                ])
                if active_guarantees_count >= 3:
                    raise ValidationError(
                        _("You cannot submit a Guarantee Letter request because you already have more than 3 active external guarantees.")
                    )

                request_count = self.env['employee.service.request'].search_count([
                    ('id', '!=', self.id),
                    ('employee_id', '=', self.employee_id.id),
                    ('letter_name', '=', 'Guarantee Letter'),
                    ('status', '!=', 'rejected'),
                ])
                if request_count >= 3:
                    raise ValidationError(
                        _("You cannot submit a Guarantee Letter request because you already have more than 3 guarantee requests.")
                    )

            elif self.letter_name == "Support Letter":
                if not self.organization_name:
                    raise ValidationError('Please fill in the Organization Name.')

        elif self.sr_category == "Acting":
            if bool(self.employee_id) == bool(self.acting_vacant_position):
                raise ValidationError('Specify either Employee OR Vacant Position.')
            if not self.acting_suggested_employee:
                raise ValidationError('Suggested Employee is required.')
            if not self.start_date or not self.end_date:
                raise ValidationError('Start Date and End Date are required.')

        elif self.sr_category == "Transfer":
            if not self.transfer_ou1:
                raise ValidationError('Requested Operating Unit is required.')

        # ----- Step 2: Stamp reference number --------------------------------
        self._assign_reference_if_new()

        # ----- Step 3: Resolve metadata values for the notification ---------
        rec = self.sudo().browse(self.id)

        sr_type_label = ''
        if rec.sr_type:
            sr_type_label = (
                getattr(rec.sr_type, 'sr_type', None)
                or getattr(rec.sr_type, 'name',    None)
                or rec.sr_type.display_name
                or ''
            )

        requestor_name = ''
        if rec.requestor:
            requestor_name = rec.requestor.name or ''
        elif rec.employee_id:
            requestor_name = rec.employee_id.name or ''
        else:
            live_emp = self.env['hr.employee'].search(
                [('user_id', '=', self.env.uid)], limit=1
            )
            requestor_name = live_emp.name if live_emp else ''

        employee_name = rec.employee_id.name if rec.employee_id else requestor_name

        # ----- Step 4: Resolve Recipient Partner IDs (Manager + HR List) -----
        partner_ids = []

        # 1. Fetch Requestor's Direct Line Manager Partner ID
        manager_partner_id = rec.manager_partner_id
        if not manager_partner_id:
            live_emp = self.env['hr.employee'].search(
                [('user_id', '=', self.env.uid)], limit=1
            )
            coach = live_emp.coach_id.sudo() or live_emp.parent_id.sudo()
            if live_emp and coach and coach.user_id:
                p = coach.user_id.partner_id
                manager_partner_id = p.id if p else 0

        if manager_partner_id:
            partner_ids.append(manager_partner_id)

        # 2. Fetch Targeted HR Users reporting to Melesse Leykun Birhanu (ID 45)
        try:
            user_query = """
                SELECT DISTINCT rp.id 
                FROM hr_employee emp
                INNER JOIN res_users ru ON emp.user_id = ru.id
                INNER JOIN res_partner rp ON ru.partner_id = rp.id
                WHERE emp.active = true
                  AND emp.coach_id = 45
            """
            self.env.cr.execute(user_query)
            target_partner_ids = [row[0] for row in self.env.cr.fetchall() if row[0]]

            if target_partner_ids:
                partner_ids.extend(target_partner_ids)
                _logger.info("Successfully matched and added %s HR partner accounts directly via relational coach mapping.", len(target_partner_ids))
            else:
                _logger.warning("SQL evaluation matched 0 active partner records for coach_id 45.")

        except Exception as sql_err:
            _logger.error("Error running user routing query logic loop: %s", sql_err)

        # Remove duplicate records to prevent sending overlapping copies
        partner_ids = list(set(partner_ids))

        _logger.info(
            "SR notify() id=%s ref=%s resolved_recipients=%s",
            self.id, rec.reference, partner_ids
        )

        # ----- Step 5: Dispatch notifications (discuss.channel Direct Message) ---
        if partner_ids:
            for pid in partner_ids:
                self._discuss_channel_msg(
                    pid,
                    rec.reference,
                    sr_type_label,
                    requestor_name,
                    employee_name,
                )
        else:
            _logger.warning(
                "SR notify() id=%s: No valid partner profiles resolved. Notification skipped.",
                self.id,
            )

        # ----- Step 6: Create or update Guarantees Details (for Guarantee Letters) -----
        if self.letter_name == 'Guarantee Letter' and self.sr_category == 'Self Service Letter':
            try:
                existing_guarantee = self.env['guarentees.details'].search([
                    ('service_request_id', '=', self.id)
                ], limit=1)

                vals = {
                    'employee_id': self.employee_id.id,
                    'ref_num': self.ref_num or self.reference,
                    'type_guarantee': self.type_guarantee,
                    'effective_date': self.effective_date,
                    'name_of_staff': self.employee_id.id,
                    'external_person_name': self.name_of_the_external_person,
                    'guarantee_amount': self.guarantee_amount,
                    'name_of_institution': self.name_of_the_organization,
                    'type': 'internal' if self.type_guarantee == 'in' else 'external',
                    'state': 'active',
                    'service_request_id': self.id,
                }

                if existing_guarantee:
                    existing_guarantee.write(vals)
                else:
                    self.env['guarentees.details'].create(vals)
            except Exception as e:
                _logger.error(
                    "SR notify() id=%s: failed to populate guarantees details: %s",
                    self.id, e
                )

        # ----- Step 7: Mark submitted and reload the form -------------------
        self.write({'status': 'submitted'})

        return {
            'name':      _('Service Request'),
            'type':      'ir.actions.act_window',
            'res_model': 'employee.service.request',
            'view_mode': 'form',
            'res_id':    self.id,
            'target':    'main',
            'context':   self.env.context,
        }

    # =========================================================================
    # MAIL HELPER
    # =========================================================================

    def _discuss_channel_msg(self, partner_id, ref, sr_type, requestor_name, employee_name):
        """Open (or create) a DM channel with partner_id and post the notification using Odoo 19 discuss.channel."""
        if not partner_id:
            return

        body = (
            "Dear Colleague,<br/><br/>"
            "A new Service Request has been raised with the following details:"
            "<br/><br/>"
            "<b>Reference No:</b> {ref}<br/>"
            "<b>Service Request Type:</b> {sr_type}<br/>"
            "<b>Requestor Name:</b> {requestor}<br/>"
            "<br/><br/>Kindly review and process."
        ).format(
            ref=ref,
            sr_type=sr_type or '',
            requestor=requestor_name or '',
            employee=employee_name or '',
        )

        try:
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[partner_id])
            channel.message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            _logger.info(
                "SR notify() id=%s: message posted to partner_id=%s discuss channel",
                self.id, partner_id
            )
        except Exception as exc:
            _logger.error(
                "SR notify() id=%s: failed to post to partner_id=%s: %s",
                self.id, partner_id, exc,
            )

    # =========================================================================
    # ACTION BUTTONS
    # =========================================================================

    def action_accept(self):
        for record in self:
            if record.status != "submitted":
                raise UserError(
                    _("Only submitted requests can be accepted into progress.")
                )
            record.write({"status": "in_progress"})

    def action_complete(self):
        for record in self:
            if record.status != "in_progress":
                raise UserError(
                    _("Only requests currently 'In Progress' can be marked as completed.")
                )
            if record.letter_name == 'Guarantee Letter':
                return {
                    'name': _('Complete Guarantee Letter Request'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'service.request.completion.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {'default_request_id': record.id},
                }

            # Normal completion flow for non-Guarantee Letters
            record.write({"status": "completed"})
            if (
                record.requestor
                and record.requestor.user_id
                and record.requestor.user_id.partner_id
            ):
                requestor_partner_id = record.requestor.user_id.partner_id.id
                sr_type_label = ""
                if record.sr_type:
                    sr_type_label = (
                        getattr(record.sr_type, "sr_type", None)
                        or getattr(record.sr_type, "name", None)
                        or record.sr_type.display_name
                        or ""
                    )
                body = (
                    "Dear {name},<br/><br/>"
                    "Your Service Request <b>{ref}</b> ({sr_type}) has been successfully "
                    "<b>Completed</b> by the HR Team.<br/><br/>Regards,"
                ).format(
                    name=record.requestor.name,
                    ref=record.reference,
                    sr_type=sr_type_label,
                )
                try:
                    channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[requestor_partner_id])
                    channel.message_post(
                        body=body,
                        message_type="comment",
                        subtype_xmlid="mail.mt_comment",
                    )
                except Exception:
                    pass

    def action_reject_wizard(self):
        self.ensure_one()
        if self.status not in ["submitted", "in_progress"]:
            raise UserError(
                _("You can only reject requests that are submitted or in progress.")
            )
        return {
            "name": _("Reason for Rejection"),
            "type": "ir.actions.act_window",
            "res_model": "service.request.rejection.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id},
        }
