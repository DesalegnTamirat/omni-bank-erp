# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


def _format_clean_text(val):
    if not val:
        return False
    if isinstance(val, dict):
        return val.get('en_US') or (list(val.values())[0] if val.values() else False)
    if isinstance(val, str) and (val.startswith('{') or 'en_US' in val):
        try:
            import ast, json
            parsed = ast.literal_eval(val) if val.startswith("{'") else json.loads(val)
            if isinstance(parsed, dict):
                return parsed.get('en_US') or (list(parsed.values())[0] if parsed.values() else val)
        except Exception:
            pass
def _update_employee_job_grade(emp, grade_val):
    if not emp or not grade_val:
        return
    
    vals = {}
    grade_rec = False

    if isinstance(grade_val, int):
        grade_rec = emp.env['employee.grade'].browse(grade_val)
    elif isinstance(grade_val, str) and grade_val.isdigit():
        grade_rec = emp.env['employee.grade'].browse(int(grade_val))
    
    if not grade_rec and isinstance(grade_val, str):
        g_str = grade_val.strip()
        grade_rec = emp.env['employee.grade'].search([
            '|', ('grade_name', '=ilike', g_str), ('grade_code', '=ilike', g_str)
        ], limit=1)
        if not grade_rec and 'grade' in g_str.lower():
            clean_str = g_str.lower().replace('grade', '').strip()
            grade_rec = emp.env['employee.grade'].search([
                '|', ('grade_name', '=ilike', clean_str), ('grade_code', '=ilike', clean_str)
            ], limit=1)

    if grade_rec and grade_rec.exists():
        if hasattr(emp, 'job_grade'):
            vals['job_grade'] = grade_rec.id
        if hasattr(emp, 'grade'):
            vals['grade'] = grade_rec.id

    if hasattr(emp, 'emp_grade'):
        vals['emp_grade'] = str(grade_val)

    if vals:
        emp.write(vals)


