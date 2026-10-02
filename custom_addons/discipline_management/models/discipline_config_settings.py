# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    discipline_sla_target_days = fields.Integer(
        string='Disciplinary SLA Target (Working Days)',
        default=10,
        config_parameter='discipline.sla_target_days',
        help='Standard SLA resolution window in working days for disciplinary cases.'
    )

    discipline_appeal_window_days = fields.Integer(
        string='Appeal Submission Window (Working Days)',
        default=10,
        config_parameter='discipline.appeal_window_days',
        help='Maximum number of working days an employee has to submit an appeal after receiving notice.'
    )

    discipline_max_suspension_days = fields.Integer(
        string='Maximum Precautionary Suspension (Days)',
        default=30,
        config_parameter='discipline.max_suspension_days',
        help='Maximum allowed duration in working days for precautionary suspension.'
    )

    discipline_coach_max_punishment = fields.Selection([
        ('verbal_warning', 'Verbal Warning Only (Level 5 Minor)'),
        ('first_warning_penalty', 'Up to 1st Written Warning (Level 4 Low)'),
        ('second_warning_penalty', 'Up to 2nd Written Warning (Level 3 Medium)'),
        ('final_warning_penalty', 'Up to Final Written Warning (Level 2 High)'),
    ], string='Direct Coach Max Punishment Authority',
       default='final_warning_penalty',
       config_parameter='discipline.coach_max_punishment',
       help='Maximum disciplinary sanction a Direct Coach / Line Manager is authorized to directly enforce without escalating to the Disciplinary Committee.')

    absence_warning_consecutive_days = fields.Integer(
        string='Consecutive Absence for Final Warning (Days)',
        default=3,
        config_parameter='discipline.absence_warning_consecutive_days',
        help='Number of consecutive unexcused absence days that automatically triggers a Final Written Warning.'
    )

    absence_dismissal_consecutive_days = fields.Integer(
        string='Consecutive Absence for Dismissal (Days)',
        default=5,
        config_parameter='discipline.absence_dismissal_consecutive_days',
        help='Number of consecutive unexcused absence days that automatically triggers a Critical Misconduct / Dismissal case.'
    )

    absence_cumulative_days_threshold = fields.Integer(
        string='Cumulative Absence Threshold (Days)',
        default=2,
        config_parameter='discipline.absence_cumulative_days_threshold',
        help='Number of cumulative unexcused absence days within rolling period to trigger minor disciplinary action.'
    )

    enable_force_checkout_discipline = fields.Boolean(
        string='Enable Force Check-Out Disciplinary Cases',
        default=False,
        config_parameter='discipline.enable_force_checkout_discipline',
        help='If checked, repeated force check-outs exceeding the threshold will trigger minor disciplinary cases.'
    )

    attendance_force_checkout_threshold = fields.Integer(
        string='Forced Check-Out Threshold Count',
        default=3,
        config_parameter='discipline.attendance_force_checkout_threshold',
        help='Number of forced check-out violations within rolling period to trigger disciplinary action (when enabled).'
    )

    attendance_late_minutes_threshold = fields.Integer(
        string='Cumulative Late Time Threshold (Minutes)',
        default=60,
        config_parameter='discipline.attendance_late_minutes_threshold',
        help='Total cumulative late duration in minutes across evaluation period to trigger disciplinary action.'
    )

    attendance_lateness_threshold = fields.Integer(
        string='Late Time Count Threshold (Legacy)',
        default=3,
        config_parameter='discipline.attendance_lateness_threshold',
        help='Legacy count threshold.'
    )

    attendance_rolling_days = fields.Integer(
        string='Attendance Violation Rolling Period (Days)',
        default=30,
        config_parameter='discipline.attendance_rolling_days',
        help='Rolling evaluation window in days for monitoring attendance thresholds.'
    )

    # Master Governance Role Configuration (Dynamic Resolution Engine)
    discipline_cpco_user_id = fields.Many2one(
        'res.users',
        string='Disciplinary Committee Chair (CPCO)',
        config_parameter='discipline.cpco_user_id',
        help='Designated user acting as the Chief People & Culture Officer (Committee Chairperson & Managerial Suspension Approver).'
    )

    discipline_secretary_user_id = fields.Many2one(
        'res.users',
        string='Committee Secretary (POMD Director)',
        config_parameter='discipline.secretary_user_id',
        help='Designated user acting as the People Operations Directorate Director (Committee Secretary).'
    )

    discipline_legal_user_id = fields.Many2one(
        'res.users',
        string='Legal Directorate Representative',
        config_parameter='discipline.legal_user_id',
        help='Designated user acting as the Legal Services Directorate Director / Representative.'
    )

    discipline_union_user_id = fields.Many2one(
        'res.users',
        string='Labour Union Representative',
        config_parameter='discipline.union_user_id',
        help='Designated user representing the Bank Labour Union in all Disciplinary Committee meetings.'
    )

    discipline_audit_user_id = fields.Many2one(
        'res.users',
        string='Internal Audit Directorate Director',
        config_parameter='discipline.audit_user_id',
        help='Designated user acting as the Internal Audit Directorate Director.'
    )

