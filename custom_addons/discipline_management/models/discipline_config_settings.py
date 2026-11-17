# -*- coding: utf-8 -*-
from odoo import models, fields, api


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
        default=5,
        config_parameter='discipline_management.appeal_window_days',
        help='Maximum number of working days an employee has to submit an appeal after receiving notice.'
    )

    discipline_max_suspension_days = fields.Integer(
        string='Maximum Precautionary Suspension (Days)',
        default=30,
        config_parameter='discipline.max_suspension_days',
        help='Maximum allowed duration in working days for precautionary suspension.'
    )

    discipline_investigation_target_days = fields.Integer(
        string='Investigation Target Window (Working Days)',
        default=10,
        config_parameter='discipline.investigation_target_days',
        help='Default target completion window in working days for internal audit investigations.'
    )

    discipline_coach_max_punishment = fields.Selection([
        ('verbal_warning', 'Verbal Warning Only (Level 5 Minor)'),
        ('first_warning_penalty', 'Up to 1st Written Warning (Level 4 Low)'),
        ('second_warning_penalty', 'Up to 2nd Written Warning (Level 3 Medium)'),
        ('final_warning_penalty', 'Up to Final Written Warning (Level 2 High)'),
        ('dismissal', 'Up to Dismissal / Separation (Level 1 Critical)'),
    ], string='Direct Coach Max Punishment Authority',
       default='final_warning_penalty',
       config_parameter='discipline.coach_max_punishment',
       help='Maximum disciplinary sanction a Direct Coach / Line Manager is authorized to directly enforce without escalating to the Disciplinary Committee.')

    discipline_enable_email_notifications = fields.Boolean(
        string='Enable External Email Notifications',
        default=False,
        config_parameter='discipline.enable_email_notifications',
        help='When enabled, formal disciplinary actions and warnings dispatch external SMTP emails to followers. Keep disabled on test and development databases without active mail servers.'
    )

    enable_attendance_discipline_cases = fields.Boolean(
        string='Enable Automated Attendance Disciplinary Cases',
        default=False,
        config_parameter='discipline.enable_attendance_discipline_cases',
        help='When enabled, the background engine scans attendance and lateness to generate disciplinary cases. Keep disabled on demo and staging databases.'
    )

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

    discipline_system_launch_date = fields.Date(
        string='Disciplinary System Go-Live Date',
        help='Initial start date for automated disciplinary tracking. Absences prior to this date will never be evaluated by the nightly cron.'
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

    discipline_notice_language = fields.Selection([
        ('amharic', 'Amharic (አማርኛ)'),
        ('english', 'English'),
    ], string='Default Notice Letter Language',
       default='amharic',
       config_parameter='discipline.default_notice_language',
       help='Official default language for disciplinary warning letters and notice memos across the Bank.')

    discipline_bank_stamp = fields.Binary(
        related='company_id.discipline_bank_stamp',
        readonly=False,
        string='Official Circular Bank Stamp',
        help='Official circular seal of Bunna Bank stamped onto all formal warning and decision notices.'
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        val = ICP.get_param('discipline.system_launch_date', default=False)
        res.update(
            discipline_system_launch_date=fields.Date.from_string(val) if val else False,
        )
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        if self.discipline_system_launch_date:
            ICP.set_param('discipline.system_launch_date', fields.Date.to_string(self.discipline_system_launch_date))
        else:
            ICP.set_param('discipline.system_launch_date', '')
        if self.discipline_appeal_window_days:
            ICP.set_param('discipline.appeal_window_days', self.discipline_appeal_window_days)
            ICP.set_param('discipline_management.appeal_window_days', self.discipline_appeal_window_days)
            active_cases = self.env['discipline.case'].sudo().search([('state', 'in', ('enforced', 'appealed', 'closed'))])
            if active_cases:
                active_cases._compute_appeal_deadline()
        if self.discipline_sla_target_days:
            ICP.set_param('discipline.sla_target_days', self.discipline_sla_target_days)
            ICP.set_param('discipline_management.sla_target_days', self.discipline_sla_target_days)
        # Automatically synchronize technical group assignments when designated in settings
        if self.discipline_legal_user_id:
            legal_group = self.env.ref('discipline_management.group_discipline_legal', raise_if_not_found=False)
            if legal_group and self.discipline_legal_user_id not in legal_group.user_ids:
                legal_group.sudo().write({'user_ids': [(4, self.discipline_legal_user_id.id)]})

        if self.discipline_audit_user_id:
            audit_group = self.env.ref('discipline_management.group_discipline_auditor', raise_if_not_found=False)
            if audit_group and self.discipline_audit_user_id not in audit_group.user_ids:
                audit_group.sudo().write({'user_ids': [(4, self.discipline_audit_user_id.id)]})

        if self.discipline_secretary_user_id:
            pomd_dir_group = self.env.ref('discipline_management.group_discipline_pomd_director', raise_if_not_found=False)
            if pomd_dir_group and self.discipline_secretary_user_id not in pomd_dir_group.user_ids:
                pomd_dir_group.sudo().write({'user_ids': [(4, self.discipline_secretary_user_id.id)]})

        if self.discipline_cpco_user_id:
            cpco_group = self.env.ref('discipline_management.group_discipline_cpco', raise_if_not_found=False)
            if cpco_group and self.discipline_cpco_user_id not in cpco_group.user_ids:
                cpco_group.sudo().write({'user_ids': [(4, self.discipline_cpco_user_id.id)]})




class ResCompany(models.Model):
    _inherit = 'res.company'

    discipline_bank_stamp = fields.Binary(
        string='Official Circular Bank Stamp',
        help='Official circular seal of Bunna Bank stamped onto all formal warning and decision notices.'
    )


class ResUsers(models.Model):
    _inherit = 'res.users'

    discipline_digital_signature = fields.Binary(
        string='Saved Digital Signature',
        copy=False,
        help='Saved digital signature used across disciplinary decisions.'
    )
    discipline_assigned_executive_id = fields.Many2one(
        'res.users',
        string='Assigned Executive Principal',
        help='The executive officer (CEO, Chief, or Directorate Director) that this Executive Assistant or Secretary supports.'
    )
    discipline_effective_boss_id = fields.Many2one(
        'res.users',
        string='Effective Executive Boss',
        compute='_compute_discipline_effective_boss',
        store=False,
        help='Effective executive authority supported by this user, resolved from explicit assignment or HR hierarchy.'
    )

    def _compute_discipline_effective_boss(self):
        for user in self:
            boss = user.discipline_assigned_executive_id
            if not boss and user.employee_id and user.employee_id.parent_id and user.employee_id.parent_id.user_id:
                boss = user.employee_id.parent_id.user_id
            if not boss and user.employee_id and user.employee_id.job_id:
                job_name = (user.employee_id.job_id.name or '').lower()
                if 'ceo' in job_name or 'president' in job_name:
                    boss = self.env['hr.employee'].sudo().get_ceo_user()
            user.discipline_effective_boss_id = boss

    def get_assigned_secretary_users(self):
        """Find secretaries assigned to this executive user."""
        self.ensure_one()
        sec_group = self.env.ref('discipline_management.group_discipline_secretary', raise_if_not_found=False)
        if not sec_group:
            return self.env['res.users']
        return sec_group.user_ids.filtered(
            lambda u: u.discipline_assigned_executive_id == self or 
                      (u.employee_id and u.employee_id.parent_id and u.employee_id.parent_id.user_id == self)
        )

    def _register_hook(self):
        super()._register_hook()
        self._auto_grant_discipline_user_baseline()

    @api.model
    def _auto_grant_discipline_user_baseline(self):
        """Ensure base.group_user implies group_discipline_user and backfill existing users."""
        try:
            cr = self.env.cr
            # 1. Ensure base.group_user implies group_discipline_user
            cr.execute("""
                INSERT INTO res_groups_implied_rel (gid, hid)
                SELECT b.res_id, d.res_id
                FROM ir_model_data b, ir_model_data d
                WHERE b.module = 'base' AND b.name = 'group_user'
                  AND d.module = 'discipline_management' AND d.name = 'group_discipline_user'
                ON CONFLICT DO NOTHING;
            """)
            # 2. Backfill User / Employee baseline to all internal bank users
            cr.execute("""
                INSERT INTO res_groups_users_rel (gid, uid)
                SELECT d.res_id, r.uid
                FROM ir_model_data d
                JOIN res_groups_users_rel r ON r.gid = (
                    SELECT res_id FROM ir_model_data WHERE module = 'base' AND name = 'group_user' LIMIT 1
                )
                WHERE d.module = 'discipline_management' AND d.name = 'group_discipline_user'
                  AND NOT EXISTS (
                      SELECT 1 FROM res_groups_users_rel x 
                      WHERE x.gid = d.res_id AND x.uid = r.uid
                  );
            """)
        except Exception:
            pass
