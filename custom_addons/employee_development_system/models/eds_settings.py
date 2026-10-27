# -*- coding: utf-8 -*-
"""EDS-only settings, accessible without Odoo system administration rights."""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EdsSettings(models.TransientModel):
    _name = 'eds.settings'
    _description = 'Employee Development Settings'

    eds_tna_cycle_start_month = fields.Integer(string='TNA Cycle Start Month')
    eds_tna_submission_days = fields.Integer(string='Submission Window (Working Days)')
    eds_tna_approval_deadline_month = fields.Integer(string='TNA Approval Deadline Month')
    eds_tna_approval_deadline_day = fields.Integer(string='TNA Approval Deadline Day')
    eds_max_tna_courses_per_employee = fields.Integer(string='Max TNA Courses per Employee')
    eds_nomination_require_line_manager = fields.Boolean(string='Require Line Manager Approval Step')
    eds_nomination_require_budget = fields.Boolean(string='Require Budget/HR Approval Step')
    eds_default_class_capacity = fields.Integer(string='Default Session Capacity')
    eds_min_attendance_pct = fields.Float(string='Minimum Attendance % for Certification')
    eds_level2_pass_threshold = fields.Float(string='Level 2 Pass Threshold (%)')
    eds_level3_delay_value = fields.Integer(string='Level 3 Review Delay')
    eds_level3_delay_unit = fields.Selection([
        ('minutes', 'Minutes'), ('hours', 'Hours'), ('days', 'Days'),
        ('weeks', 'Weeks'), ('months', 'Months'),
    ], string='Level 3 Delay Unit')
    eds_course_mapping_sla_days = fields.Integer(string='Course-to-Competency Mapping SLA')
    eds_curriculum_sla_days = fields.Integer(string='Curriculum Development SLA')
    eds_calendar_sla_days = fields.Integer(string='Annual Calendar Generation SLA')
    eds_level1_report_sla_days = fields.Integer(string='Level 1 Evaluation Report SLA')
    eds_sponsorship_min_service_months = fields.Integer(string='Sponsorship Minimum Service (Months)')
    eds_partnership_min_score = fields.Float(string='Learning Partnership Minimum Score')
    eds_rfp_min_providers = fields.Integer(string='Minimum Providers per RFP')
    eds_technical_min_threshold = fields.Float(string='Technical Minimum Threshold (%)')
    eds_technical_financial_blend = fields.Integer(string='Technical / Financial Weight (%)')

    _parameter_defaults = {
        'eds_tna_cycle_start_month': ('eds.tna_cycle_start_month', 4),
        'eds_tna_submission_days': ('eds.tna_submission_days', 10),
        'eds_tna_approval_deadline_month': ('eds.tna_approval_deadline_month', 5),
        'eds_tna_approval_deadline_day': ('eds.tna_approval_deadline_day', 31),
        'eds_max_tna_courses_per_employee': ('eds.max_tna_courses_per_employee', 3),
        'eds_nomination_require_line_manager': ('eds.nomination_require_line_manager', True),
        'eds_nomination_require_budget': ('eds.nomination_require_budget', False),
        'eds_default_class_capacity': ('eds.default_class_capacity', 30),
        'eds_min_attendance_pct': ('eds.min_attendance_pct', 80.0),
        'eds_level2_pass_threshold': ('eds.level2_pass_threshold', 60.0),
        'eds_level3_delay_value': ('eds.level3_delay_value', 60),
        'eds_level3_delay_unit': ('eds.level3_delay_unit', 'days'),
        'eds_course_mapping_sla_days': ('eds.course_mapping_sla_days', 5),
        'eds_curriculum_sla_days': ('eds.curriculum_sla_days', 10),
        'eds_calendar_sla_days': ('eds.calendar_sla_days', 5),
        'eds_level1_report_sla_days': ('eds.level1_report_sla_days', 7),
        'eds_sponsorship_min_service_months': ('eds.sponsorship_min_service_months', 12),
        'eds_partnership_min_score': ('eds.partnership_min_score', 70.0),
        'eds_rfp_min_providers': ('eds.rfp_min_providers', 3),
        'eds_technical_min_threshold': ('eds.technical_min_threshold', 70.0),
        'eds_technical_financial_blend': ('eds.technical_financial_blend', 70),
    }

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        parameters = self.env['ir.config_parameter'].sudo()
        for name in field_names:
            if name not in self._parameter_defaults:
                continue
            key, fallback = self._parameter_defaults[name]
            raw = parameters.get_param(key, str(fallback))
            if isinstance(fallback, bool):
                values[name] = str(raw).lower() in ('true', '1', 'yes')
            elif isinstance(fallback, int):
                values[name] = int(raw)
            elif isinstance(fallback, float):
                values[name] = float(raw)
            else:
                values[name] = raw
        return values

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(list(self._parameter_defaults))
        records = super().create([{**defaults, **vals} for vals in vals_list])
        for record in records:
            record._save_parameters()
        return records

    def write(self, vals):
        result = super().write(vals)
        for record in self:
            record._save_parameters()
        return result

    def _save_parameters(self):
        self.ensure_one()
        if not self.env.user.has_group('employee_development_system.group_eds_admin'):
            raise ValidationError(_('Only an EDS administrator can change EDS settings.'))
        for name in ('eds_tna_cycle_start_month', 'eds_tna_approval_deadline_month'):
            if not 1 <= self[name] <= 12:
                raise ValidationError(_('%s must be between 1 and 12.') % self._fields[name].string)
        if not 1 <= self.eds_tna_approval_deadline_day <= 31:
            raise ValidationError(_('TNA Approval Deadline Day must be between 1 and 31.'))
        for name in (
            'eds_tna_submission_days', 'eds_max_tna_courses_per_employee',
            'eds_default_class_capacity', 'eds_course_mapping_sla_days',
            'eds_curriculum_sla_days', 'eds_calendar_sla_days',
            'eds_level1_report_sla_days', 'eds_sponsorship_min_service_months',
            'eds_rfp_min_providers', 'eds_level3_delay_value',
        ):
            if self[name] < 1:
                raise ValidationError(_('%s must be at least 1.') % self._fields[name].string)
        for name in (
            'eds_min_attendance_pct', 'eds_level2_pass_threshold',
            'eds_partnership_min_score', 'eds_technical_min_threshold',
            'eds_technical_financial_blend',
        ):
            if not 0 <= self[name] <= 100:
                raise ValidationError(_('%s must be between 0 and 100.') % self._fields[name].string)
        if self.eds_level3_delay_unit not in ('minutes', 'hours', 'days', 'weeks', 'months'):
            raise ValidationError(_('Select a valid Level 3 review delay unit.'))
        parameters = self.env['ir.config_parameter'].sudo()
        for name, (key, default_value) in self._parameter_defaults.items():
            parameters.set_param(key, self[name])
