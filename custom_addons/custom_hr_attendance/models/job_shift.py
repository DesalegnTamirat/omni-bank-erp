from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import time


class JobShift(models.Model):
    _name = "job.shift"
    _description = "Job Shift"
    _order = "start_time"
    _rec_names_search = ['name', 'code', 'time_range']

    active = fields.Boolean(string="Active", default=True, index=True)
    name = fields.Char(string="Shift Name", required=True)
    code = fields.Char(string="Code", required=False, copy=False)

    @api.onchange('name')
    def _onchange_name_generate_code(self):
        """ Automatically generate and fill shift code as soon as shift name is entered """
        if self.name and (not self.code or self.code in (_('New'), 'New')):
            seq_code = self.env['ir.sequence'].next_by_code('job.shift')
            if not seq_code:
                max_id = self.env['job.shift'].sudo().search([], order='id desc', limit=1).id or 0
                seq_code = f"SH-{max_id + 1:04d}"
            self.code = seq_code

    @api.depends('name', 'time_range')
    def _compute_display_name(self):
        for s in self:
            if s.time_range and s.time_range not in (s.name or ''):
                s.display_name = f"{s.name} ({s.time_range})"
            else:
                s.display_name = s.name or _("Unnamed Shift")

    def _get_active_live_attendances(self):
        """ Returns any open attendance records (check_out = False) active today under this shift. """
        self.ensure_one()
        today = fields.Date.context_today(self)
        att_obj = self.env['hr.attendance'].sudo()

        # 1. Employees via Job Position Exceptions
        jpe_emps = self.env['job.position.exception'].sudo().search([
            ('shift_id', '=', self.id),
            ('status', '=', 'active'),
            ('active', '=', True),
            ('start_date', '<=', today),
            '|', ('end_date', '=', False), ('end_date', '>=', today)
        ]).mapped('employee_id')

        # 2. Employees via Location Based Exceptions
        lbe_records = self.env['location.based.exception'].sudo().search([
            ('shift_id', '=', self.id),
            ('state', '=', 'active'),
            ('active', '=', True),
            ('start_date', '<=', today),
            '|', ('end_date', '=', False), ('end_date', '>=', today)
        ])
        lbe_ous = self.env['operating.unit'].browse()
        for lbe in lbe_records:
            lbe_ous |= (lbe.operating_unit_ids or lbe.operating_unit)
        lbe_emps = self.env['hr.employee'].sudo().search([
            ('default_operating_unit_id', 'in', lbe_ous.ids),
            ('active', '=', True)
        ]) if lbe_ous else self.env['hr.employee'].browse()

        # 3. Employees via Weekly Roster Lines for Today
        roster_emps = self.env['hr.employee'].browse()
        if 'job.position.roster.line' in self.env:
            roster_emps = self.env['job.position.roster.line'].sudo().search([
                ('shift_id', '=', self.id),
                ('date', '=', today)
            ]).mapped('employee_id')

        all_target_emps = (jpe_emps | lbe_emps | roster_emps)
        if not all_target_emps:
            return att_obj.browse()

        return att_obj.search([
            ('employee_id', 'in', all_target_emps.ids),
            ('check_out', '=', False),
            ('date', '=', today)
        ])

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager') and not self.env.is_superuser():
            raise UserError(_("Only Attendance Administrators can create new job shift schedules."))
        for vals in vals_list:
            if vals.get('code', _('New')) in (_('New'), False, ''):
                seq_code = self.env['ir.sequence'].next_by_code('job.shift')
                if not seq_code:
                    max_id = self.env['job.shift'].sudo().search([], order='id desc', limit=1).id or 0
                    seq_code = f"SH-{max_id + 1:04d}"
                vals['code'] = seq_code

            if vals.get('scope_type') == 'branches':
                vals['applies_to_branches'] = True
            elif vals.get('scope_type') in ('all', 'specific'):
                vals['applies_to_branches'] = False
            elif vals.get('applies_to_branches') is True and 'scope_type' not in vals:
                vals['scope_type'] = 'branches'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager') and not self.env.is_superuser():
            raise UserError(_("Only Attendance Administrators can modify job shift schedules."))

        # Guard critical shift parameters while live attendances are in progress
        critical_fields = {'start_time', 'end_time', 'is_night_shift', 'has_lunch_break', 'lunch_start_time', 'lunch_duration', 'active'}
        is_module_loading = bool(self.env.context.get('install_mode'))
        if not self.env.context.get('bypass_checkin_guard') and not is_module_loading:
            for shift in self:
                really_changed = False
                for f in critical_fields:
                    if f in vals:
                        curr = getattr(shift, f)
                        val = vals[f]
                        if isinstance(curr, float) and isinstance(val, (int, float)):
                            if abs(curr - float(val)) > 0.0001:
                                really_changed = True
                                break
                        elif curr != val:
                            really_changed = True
                            break
                if really_changed:
                    open_atts = shift._get_active_live_attendances()
                    if open_atts:
                        emp_sample = ", ".join(open_atts.mapped('employee_id.name')[:5])
                        raise UserError(_(
                            "Cannot Modify Active Shift '%(shift_name)s':\n\n"
                            "%(count)d employee(s) (including: %(emps)s) are currently clocked in under this shift today.\n"
                            "Modifying shift hours or deactivating the shift while live sessions are in progress "
                            "will corrupt their exit and lateness calculations.\n\n"
                            "Please wait until all employees complete checkout before modifying this shift."
                        ) % {
                            'shift_name': shift.name,
                            'count': len(open_atts),
                            'emps': emp_sample,
                        })

        if vals.get('scope_type') == 'branches':
            vals['applies_to_branches'] = True
        elif vals.get('scope_type') in ('all', 'specific'):
            vals['applies_to_branches'] = False
        elif vals.get('applies_to_branches') is True and 'scope_type' not in vals:
            vals['scope_type'] = 'branches'
        return super().write(vals)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB with active usage guards """
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager') and not self.env.is_superuser():
            raise UserError(_("Only Attendance Administrators can delete job shift schedules."))
        today = fields.Date.context_today(self)
        for rec in self:
            if not self.env.context.get('bypass_checkin_guard'):
                open_atts = rec._get_active_live_attendances()
                if open_atts:
                    emp_sample = ", ".join(open_atts.mapped('employee_id.name')[:5])
                    raise UserError(_(
                        "Cannot Delete/Archive Shift '%(shift_name)s':\n\n"
                        "%(count)d employee(s) (including: %(emps)s) are currently on duty under this shift today.\n"
                        "Please wait until employees check out before archiving this shift."
                    ) % {
                        'shift_name': rec.name,
                        'count': len(open_atts),
                        'emps': emp_sample,
                    })
                # Check active exception dependencies
                has_active_lbe = self.env['location.based.exception'].sudo().search_count([
                    ('shift_id', '=', rec.id),
                    ('state', '=', 'active'),
                    ('active', '=', True),
                    ('start_date', '<=', today),
                    '|', ('end_date', '=', False), ('end_date', '>=', today)
                ])
                has_active_jpe = self.env['job.position.exception'].sudo().search_count([
                    ('shift_id', '=', rec.id),
                    ('status', '=', 'active'),
                    ('active', '=', True),
                    ('start_date', '<=', today),
                    '|', ('end_date', '=', False), ('end_date', '>=', today)
                ])
                if has_active_lbe or has_active_jpe:
                    raise UserError(_(
                        "Cannot Delete/Archive Shift '%s':\n\n"
                        "This shift is actively assigned to %d location exception(s) and %d employee exception(s).\n"
                        "Please reassign or end those shift exceptions before deleting this shift."
                    ) % (rec.name, has_active_lbe, has_active_jpe))
            rec.write({'active': False})
        return True

    start_time = fields.Float(
        string="Start Time",
        required=True,
        help="Start time in 24h format (e.g. 7.0 = 07:00)"
    )

    end_time = fields.Float(
        string="End Time",
        required=True,
        help="End time in 24h format (e.g. 23.0 = 23:00)"
    )

    is_night_shift = fields.Boolean(
        string="Night Shift",
        help="Enable if the shift crosses midnight or operates during night hours"
    )

    @api.onchange('start_time', 'end_time')
    def _onchange_night_shift_visibility(self):
        s_time = self.start_time or 0.0
        e_time = self.end_time or 0.0
        is_cross_midnight = (e_time <= s_time) and (s_time > 0 or e_time > 0)
        touches_night = (
            s_time >= 20.0 or
            (s_time > 0 and s_time < 6.0) or
            e_time > 20.0 or
            (e_time <= 6.0 and e_time > 0.0)
        )
        if is_cross_midnight:
            self.is_night_shift = True
        elif not (is_cross_midnight or touches_night):
            self.is_night_shift = False

    time_range = fields.Char(
        string="Time Range",
        compute="_compute_time_range",
        store=True
    )

    # -------------------------
    # LUNCH BREAK CONFIGURATION
    # -------------------------
    has_lunch_break = fields.Boolean(
        string="Includes Lunch Break",
        default=False,
        help="Check if this shift includes a shift-specific lunch break."
    )
    lunch_start_time = fields.Float(
        string="Lunch Start Time",
        help="Lunch start time in 24h format (e.g. 12.0 = 12:00)"
    )
    lunch_duration = fields.Float(
        string="Lunch Duration (Hours)",
        default=1.0,
        help="Lunch break duration in hours (e.g. 1.0 = 1 hour)"
    )

    # -------------------------
    # APPLICABILITY SCOPE
    # -------------------------
    scope_type = fields.Selection([
        ('all', 'Bank-wide (All Operating Units & Head Office)'),
        ('branches', 'All Branches / Districts Only (Excludes Head Office)'),
        ('specific', 'Specific Work Units (Departments / Operating Units)'),
    ], string="Applicability Scope", default='all', required=True)

    applies_to_branches = fields.Boolean(
        string="Applies to All Branches / Districts",
        default=False,
        help="If enabled, this shift is applicable to all branch/district work units automatically."
    )
    operating_unit_ids = fields.Many2many(
        'operating.unit',
        'job_shift_operating_unit_rel',
        'shift_id',
        'operating_unit_id',
        string="Applicable Operating Units"
    )
    department_ids = fields.Many2many(
        'hr.department',
        'job_shift_department_rel',
        'shift_id',
        'department_id',
        string="Applicable Departments"
    )

    scope_description = fields.Char(
        string="Scope Summary",
        compute="_compute_scope_description"
    )

    @api.depends('scope_type', 'department_ids', 'operating_unit_ids')
    def _compute_scope_description(self):
        for rec in self:
            if rec.scope_type == 'all':
                rec.scope_description = "Bank-wide: This shift is applicable to all employees across all Branches, District Offices, and Head Office departments."
            elif rec.scope_type == 'branches':
                rec.scope_description = "All Branches & Districts: This shift is applicable to all branch and district staff across the bank (automatically excludes Head Office)."
            elif rec.scope_type == 'specific':
                dept_count = len(rec.department_ids)
                ou_count = len(rec.operating_unit_ids)
                if not dept_count and not ou_count:
                    rec.scope_description = "Specific Scope: Please select at least one Department or Operating Unit below."
                elif dept_count and not ou_count:
                    rec.scope_description = f"Specific Scope: Applies to {dept_count} selected department(s) and their branch networks."
                elif not dept_count and ou_count:
                    rec.scope_description = f"Specific Scope: Applies specifically to {ou_count} selected operating unit(s)."
                else:
                    rec.scope_description = f"Specific Scope: Applies to {dept_count} department(s) and {ou_count} operating unit(s)."
            else:
                rec.scope_description = ""

    @api.onchange('scope_type')
    def _onchange_scope_type(self):
        if self.scope_type == 'all':
            self.applies_to_branches = False
            self.department_ids = [(5, 0, 0)]
            self.operating_unit_ids = [(5, 0, 0)]
        elif self.scope_type == 'branches':
            self.applies_to_branches = True
            self.department_ids = [(5, 0, 0)]
            self.operating_unit_ids = [(5, 0, 0)]
        elif self.scope_type == 'specific':
            self.applies_to_branches = False
        self._compute_allowed_operating_unit_ids()
        return {'domain': {'operating_unit_ids': [('id', 'in', self.allowed_operating_unit_ids.ids)]}}

    allowed_operating_unit_ids = fields.Many2many(
        'operating.unit',
        compute='_compute_allowed_operating_unit_ids',
        string="Allowed Operating Units Domain"
    )

    @api.model
    def _get_allowed_ous_for_departments(self, department_records):
        """
        Given a recordset of hr.department, resolves all applicable operating units:
        1. If 'Head Office' department is selected: includes all Head Office operating units
           (work_unit_type = 'head_office', name ilike 'Head Office', code = 'HO', etc.).
        2. Direct links: OUs where ou.department is in department_records or ou.id is d.operating_unit_id.
        3. Normalized name matches: exact and whitespace-collapsed name equality.
        4. Token-based matching: handles district departments like 'Dessie District  Office' -> 'Dessie District Office'.
        5. Recursive parent_unit traversal: gathers all child branches/sub-units across multiple levels
           (District -> Branches, Directorate -> Sub-directorates / Divisions / Stores).
        """
        all_ous = self.env['operating.unit'].browse()
        for d in department_records:
            if not d.name:
                continue
            clean_name = " ".join(d.name.split()).strip()
            lower_name = clean_name.lower()

            # 1. Head Office department: match all Head Office operating units
            if lower_name in ('head office', 'head', 'head_office', 'ho', 'head office department') or 'head office' in lower_name:
                ho_ous = self.env['operating.unit'].sudo().search([
                    '|', '|',
                    ('work_unit_type', '=', 'head_office'),
                    ('name', 'ilike', 'Head Office'),
                    ('code', '=ilike', 'HO')
                ])
                all_ous |= ho_ous
                continue

            # 2. Direct relational links
            direct = self.env['operating.unit'].sudo().search([
                '|',
                ('department', '=', d.id),
                ('id', '=', d.operating_unit_id.id if d.operating_unit_id else 0)
            ])

            # 3. Match by normalized name
            direct |= self.env['operating.unit'].sudo().search([('name', '=ilike', clean_name)])

            # 4. Token-based matching (handles district names e.g. 'Dessie District  Office')
            core_words = [w for w in clean_name.split() if w.lower() not in (
                'office', 'dept', 'department', 'division', 'unit', 'and', '&', 'directorate', 'management', 'service', 'services'
            )]
            if core_words:
                domain = [('name', 'ilike', core_words[0])]
                for w in core_words[1:]:
                    domain.append(('name', 'ilike', w))
                direct |= self.env['operating.unit'].sudo().search(domain)

            all_ous |= direct

        # 5. Recursive parent_unit traversal (District -> Branches, Directorate -> Sub-units across all depths)
        if all_ous:
            curr = all_ous
            while curr:
                children = self.env['operating.unit'].sudo().search([
                    ('parent_unit', 'in', curr.ids),
                    ('id', 'not in', all_ous.ids)
                ])
                if not children:
                    break
                all_ous |= children
                curr = children

        return all_ous

    @api.depends('department_ids', 'scope_type')
    def _compute_allowed_operating_unit_ids(self):
        for record in self:
            if record.scope_type != 'specific':
                record.allowed_operating_unit_ids = self.env['operating.unit'].browse()
                continue

            if not record.department_ids:
                # If no department selected, allow selecting any active Operating Unit
                record.allowed_operating_unit_ids = self.env['operating.unit'].sudo().search([('active', '=', True)])
            else:
                record.allowed_operating_unit_ids = self._get_allowed_ous_for_departments(record.department_ids)

    @api.onchange('department_ids')
    def _onchange_department_ids(self):
        self._compute_allowed_operating_unit_ids()
        if self.operating_unit_ids and self.allowed_operating_unit_ids:
            valid_ous = self.operating_unit_ids.filtered(lambda ou: ou in self.allowed_operating_unit_ids)
            self.operating_unit_ids = [(6, 0, valid_ous.ids)]
        return {'domain': {'operating_unit_ids': [('id', 'in', self.allowed_operating_unit_ids.ids)]}}

    # -------------------------
    # COMPUTE
    # -------------------------
    @staticmethod
    def _float_to_time(float_time):
        hours = int(float_time)
        minutes = int(round((float_time - hours) * 60))
        return time(hours, minutes)

    @api.depends('start_time', 'end_time', 'is_night_shift')
    def _compute_time_range(self):
        for record in self:
            start = self._float_to_time(record.start_time)
            end = self._float_to_time(record.end_time)

            if record.is_night_shift:
                record.time_range = f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')} (Next Day)"
            else:
                record.time_range = f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"

    # -------------------------
    # CONSTRAINTS
    # -------------------------
    @api.constrains('start_time', 'end_time', 'is_night_shift', 'has_lunch_break', 'lunch_start_time', 'lunch_duration')
    def _check_time_validity(self):
        for record in self:
            if record.start_time < 0 or record.end_time < 0:
                raise ValidationError("Time values cannot be negative.")

            if record.start_time >= 24 or record.end_time > 24:
                raise ValidationError("Time must be within 24-hour range.")

            if not record.is_night_shift and record.end_time <= record.start_time:
                raise ValidationError(
                    "End time must be after start time unless it is a night shift."
                )

            if record.has_lunch_break:
                if record.lunch_start_time < 0 or record.lunch_duration <= 0:
                    raise ValidationError("Lunch start time cannot be negative and lunch duration must be greater than zero.")
                if record.lunch_start_time >= 24:
                    raise ValidationError("Lunch start time must be within 24-hour range.")

                lunch_end = record.lunch_start_time + record.lunch_duration
                if not record.is_night_shift:
                    if record.lunch_start_time < record.start_time or lunch_end > record.end_time:
                        raise ValidationError("Lunch break must fall within the shift start time and end time.")
                else:
                    pass

    def is_applicable_for(self, operating_unit=None, department=None, assigner_operating_unit=None, assigner_department=None):
        self.ensure_one()

        # Rule 1: Bank-wide scope (applies only if scope_type is 'all' and no restrictions exist)
        if self.scope_type == 'all':
            if not self.applies_to_branches and not self.operating_unit_ids and not self.department_ids:
                return True

        # Rule 2: applies_to_branches=True or scope_type == 'branches' -> APPLICABLE to branches except head office
        if self.scope_type == 'branches' or self.applies_to_branches:
            target_ou = operating_unit or assigner_operating_unit
            if target_ou:
                code = (target_ou.code or '').upper()
                name = (target_ou.name or '').upper()
                work_unit_type = getattr(target_ou, 'work_unit_type', '')
                is_head_office = (work_unit_type == 'head_office' or 'HEAD' in code or 'HEAD' in name or 'MAIN' in code or 'MAIN' in name or code == 'HO')
                if is_head_office:
                    return False
            return True

        # Collect OUs to check (both target location/employee OU, assigner/coach OU, and recursive parent units)
        # Safely unwrap _origin to prevent NewId comparison failures during UI onchange
        ous_to_check = []
        for raw_ou in [operating_unit, assigner_operating_unit]:
            if raw_ou:
                ou = getattr(raw_ou, '_origin', raw_ou) or raw_ou
                curr = ou
                while curr and curr not in ous_to_check:
                    ous_to_check.append(curr)
                    curr = curr.parent_unit if hasattr(curr, 'parent_unit') and curr.parent_unit else None

        ou_ids_to_check = set(getattr(o, '_origin', o).id for o in ous_to_check if getattr(o, '_origin', o).id)

        # Rule 3: If operating_unit_ids is specified, location MUST match
        if self.operating_unit_ids:
            shift_ou_ids = set(self.operating_unit_ids.ids)
            if not ou_ids_to_check or not (ou_ids_to_check & shift_ou_ids):
                return False  # Target location does not match restricted operating units

        # Collect Departments to check
        depts_to_check = [d for d in [department, assigner_department] if d]

        # Rule 4: If department_ids is specified, department MUST match
        if self.department_ids:
            dept_matched = False
            if depts_to_check:
                for dept in depts_to_check:
                    curr = getattr(dept, '_origin', dept) or dept
                    while curr:
                        if curr in self.department_ids or curr.id in self.department_ids.ids:
                            dept_matched = True
                            break
                        curr = curr.parent_id

            # Check if target OU matches any allowed operating units derived from the shift's departments
            if not dept_matched and ous_to_check:
                allowed_ous = self.allowed_operating_unit_ids
                if not allowed_ous or len(allowed_ous) == 0:
                    allowed_ous = self._get_allowed_ous_for_departments(self.department_ids)
                allowed_ou_ids = set(allowed_ous.ids)
                if ou_ids_to_check & allowed_ou_ids:
                    dept_matched = True

            if not dept_matched and ous_to_check:
                for ou in ous_to_check:
                    ou_name_clean = " ".join((ou.name or '').split()).lower()
                    parent_name_clean = " ".join((ou.parent_unit.name or '').split()).lower() if hasattr(ou, 'parent_unit') and ou.parent_unit and ou.parent_unit.name else ""
                    for dept in self.department_ids:
                        if not dept.name:
                            continue
                        dept_name_clean = " ".join(dept.name.split()).lower()
                        # Direct or parent name matching
                        if dept_name_clean == ou_name_clean or (parent_name_clean and dept_name_clean == parent_name_clean):
                            dept_matched = True
                            break
                        # Core words matching
                        core_words = [w for w in dept_name_clean.split() if w not in ('office', 'dept', 'department', 'division', 'unit', 'and', '&')]
                        if core_words:
                            if all(w in ou_name_clean for w in core_words) or (parent_name_clean and all(w in parent_name_clean for w in core_words)):
                                dept_matched = True
                                break
                    if dept_matched:
                        break

                    depts_linked = self.env['hr.department'].sudo().search([
                        '|',
                        ('operating_unit_id', '=', ou.id),
                        ('operating_unit', '=', ou.id)
                    ])
                    if any(d in self.department_ids or d.parent_id in self.department_ids for d in depts_linked):
                        dept_matched = True
                        break
                    if hasattr(ou, 'department') and ou.department and (ou.department in self.department_ids or ou.department.parent_id in self.department_ids):
                        dept_matched = True
                        break

            if not dept_matched:
                return False  # Target department does not match restricted departments

        return True

    @api.model
    def get_allowed_shift_ids(self, operating_unit_id=None, department_id=None, assigner_operating_unit_id=None, assigner_department_id=None):
        """
        Returns list of shift IDs allowed for the given target operating unit/department and assigner operating unit/department.
        """
        ou = self.env['operating.unit'].browse(operating_unit_id) if operating_unit_id else False
        dept = self.env['hr.department'].browse(department_id) if department_id else False
        a_ou = self.env['operating.unit'].browse(assigner_operating_unit_id) if assigner_operating_unit_id else False
        a_dept = self.env['hr.department'].browse(assigner_department_id) if assigner_department_id else False

        shifts = self.search([('active', '=', True)])
        allowed = shifts.filtered(lambda s: s.is_applicable_for(
            operating_unit=ou,
            department=dept,
            assigner_operating_unit=a_ou,
            assigner_department=a_dept
        ))
        return allowed.ids
        #return allowed.ids

