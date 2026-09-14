# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CbisBulkScheduleWizard(models.TransientModel):
    """
    Bulk Interview Scheduling Wizard (FR-CBIS-010)
    =============================================
    Allows scheduling multiple qualified candidates simultaneously across
    assigned panel members with time slots.
    """
    _name = "cbis.bulk.schedule.wizard"
    _description = "Bulk Candidate Interview Scheduler Wizard"

    session_id = fields.Many2one("cbis.interview.session", string="Target Interview Session", required=True)
    vacancy_id = fields.Many2one(related="session_id.vacancy_id", string="Job Vacancy", readonly=True)
    
    applicant_ids = fields.Many2many(
        "hr.applicant",
        string="Qualified External Applicants",
        domain="[('job_id', '=', job_id)]"
    )
    employee_ids = fields.Many2many("hr.employee", string="Internal Candidates")
    job_id = fields.Many2one(related="session_id.job_id", string="Job Position", readonly=True)

    default_start_time = fields.Datetime(string="First Slot Start Time", default=fields.Datetime.now, required=True)
    slot_interval_minutes = fields.Integer(string="Interval per Candidate (Minutes)", default=30, required=True)

    def action_schedule_bulk(self):
        self.ensure_one()
        current_time = self.default_start_time
        created_lines = []

        # External applicants
        for app in self.applicant_ids:
            created_lines.append({
                "session_id": self.session_id.id,
                "candidate_type": "external",
                "applicant_id": app.id,
                "scheduled_time": current_time,
            })
            current_time += fields.Datetime.timedelta(minutes=self.slot_interval_minutes)

        # Internal employees
        for emp in self.employee_ids:
            created_lines.append({
                "session_id": self.session_id.id,
                "candidate_type": "internal",
                "employee_id": emp.id,
                "scheduled_time": current_time,
            })
            current_time += fields.Datetime.timedelta(minutes=self.slot_interval_minutes)

        if created_lines:
            self.env["cbis.interview.candidate"].create(created_lines)
            
        return {"type": "ir.actions.act_window_close"}
