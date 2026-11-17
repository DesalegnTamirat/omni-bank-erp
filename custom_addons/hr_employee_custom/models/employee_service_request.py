# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
import re
import logging
from markupsafe import Markup, escape
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
        ("Self Service Letter", "Self Service Letter"),
    ], string="SR Category", default="Self Service Letter", required=True)

    letter_name = fields.Selection([
        ("Guarantee Letter", "Guarantee Letter"),
        ("Support Letter",   "Support Letter"),
    ], string="Letter Name", required=True)

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
    employee_phone     = fields.Char(string="Employee Phone Number", readonly=True)

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
    organization_name = fields.Char(
        string="Addressed To / Recipient",
        default="To Whom It May Concern",
        help="Name of the organization, embassy, university, or authority requesting the letter.",
    )
    support_purpose = fields.Selection([
        ('general', 'General Confirmation'),
        ('visa', 'Visa / Embassy Application'),
        ('financial', 'Bank / Financial / Loan Application'),
        ('academic', 'Academic / Higher Education Application'),
        ('government', 'Government / Administrative Office'),
        ('other', 'Other Purpose'),
    ], string="Support Purpose", default='general')
    support = fields.Text(
        string="Specific Purpose / Remarks",
        help="Optional additional details, special instructions, or custom purpose.",
    )
    include_salary = fields.Boolean(
        string="Include Salary in Letter?",
        default=False,
        help="Check this if the support letter must state the monthly gross salary.",
    )
    salary = fields.Float(
        string="Monthly Gross Salary",
        readonly=True,
        help="Monthly gross salary to be stated in the letter.",
    )
    salary_in_words = fields.Char(
        string="Salary in Words",
        compute="_compute_support_salary_words",
        store=True,
        readonly=True,
    )
    letter_language = fields.Selection([
        ('en', 'English'),
        ('am', 'Amharic'),
    ], string="Letter Language", default='en', required=True)
    permanent_emp = fields.Boolean(
        string="Permanent Employee",
        default=True,
    )
    job_position = fields.Char(string="Job Position")
    hire_date = fields.Date(string="Hire Date / Start Date")

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

    def _extract_employee_meta(self, employee):
        """Helper to extract clean metadata from hr.employee"""
        if not employee:
            return {}

        manager = employee.coach_id.sudo() or employee.parent_id.sudo()

        requesting_wu_id = False
        work_unit_name = ''
        if hasattr(employee, 'default_operating_unit_id') and employee.default_operating_unit_id:
            requesting_wu_id = employee.default_operating_unit_id.id
            work_unit_name = employee.default_operating_unit_id.name

        position_id = False
        if hasattr(employee, 'job_id') and employee.job_id:
            position_id = employee.job_id.id

        # Determine Category: Managerial or Non Managerial from Job Position or Grade
        category_name = ''
        if employee.job_id:
            if hasattr(employee.job_id, 'employee_category') and employee.job_id.employee_category:
                cat_val = employee.job_id.employee_category
                category_name = getattr(cat_val, 'name', str(cat_val))
            elif hasattr(employee.job_id, 'is_managerial'):
                category_name = 'Managerial' if employee.job_id.is_managerial else 'Non Managerial'

        if not category_name:
            if employee.grade_id and employee.grade_id.category:
                cat_val = employee.grade_id.category
                category_name = getattr(cat_val, 'name', str(cat_val))
            elif hasattr(employee, 'contract_id') and employee.contract_id and employee.contract_id.employee_category:
                category_name = employee.contract_id.employee_category.name or ''

        grade_id = employee.grade_id.id if employee.grade_id else False

        manager_partner_id = 0
        if manager and manager.user_id and manager.user_id.partner_id:
            manager_partner_id = manager.user_id.partner_id.id

        # Gender: read employee.gender (selection: male, female, other)
        gender_val = employee.gender or getattr(employee, 'sex', '') or ''
        if gender_val and hasattr(employee._fields.get('gender'), 'selection'):
            gender_val = dict(employee._fields['gender'].selection).get(gender_val, str(gender_val).capitalize())
        elif gender_val:
            gender_val = str(gender_val).capitalize()

        # Email: work_email, private_email, or login user email
        email_val = (
            employee.work_email
            or getattr(employee, 'private_email', False)
            or (employee.user_id.email if employee.user_id else False)
            or (employee.user_id.login if employee.user_id and '@' in employee.user_id.login else '')
            or ''
        )

        # Phone: mobile_phone, personal_phone, work_phone, or phone_num
        phone_val = (
            employee.work_phone
            or employee.mobile_phone
            or getattr(employee, 'personal_phone', False)
            or getattr(employee, 'phone_num', False)
            or ''
        )

        # Support Letter Defaults:
        job_pos_name = (
            (employee.job_id and employee.job_id.name)
            or getattr(employee, 'job_title', False)
            or ''
        )
        hire_date_val = False
        if hasattr(employee, 'get_experience_letter_start_date'):
            try:
                start_str = employee.get_experience_letter_start_date()
                if start_str:
                    hire_date_val = fields.Date.from_string(start_str)
            except Exception:
                hire_date_val = False
        if not hire_date_val:
            if hasattr(employee, 'first_contract_date') and employee.first_contract_date:
                hire_date_val = employee.first_contract_date
            elif hasattr(employee, 'contract_id') and employee.contract_id and employee.contract_id.date_start:
                hire_date_val = employee.contract_id.date_start
            elif employee.create_date:
                hire_date_val = employee.create_date.date()

        salary_val = 0.0
        if hasattr(employee, 'get_experience_letter_salary_info'):
            try:
                salary_info = employee.get_experience_letter_salary_info()
                salary_val = salary_info.get('amount', 0.0)
            except Exception:
                salary_val = 0.0
        if not salary_val and hasattr(employee, 'contract_id') and employee.contract_id:
            salary_val = getattr(employee.contract_id, 'wage', 0.0) or 0.0

        return {
            'requestor': employee.id,
            'employee_id': employee.id,
            'requesting_work_unit': requesting_wu_id,
            'employee_manager': manager.name if manager else '',
            'manager_user_id': manager.user_id.id if manager and manager.user_id else 0,
            'manager_partner_id': manager_partner_id,
            'employee_work_unit': work_unit_name,
            'employee_position': position_id,
            'employee_grade': grade_id,
            'employee_category': category_name,
            'employee_gender': gender_val,
            'employee_mail': email_val,
            'employee_phone': phone_val,
            'job_position': job_pos_name,
            'permanent_emp': True,
            'hire_date': hire_date_val,
            'salary': salary_val,
            'organization_name': 'To Whom It May Concern',
        }

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1
        )
        if not employee:
            return res

        meta = self._extract_employee_meta(employee)
        res.update(meta)
        return res

    # =========================================================================
    # CREATE / WRITE
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['reference'] = _('New')
            emp_id = vals.get('employee_id') or vals.get('requestor')
            if not emp_id:
                emp = self.env['hr.employee'].search(
                    [('user_id', '=', self.env.uid)], limit=1
                )
            else:
                emp = self.env['hr.employee'].browse(emp_id)

            if emp:
                meta = self._extract_employee_meta(emp)
                for k, v in meta.items():
                    vals.setdefault(k, v)

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

        employee = self.employee_id or self.requestor or self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1
        )

        if not employee:
            raise UserError(_('No employee record found for the current user.'))

        meta = self._extract_employee_meta(employee)
        # Update the record with refreshed employee data
        self.write(meta)

        # Return toast notification with form reload
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Data Refreshed'),
                'message': _('Employee profile details have been refreshed successfully.'),
                'type': 'info',
                'sticky': False,
                'next': {
                    'name': _('Service Request'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'employee.service.request',
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'res_id': self.id,
                    'target': 'current',
                    'context': self.env.context,
                }
            }
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
                active_guarantees_count = self.env['guarentees.details'].sudo().search_count([
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

        # ----- Step 4: Resolve Recipient Partner IDs (Manager + HR Team) -----
        partner_ids = set()

        # 1. Fetch Requestor's Direct Line Manager Partner ID
        manager_partner_id = rec.manager_partner_id
        if not manager_partner_id:
            live_emp = self.env['hr.employee'].sudo().search(
                [('user_id', '=', self.env.uid)], limit=1
            )
            coach = live_emp.coach_id.sudo() or live_emp.parent_id.sudo()
            if live_emp and coach and coach.user_id:
                p = coach.user_id.partner_id
                manager_partner_id = p.id if p else 0

        if manager_partner_id:
            partner_ids.add(manager_partner_id)

        # 2. Fetch Targeted HR Users:
        # A. Include all users in Service Request & HR management/officer roles
        hr_group_xmlids = [
            'hr_employee_custom.group_service_request_manager',
            'hr_employee_custom.group_service_request_officer',
            'hr.group_hr_manager',
            'hr.group_hr_user',
        ]
        for g_xmlid in hr_group_xmlids:
            try:
                grp = self.env.ref(g_xmlid, raise_if_not_found=False)
                if grp:
                    grp_users = getattr(grp, 'all_user_ids', None) or getattr(grp, 'user_ids', None)
                    if grp_users:
                        for u in grp_users:
                            if u.active and u.partner_id:
                                partner_ids.add(u.partner_id.id)
            except Exception as grp_err:
                _logger.warning("Error resolving group %s: %s", g_xmlid, grp_err)

        # B. Find Melesse Leykun Birhanu dynamically and include all active reporting officers (POMD Directorate)
        try:
            melesse = self.env['hr.employee'].sudo().search([
                ('name', 'ilike', 'Melesse Leykun Birhanu')
            ], limit=1)
            melesse_id = melesse.id if melesse else 4342

            user_query = """
                SELECT DISTINCT rp.id 
                FROM hr_employee emp
                INNER JOIN res_users ru ON emp.user_id = ru.id
                INNER JOIN res_partner rp ON ru.partner_id = rp.id
                WHERE emp.active = true
                  AND ru.active = true
                  AND (emp.coach_id = %s OR emp.parent_id = %s OR emp.id = %s)
            """
            self.env.cr.execute(user_query, (melesse_id, melesse_id, melesse_id))
            for row in self.env.cr.fetchall():
                if row[0]:
                    partner_ids.add(row[0])
        except Exception as sql_err:
            _logger.error("Error running user routing query logic loop: %s", sql_err)

        # Exclude the submitter themselves so they don't receive an alert for their own action
        current_partner_id = self.env.user.partner_id.id if self.env.user.partner_id else 0
        partner_ids.discard(current_partner_id)
        partner_ids = list(partner_ids)

        _logger.info(
            "SR notify() id=%s ref=%s resolved_recipients=%s",
            self.id, rec.reference, partner_ids
        )

        # ----- Step 5: Dispatch notifications (Discuss DM + Toast) ---
        if partner_ids:
            for pid in partner_ids:
                try:
                    self.sudo()._discuss_channel_msg(
                        pid,
                        rec.reference,
                        sr_type_label,
                        requestor_name,
                        employee_name,
                    )
                except Exception as d_err:
                    _logger.warning("Failed to send discuss message to partner %s: %s", pid, d_err)

                try:
                    target_partner = self.env['res.partner'].sudo().browse(pid)
                    self.env['bus.bus'].sudo()._sendone(target_partner, 'simple_notification', {
                        'title': _('New Service Request (%s)') % (rec.reference or ''),
                        'message': _('A new %s has been submitted by %s.') % (sr_type_label or _('Service Request'), employee_name),
                        'type': 'info',
                        'sticky': False,
                    })
                except Exception as b_err:
                    _logger.warning("Failed to send bus toast to partner %s: %s", pid, b_err)
        else:
            _logger.warning(
                "SR notify() id=%s: No valid partner profiles resolved. Notification skipped.",
                self.id,
            )

        # ----- Step 6: Create or update Guarantees Details (for Guarantee Letters) -----
        if self.letter_name == 'Guarantee Letter' and self.sr_category == 'Self Service Letter':
            try:
                existing_guarantee = self.env['guarentees.details'].sudo().search([
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
                    existing_guarantee.sudo().write(vals)
                else:
                    self.env['guarentees.details'].sudo().create(vals)
            except Exception as e:
                _logger.error(
                    "SR notify() id=%s: failed to populate guarantees details: %s",
                    self.id, e
                )

        # ----- Step 7: Mark submitted and return success toast notification ---
        self.write({'status': 'submitted'})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Submitted Successfully'),
                'message': _('Service Request %s has been submitted and notifications sent.') % rec.reference,
                'type': 'success',
                'sticky': False,
                'next': {
                    'name':      _('Service Request'),
                    'type':      'ir.actions.act_window',
                    'res_model': 'employee.service.request',
                    'view_mode': 'form',
                    'views':     [(False, 'form')],
                    'res_id':    self.id,
                    'target':    'current',
                    'context':   self.env.context,
                }
            }
        }

    # =========================================================================
    # MAIL HELPER
    # =========================================================================

    def _discuss_channel_msg(self, partner_id, ref, sr_type, requestor_name, employee_name):
        """Open (or create) a DM channel with partner_id and post the notification using Odoo 19 discuss.channel."""
        if not partner_id:
            return

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        sr_url = f"{base_url.rstrip('/')}/web#id={self.id}&model=employee.service.request&view_type=form" if base_url else f"/web#id={self.id}&model=employee.service.request&view_type=form"
        body = Markup(
            f"<p>Dear Colleague,</p>"
            f"<p>A new Service Request has been raised with the following details:</p>"
            f"<ul>"
            f"<li><b>Reference No:</b> {escape(str(ref or ''))}</li>"
            f"<li><b>Service Request Type:</b> {escape(str(sr_type or ''))}</li>"
            f"<li><b>Requestor Name:</b> {escape(str(requestor_name or ''))}</li>"
            f"</ul>"
            f"<div style='margin-top: 10px; margin-bottom: 12px;'>"
            f"<a href='{sr_url}' target='_blank' style='display: inline-block; padding: 8px 16px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
            f"👉 Open Service Request ({escape(str(ref or ''))})"
            f"</a>"
            f"</div>"
            f"<p>Kindly review and process.</p>"
        )

        try:
            channel = self.env['discuss.channel'].sudo()._get_or_create_chat(partners_to=[partner_id])
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

            # Notify requestor that request has been accepted and is now in progress
            emp = record.requestor or record.employee_id
            if emp and emp.user_id and emp.user_id.partner_id:
                requestor_partner_id = emp.user_id.partner_id.id
                sr_type_label = ""
                if record.sr_type:
                    sr_type_label = (
                        getattr(record.sr_type, "sr_type", None)
                        or getattr(record.sr_type, "name", None)
                        or record.sr_type.display_name
                        or ""
                    )
                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
                sr_url = f"{base_url.rstrip('/')}/web#id={record.id}&model=employee.service.request&view_type=form" if base_url else f"/web#id={record.id}&model=employee.service.request&view_type=form"
                body = Markup(
                    f"<p>Dear <b>{escape(emp.name or '')}</b>,</p>"
                    f"<p>Your Service Request <b>{escape(record.reference or '')}</b> ({escape(sr_type_label or '')}) has been <b>Accepted</b> and is currently <b>In Progress</b> with the HR Team.</p>"
                    f"<div style='margin-top: 10px; margin-bottom: 12px;'>"
                    f"<a href='{sr_url}' target='_blank' style='display: inline-block; padding: 8px 16px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
                    f"👉 View Service Request"
                    f"</a>"
                    f"</div>"
                    f"<p>Best regards,<br/>HR Team</p>"
                )
                try:
                    channel = self.env["discuss.channel"].sudo()._get_or_create_chat(partners_to=[requestor_partner_id])
                    channel.message_post(
                        body=body,
                        message_type="comment",
                        subtype_xmlid="mail.mt_comment",
                    )
                except Exception as e:
                    _logger.warning("Failed to send accept notification: %s", e)
                try:
                    emp_partner = emp.user_id.partner_id
                    self.env['bus.bus']._sendone(emp_partner, 'simple_notification', {
                        'title': _('Service Request Accepted'),
                        'message': _('Your Service Request %s has been Accepted and is currently In Progress.') % record.reference,
                        'type': 'info',
                        'sticky': False,
                    })
                except Exception as be:
                    _logger.warning("Failed to send accept bus toast: %s", be)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Request Accepted'),
                'message': _('Service Request %s is now In Progress.') % self.reference,
                'type': 'success',
                'sticky': False,
                'next': {
                    'name': _('Service Request'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'employee.service.request',
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'res_id': self.id,
                    'target': 'current',
                    'context': self.env.context,
                }
            }
        }

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
                    'views': [(False, 'form')],
                    'target': 'new',
                    'context': {'default_request_id': record.id},
                }

            # Normal completion flow for non-Guarantee Letters
            record.write({"status": "completed"})
            emp = record.requestor or record.employee_id
            if (
                emp
                and emp.user_id
                and emp.user_id.partner_id
            ):
                requestor_partner_id = emp.user_id.partner_id.id
                sr_type_label = ""
                if record.sr_type:
                    sr_type_label = (
                        getattr(record.sr_type, "sr_type", None)
                        or getattr(record.sr_type, "name", None)
                        or record.sr_type.display_name
                        or ""
                    )
                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
                sr_url = f"{base_url.rstrip('/')}/web#id={record.id}&model=employee.service.request&view_type=form" if base_url else f"/web#id={record.id}&model=employee.service.request&view_type=form"
                body = Markup(
                    f"<p>Dear <b>{escape(emp.name or '')}</b>,</p>"
                    f"<p>Your Service Request <b>{escape(record.reference or '')}</b> ({escape(sr_type_label or '')}) has been successfully <b>Completed</b> by the HR Team.</p>"
                    f"<div style='margin-top: 10px; margin-bottom: 12px;'>"
                    f"<a href='{sr_url}' target='_blank' style='display: inline-block; padding: 8px 16px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
                    f"👉 View Service Request"
                    f"</a>"
                    f"</div>"
                    f"<p>Best regards,<br/>HR Team</p>"
                )
                try:
                    channel = self.env["discuss.channel"].sudo()._get_or_create_chat(partners_to=[requestor_partner_id])
                    channel.message_post(
                        body=body,
                        message_type="comment",
                        subtype_xmlid="mail.mt_comment",
                    )
                except Exception:
                    pass
                try:
                    emp_partner = emp.user_id.partner_id
                    self.env['bus.bus']._sendone(emp_partner, 'simple_notification', {
                        'title': _('Service Request Completed'),
                        'message': _('Your Service Request %s has been successfully Completed by HR.') % record.reference,
                        'type': 'success',
                        'sticky': False,
                    })
                except Exception as be:
                    _logger.warning("Failed to send completion bus toast: %s", be)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Completed Successfully'),
                'message': _('Service Request %s has been marked as Completed.') % self.reference,
                'type': 'success',
                'sticky': False,
                'next': {
                    'name': _('Service Request'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'employee.service.request',
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'res_id': self.id,
                    'target': 'current',
                    'context': self.env.context,
                }
            }
        }

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
            "views": [(False, "form")],
            "target": "new",
            "context": {"default_request_id": self.id},
        }

    # =========================================================================
    # SUPPORT LETTER COMPUTATION & REPORT HELPERS
    # =========================================================================

    @api.onchange('include_salary', 'employee_id')
    def _onchange_include_salary(self):
        if self.include_salary and self.employee_id:
            if hasattr(self.employee_id, 'get_experience_letter_salary_info'):
                info = self.employee_id.get_experience_letter_salary_info()
                self.salary = info.get('amount', 0.0)
            elif hasattr(self.employee_id, 'contract_id') and self.employee_id.contract_id:
                self.salary = getattr(self.employee_id.contract_id, 'wage', 0.0) or 0.0
            if hasattr(self, '_compute_support_salary_words'):
                self._compute_support_salary_words()
        elif not self.include_salary:
            self.salary = 0.0
            self.salary_in_words = ""

    @api.depends('salary', 'letter_language')
    def _compute_support_salary_words(self):
        for rec in self:
            if rec.salary:
                if rec.letter_language == 'am':
                    rec.salary_in_words = rec._amount_to_words_am(rec.salary)
                else:
                    rec.salary_in_words = rec._amount_to_words_title_en(rec.salary)
            else:
                rec.salary_in_words = ''

    def _amount_to_words_title_en(self, amt):
        """Convert a numerical amount to English words in Title Case."""
        ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
                'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
                'Seventeen', 'Eighteen', 'Nineteen']
        tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

        def helper(num):
            if num < 20:
                return ones[num]
            elif num < 100:
                rem = num % 10
                return tens[num // 10] + ('-' + ones[rem] if rem else '')
            elif num < 1000:
                rem = num % 100
                return ones[num // 100] + ' Hundred' + (' ' + helper(rem) if rem else '')
            elif num < 1000000:
                thousands = num // 1000
                rem = num % 1000
                return helper(thousands) + ' Thousand' + (' ' + helper(rem) if rem else '')
            elif num < 1000000000:
                millions = num // 1000000
                rem = num % 1000000
                return helper(millions) + ' Million' + (' ' + helper(rem) if rem else '')
            else:
                billions = num // 1000000000
                rem = num % 1000000000
                return helper(billions) + ' Billion' + (' ' + helper(rem) if rem else '')

        amt = round(float(amt or 0.0), 2)
        int_part = int(amt)
        cents = int(round((amt - int_part) * 100))
        res = helper(int_part).strip() if int_part > 0 else 'Zero'
        if cents > 0:
            res += f' and {cents:02d}/100'
        return res

    def _amount_to_words_am(self, amt):
        """Convert a numerical amount to Amharic words."""
        if not amt:
            return "ዜሮ"
        ones = ['', 'አንድ', 'ሁለት', 'ሦስት', 'አራት', 'አምስት', 'ስድስት', 'ሰባት', 'ስምንት', 'ዘጠኝ',
                'አሥር', 'አሥራ አንድ', 'አሥራ ሁለት', 'አሥራ ሦስት', 'አሥራ አራት', 'አሥራ አምስት', 'አሥራ ስድስት',
                'አሥራ ሰባት', 'አሥራ ስምንት', 'አሥራ ዘጠኝ']
        tens = ['', '', 'ሃያ', 'ሠላሳ', 'አርባ', 'ሃምሳ', 'ስድሳ', 'ሰባ', 'ሰማንያ', 'ዘጠና']

        def helper(num):
            if num == 0:
                return ''
            elif num < 20:
                return ones[num]
            elif num < 100:
                rem = num % 10
                return tens[num // 10] + (' ' + ones[rem] if rem else '')
            elif num < 1000:
                hundreds = num // 100
                rem = num % 100
                h_str = (ones[hundreds] + ' መቶ') if hundreds > 1 else 'አንድ መቶ'
                return h_str + (' ' + helper(rem) if rem else '')
            elif num < 1000000:
                thousands = num // 1000
                rem = num % 1000
                return helper(thousands) + ' ሺህ' + (' ' + helper(rem) if rem else '')
            elif num < 1000000000:
                millions = num // 1000000
                rem = num % 1000000
                return helper(millions) + ' ሚሊዮን' + (' ' + helper(rem) if rem else '')
            else:
                billions = num // 1000000000
                rem = num % 1000000000
                return helper(billions) + ' ቢሊዮን' + (' ' + helper(rem) if rem else '')

        amt = round(float(amt or 0.0), 2)
        int_part = int(amt)
        cents = int(round((amt - int_part) * 100))
        res = helper(int_part).strip() if int_part > 0 else 'ዜሮ'
        if cents > 0:
            res += f' ከ {cents:02d}/100 ሳንቲም'
        return res

    def get_barlow_font_faces(self):
        """Loads Barlow font-face CSS rules for wkhtmltopdf."""
        try:
            from .report_font_utils import get_barlow_font_faces_css
            return get_barlow_font_faces_css()
        except Exception:
            return ""

    def get_support_letter_signatory_name(self):
        """Returns signatory name from authorizer, employee, or default POMD."""
        self.ensure_one()
        if self.authorizer_id and self.authorizer_id.name:
            return self.authorizer_id.name
        if self.employee_id and hasattr(self.employee_id, 'get_experience_letter_signatory_name'):
            return self.employee_id.get_experience_letter_signatory_name()
        return "People Operation Management Directorate"

    def get_support_letter_signatory_title(self):
        """Returns signatory title."""
        self.ensure_one()
        if self.authorizer_id and self.authorizer_id.job_id:
            return self.authorizer_id.job_id.name
        if self.employee_id and hasattr(self.employee_id, 'get_experience_letter_signatory_title'):
            return self.employee_id.get_experience_letter_signatory_title()
        return "People Operation Management Directorate"

    def get_support_letter_signature_data(self):
        """Returns structured dictionary with separate signature & stamp base64 data URIs."""
        self.ensure_one()
        if self.employee_id and hasattr(self.employee_id, 'get_experience_letter_signature_data'):
            data = self.employee_id.get_experience_letter_signature_data()
            if self.authorizer_id and self.authorizer_id.name:
                data['signatory_name'] = self.authorizer_id.name
            if self.authorizer_id and self.authorizer_id.job_id:
                data['signatory_title'] = self.authorizer_id.job_id.name
            return data
        if hasattr(self, 'get_letter_signature_data'):
            return self.get_letter_signature_data(doc_type='all')
        return {
            'has_split': False,
            'signature_b64': '',
            'stamp_b64': '',
            'stamp_position': 'right',
            'legacy_b64': self.get_support_letter_signature_stamp(),
            'signatory_name': self.get_support_letter_signatory_name(),
            'signatory_title': self.get_support_letter_signatory_title(),
            'signatory_company': 'Bunna Bank S.C.',
        }

    def get_support_letter_signature_stamp(self):
        """Returns authorized signature and stamp base64 data URI."""
        self.ensure_one()
        if self.employee_id and hasattr(self.employee_id, 'get_experience_letter_signature_stamp'):
            return self.employee_id.get_experience_letter_signature_stamp()
        return ""

    def get_support_letter_salutation(self):
        """Returns salutation (Mr. / Ms. or አቶ / ወ/ሮ / ወ/ሪት)."""
        self.ensure_one()
        is_am = self.letter_language == 'am'
        gen = (self.employee_gender or '').lower()
        if 'female' in gen or 'f' == gen:
            return 'ወ/ሮ / ወ/ሪት' if is_am else 'Ms.'
        return 'አቶ' if is_am else 'Mr.'

    def get_support_letter_pronouns(self):
        """Returns third-person pronouns for English support letter."""
        self.ensure_one()
        if self.employee_id and hasattr(self.employee_id, 'get_experience_letter_pronouns'):
            return self.employee_id.get_experience_letter_pronouns()
        gen = (self.employee_gender or '').lower()
        is_female = 'female' in gen or 'f' == gen
        return {
            'subj': 'She' if is_female else 'He',
            'subj_lower': 'she' if is_female else 'he',
            'obj': 'her' if is_female else 'him',
            'poss': 'her' if is_female else 'his',
            'poss_cap': 'Her' if is_female else 'His',
        }

    def get_support_letter_salary_info(self):
        """Returns dictionary of formatted salary figures and words in English and Amharic."""
        self.ensure_one()
        wage = self.salary or 0.0
        fig_str = f"{wage:,.2f}" if wage else "0.00"
        words_en = self._amount_to_words_title_en(wage) if wage else "Zero"
        words_am = self._amount_to_words_am(wage) if wage else "ዜሮ"
        return {
            'amount': wage,
            'figure': fig_str,
            'words': words_en,
            'words_am': words_am,
        }

    def get_support_letter_hire_date_str(self):
        """Returns formatted hire date string."""
        self.ensure_one()
        if self.hire_date:
            if self.letter_language == 'am':
                return self.hire_date.strftime('%Y-%m-%d')
            return self.hire_date.strftime('%B %d, %Y')
        if self.employee_id and hasattr(self.employee_id, 'get_experience_letter_start_date'):
            return self.employee_id.get_experience_letter_start_date()
        today = fields.Date.context_today(self)
        if self.letter_language == 'am':
            return today.strftime('%Y-%m-%d')
        return today.strftime('%B %d, %Y')

    def action_print_support_letter(self):
        """Print the Support Letter QWeb PDF report."""
        self.ensure_one()
        if self.status != 'completed':
            raise UserError(_("You can only print the Support Letter once the request is approved and completed."))
        return self.env.ref('hr_employee_custom.action_report_support_letter').report_action(self)