class InternalRecruitmentReleaseWizard(models.TransientModel):
    _name = "new.internal.recruitment.release.wizard"
    _description = "Internal Promotion Release Form (Different Work Unit)"

    candidate_id = fields.Many2one(
        "new.internal.recruitment.selected.candidates",
        string="Selected Candidate",
        required=True,
        ondelete="cascade"
    )
    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    current_work_unit = fields.Char(string="Current Work Unit", readonly=True)
    target_work_unit = fields.Char(string="New Placement Work Unit", readonly=True)
    current_position = fields.Char(string="Current Position", readonly=True)
    new_job_position_id = fields.Many2one("hr.job", string="New Job Position", readonly=True)
    new_job_grade = fields.Char(string="New Job Grade", readonly=True)

    coach_id = fields.Many2one(
        "hr.employee",
        string="Releasing Coach / Manager",
        required=True,
        help="The immediate supervisor, coach, or department manager authorizing the employee release."
    )
    release_date = fields.Date(
        string="Release Effective Date",
        default=fields.Date.context_today,
        required=True,
        help="Date when the candidate is officially released from the current work unit."
    )
    handover_status = fields.Selection([
        ('completed', 'Handover Completed'),
        ('pending', 'Pending Handover')
    ], string="Handover Status", default='completed', required=True)

    release_remarks = fields.Text(
        string="Release & Handover Remarks",
        help="Enter any notes, clearance status, or handover details."
    )

    @api.model
    def default_get(self, fields_list):
        res = super(InternalRecruitmentReleaseWizard, self).default_get(fields_list)
        active_id = self.env.context.get('active_id')
        active_model = self.env.context.get('active_model')

        if active_model == 'new.internal.recruitment.selected.candidates' and active_id:
            cand = self.env['new.internal.recruitment.selected.candidates'].browse(active_id)
            if cand:
                parent_rec = cand.new_int_sel_cand
                curr_unit = cand.current_work_unit or (
                    cand.emp_name.default_operating_unit_id.name
                    if cand.emp_name and getattr(cand.emp_name, 'default_operating_unit_id', False)
                    else 'N/A'
                )
                target_unit = cand.preferred_location or (parent_rec.job_location if parent_rec else 'N/A')
                curr_pos = cand.emp_position or (
                    cand.emp_name.job_id.name
                    if cand.emp_name and cand.emp_name.job_id
                    else 'N/A'
                )
                coach = cand.coach_id or (
                    cand.emp_name.coach_id or cand.emp_name.parent_id
                    if cand.emp_name
                    else False
                )

                res.update({
                    'candidate_id': cand.id,
                    'employee_id': cand.emp_name.id if cand.emp_name else False,
                    'current_work_unit': _format_clean_text(curr_unit),
                    'target_work_unit': _format_clean_text(target_unit),
                    'current_position': _format_clean_text(curr_pos),
                    'new_job_position_id': parent_rec.job_position.id if parent_rec and parent_rec.job_position else False,
                    'new_job_grade': _format_clean_text(parent_rec.job_grade) if parent_rec else 'N/A',
                    'coach_id': coach.id if coach else False,
                })
        return res

    def action_confirm_release(self):
        self.ensure_one()
        cand = self.candidate_id
        if not cand or not cand.emp_name:
            raise UserError(_("No valid candidate employee found for release."))

        emp = cand.emp_name
        parent_rec = cand.new_int_sel_cand

        # Apply Job Position, Grade, and Location changes on hr.employee
        vals = {}
        if parent_rec and parent_rec.job_position:
            if hasattr(emp, 'job_id'):
                vals['job_id'] = parent_rec.job_position.id
            if hasattr(emp, 'job_position'):
                vals['job_position'] = parent_rec.job_position.id
            if hasattr(emp, 'department_id') and parent_rec.job_position.department_id:
                vals['department_id'] = parent_rec.job_position.department_id.id

        if parent_rec and parent_rec.job_grade:
            if hasattr(emp, 'emp_grade'):
                vals['emp_grade'] = parent_rec.job_grade

        # Update Work Unit / Location
        target_unit_name = cand.preferred_location or (parent_rec.job_location if parent_rec else False)
        if target_unit_name and hasattr(emp, 'default_operating_unit_id'):
            unit = self.env['operating.unit'].search([('name', '=', target_unit_name)], limit=1)
            if unit:
                vals['default_operating_unit_id'] = unit.id

        if vals:
            emp.write(vals)

        # Update Many2one employee.grade on hr.employee
        _update_employee_job_grade(emp, (parent_rec.job_grade or parent_rec.job_grade_id) if parent_rec else False)

        # Update candidate line status
        cand.write({
            'promotion_status': 'released',
            'release_date': self.release_date,
            'coach_id': self.coach_id.id,
            'release_remarks': self.release_remarks,
            'release_handover': self.handover_status,
        })

        # Post message in chatter
        if parent_rec:
            parent_rec.message_post(
                body=_(
                    "<b>Candidate Release Approved (Different Work Unit)</b><br/>"
                    "• Employee: %s<br/>"
                    "• Releasing Coach/Manager: %s<br/>"
                    "• Release Effective Date: %s<br/>"
                    "• Handover Status: %s<br/>"
                    "• New Position: %s (Grade %s)<br/>"
                    "• New Work Unit Placement: %s<br/>"
                    "• Remarks: %s"
                ) % (
                    emp.name,
                    self.coach_id.name,
                    self.release_date,
                    dict(self._fields['handover_status'].selection).get(self.handover_status, self.handover_status),
                    parent_rec.job_position.name if parent_rec.job_position else 'N/A',
                    parent_rec.job_grade or 'N/A',
                    target_unit_name or 'N/A',
                    self.release_remarks or 'None'
                )
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidate Released & Promoted'),
                'message': _('Employee %s has been successfully released by Coach/Manager and updated to the new placement.') % emp.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
