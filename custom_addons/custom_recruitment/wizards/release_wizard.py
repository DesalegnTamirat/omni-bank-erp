# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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


def _resolve_operating_unit(env, cand, parent_rec):
    """
    Robustly resolves the destination operating unit record.
    """
    # 1. From candidate target work unit helper / preferred location
    if hasattr(cand, 'get_target_work_unit_name'):
        target_name = cand.get_target_work_unit_name()
        if target_name:
            ou = env['operating.unit'].search([('name', '=ilike', str(target_name).strip())], limit=1)
            if ou:
                return ou
            ou = env['operating.unit'].search([('name', 'ilike', str(target_name).strip())], limit=1)
            if ou:
                return ou

    target_unit = getattr(cand, 'preferred_location', False)
    if target_unit:
        clean_name = _format_clean_text(target_unit)
        if clean_name:
            ou = env['operating.unit'].search([('name', '=ilike', str(clean_name).strip())], limit=1)
            if ou:
                return ou
            ou = env['operating.unit'].search([('name', 'ilike', str(clean_name).strip())], limit=1)
            if ou:
                return ou

    # 2. From parent recruitment workunit_id
    if parent_rec and getattr(parent_rec, 'workunit_id', False):
        w_id = parent_rec.workunit_id
        if isinstance(w_id, int) and w_id > 0:
            ou = env['operating.unit'].browse(w_id)
            if ou.exists():
                return ou
        elif hasattr(w_id, 'id') and w_id.id:
            return w_id

    # 3. From vacancy operating_unit_id or hiring_details
    vac = False
    if parent_rec:
        vac_id = getattr(parent_rec, 'vacancy_id', False)
        if isinstance(vac_id, int) and vac_id > 0:
            vac = env['job.vacancy'].browse(vac_id)
        elif hasattr(vac_id, 'operating_unit_id') and vac_id:
            vac = vac_id
        if not vac and getattr(parent_rec, 'vacancy_reference', False):
            vac = env['job.vacancy'].search([('reference', '=', parent_rec.vacancy_reference)], limit=1)
    if not vac and getattr(cand, 'vacancy_id', False):
        c_vac_id = cand.vacancy_id
        if isinstance(c_vac_id, int) and c_vac_id > 0:
            vac = env['job.vacancy'].browse(c_vac_id)

    if vac and vac.exists():
        if vac.operating_unit_id:
            return vac.operating_unit_id
        if hasattr(vac, 'hiring_details') and vac.hiring_details:
            for hd in vac.hiring_details:
                if hd.work_unit:
                    return hd.work_unit

    # 4. From parent recruitment job_location string
    if parent_rec and getattr(parent_rec, 'job_location', False):
        loc_str = _format_clean_text(parent_rec.job_location)
        if loc_str:
            ou = env['operating.unit'].search([('name', '=ilike', str(loc_str).strip())], limit=1)
            if ou:
                return ou
            ou = env['operating.unit'].search([('name', 'ilike', str(loc_str).strip())], limit=1)
            if ou:
                return ou

    return False


def _resolve_grade_record(env, grade_val, parent_rec=None):
    """
    Robustly resolves employee.grade record.
    """
    if grade_val:
        if isinstance(grade_val, int) and grade_val > 0:
            rec = env['employee.grade'].browse(grade_val)
            if rec.exists():
                return rec
        elif hasattr(grade_val, '_name') and grade_val._name == 'employee.grade':
            return grade_val
        g_str = _format_clean_text(grade_val)
        if g_str:
            g_str = str(g_str).strip()
            if g_str.isdigit():
                rec = env['employee.grade'].browse(int(g_str))
                if rec.exists():
                    return rec
            rec = env['employee.grade'].search([
                '|', ('grade_name', '=ilike', g_str), ('grade_code', '=ilike', g_str)
            ], limit=1)
            if rec and rec.exists():
                return rec
            if 'grade' in g_str.lower():
                clean_str = g_str.lower().replace('grade', '').strip()
                rec = env['employee.grade'].search([
                    '|', ('grade_name', '=ilike', clean_str), ('grade_code', '=ilike', clean_str)
                ], limit=1)
                if rec and rec.exists():
                    return rec

    # Fallback to parent recruitment / vacancy grade
    if parent_rec:
        if getattr(parent_rec, 'job_grade_id', False):
            g_id = parent_rec.job_grade_id
            if isinstance(g_id, int) and g_id > 0:
                rec = env['employee.grade'].browse(g_id)
                if rec.exists():
                    return rec
            elif hasattr(g_id, 'id') and g_id.id:
                return g_id
        vac_id = getattr(parent_rec, 'vacancy_id', False)
        vac = False
        if isinstance(vac_id, int) and vac_id > 0:
            vac = env['job.vacancy'].browse(vac_id)
        elif hasattr(vac_id, 'grade'):
            vac = vac_id
        if not vac and getattr(parent_rec, 'vacancy_reference', False):
            vac = env['job.vacancy'].search([('reference', '=', parent_rec.vacancy_reference)], limit=1)
        if vac and vac.exists():
            if hasattr(vac, 'grade') and vac.grade:
                return vac.grade
            if hasattr(vac, 'job_grade') and vac.job_grade:
                return vac.job_grade
            if hasattr(vac, 'job_id') and vac.job_id and hasattr(vac.job_id, 'job_grade') and vac.job_id.job_grade:
                return vac.job_id.job_grade
        if hasattr(parent_rec, 'job_position') and parent_rec.job_position:
            if hasattr(parent_rec.job_position, 'job_grade') and parent_rec.job_position.job_grade:
                return parent_rec.job_position.job_grade
            if hasattr(parent_rec.job_position, 'grade') and parent_rec.job_position.grade:
                return parent_rec.job_position.grade

    return False


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
        ('pending', 'Pending Handover'),
    ], string="Handover Status", default='completed', required=True)

    release_remarks = fields.Text(
        string="Release & Handover Remarks",
        help="Enter any notes, clearance status, or handover details."
    )

    @api.model
    def default_get(self, fields_list):
        res = super(InternalRecruitmentReleaseWizard, self).default_get(fields_list)
        active_id = self.env.context.get('default_candidate_id') or self.env.context.get('active_id')
        active_model = self.env.context.get('active_model') or 'new.internal.recruitment.selected.candidates'

        if active_id:
            cand = self.env['new.internal.recruitment.selected.candidates'].browse(active_id)
            if cand and cand.exists():
                emp = cand.emp_name
                parent_rec = cand.new_int_sel_cand

                # Find the linked vacancy record
                vac = False
                if parent_rec:
                    vac_id = getattr(parent_rec, 'vacancy_id', False)
                    if isinstance(vac_id, int) and vac_id > 0:
                        vac = self.env['job.vacancy'].browse(vac_id)
                    elif hasattr(vac_id, 'operating_unit_id') and vac_id:
                        vac = vac_id
                    if not vac and getattr(parent_rec, 'vacancy_reference', False):
                        vac = self.env['job.vacancy'].search([('reference', '=', parent_rec.vacancy_reference)], limit=1)

                if not vac and getattr(cand, 'vacancy_id', False):
                    c_vac_id = cand.vacancy_id
                    if isinstance(c_vac_id, int) and c_vac_id > 0:
                        vac = self.env['job.vacancy'].browse(c_vac_id)

                # 1. Current Position (Reference #1): Candidate's current job position
                curr_pos = cand.get_current_position_name() if hasattr(cand, 'get_current_position_name') else False
                if not curr_pos:
                    curr_pos = cand.emp_position or False
                if not curr_pos and emp:
                    curr_pos = (
                        (emp.job_id.name if getattr(emp, 'job_id', False) and emp.job_id else False) or
                        (emp.job_position.name if hasattr(emp, 'job_position') and emp.job_position and hasattr(emp.job_position, 'name') else False) or
                        (emp.job_name if hasattr(emp, 'job_name') and emp.job_name else False) or
                        (getattr(emp, 'job_title', False) or False) or
                        (emp.contract_id.job_id.name if hasattr(emp, 'contract_id') and emp.contract_id and emp.contract_id.job_id else False) or
                        (emp.version_id.job_id.name if hasattr(emp, 'version_id') and emp.version_id and emp.version_id.job_id else False)
                    )
                if not curr_pos and getattr(cand, 'position_id', False):
                    job = self.env['hr.job'].browse(cand.position_id)
                    if job.exists():
                        curr_pos = job.name

                # 2. Current Work Unit (Reference #1): Candidate's current location / default operating unit
                curr_unit = cand.get_current_work_unit_name() if hasattr(cand, 'get_current_work_unit_name') else False
                if not curr_unit:
                    curr_unit = cand.current_work_unit or False
                if not curr_unit and emp:
                    curr_unit = (
                        (emp.default_operating_unit_id.name if getattr(emp, 'default_operating_unit_id', False) and emp.default_operating_unit_id else False) or
                        (emp.department_id.operating_unit_id.name if (getattr(emp, 'department_id', False) and emp.department_id and getattr(emp.department_id, 'operating_unit_id', False) and emp.department_id.operating_unit_id) else False) or
                        (emp.department_id.name if getattr(emp, 'department_id', False) and emp.department_id else False) or
                        (emp.operating_unit_ids[0].name if getattr(emp, 'operating_unit_ids', False) and emp.operating_unit_ids else False) or
                        (getattr(emp, 'location', False) or False)
                    )
                if not curr_unit and getattr(cand, 'workunit_id', False):
                    ou = self.env['operating.unit'].browse(cand.workunit_id)
                    if ou.exists():
                        curr_unit = ou.name

                # 3. New Placement Work Unit (Reference #2): Candidate's target placement unit / vacancy hiring work unit
                target_unit = cand.get_target_work_unit_name() if hasattr(cand, 'get_target_work_unit_name') else False
                if not target_unit:
                    target_unit = cand.preferred_location or False
                if not target_unit and vac and vac.exists():
                    if hasattr(vac, 'hiring_details') and vac.hiring_details:
                        units = [hd.work_unit.name for hd in vac.hiring_details if hd.work_unit and hd.work_unit.name]
                        if units:
                            target_unit = ", ".join(dict.fromkeys(units))
                    if not target_unit and vac.operating_unit_id and vac.operating_unit_id.name:
                        target_unit = vac.operating_unit_id.name
                    if not target_unit and getattr(vac, 'job_location', False):
                        target_unit = vac.job_location

                if not target_unit:
                    dest_ou = _resolve_operating_unit(self.env, cand, parent_rec)
                    target_unit = dest_ou.name if dest_ou else (parent_rec.job_location if parent_rec and parent_rec.job_location else False)

                if not target_unit and parent_rec and getattr(parent_rec, 'workunit_id', False):
                    ou = self.env['operating.unit'].browse(parent_rec.workunit_id)
                    if ou.exists():
                        target_unit = ou.name

                # 4. New Job Position & Grade: vacancy of this position which was selected
                new_job = False
                if parent_rec and parent_rec.job_position:
                    new_job = parent_rec.job_position
                elif vac and vac.exists() and vac.job_position:
                    new_job = vac.job_position

                new_grade_str = cand.get_new_job_grade_name() if hasattr(cand, 'get_new_job_grade_name') else False
                if not new_grade_str and vac and vac.exists():
                    if getattr(vac, 'grade', False) and vac.grade:
                        new_grade_str = getattr(vac.grade, 'grade_name', False) or getattr(vac.grade, 'name', False) or str(vac.grade)
                    elif getattr(vac, 'job_grade', False) and vac.job_grade:
                        new_grade_str = getattr(vac.job_grade, 'grade_name', False) or getattr(vac.job_grade, 'name', False) or str(vac.job_grade)

                if not new_grade_str and new_job:
                    if getattr(new_job, 'grade', False) and new_job.grade:
                        new_grade_str = getattr(new_job.grade, 'grade_name', False) or getattr(new_job.grade, 'name', False)
                    elif getattr(new_job, 'job_grade', False) and new_job.job_grade:
                        new_grade_str = getattr(new_job.job_grade, 'grade_name', False) or getattr(new_job.job_grade, 'name', False)

                if not new_grade_str and parent_rec:
                    grade_val = parent_rec.job_grade if parent_rec else False
                    grade_rec = _resolve_grade_record(self.env, grade_val, parent_rec=parent_rec)
                    new_grade_str = grade_rec.grade_name if grade_rec else (_format_clean_text(grade_val) or (new_job.job_grade.grade_name if new_job and hasattr(new_job, 'job_grade') and new_job.job_grade else False))

                if not new_grade_str and getattr(cand, 'emp_grade', False):
                    new_grade_str = cand.emp_grade

                # 5. Coach / Manager
                coach = cand.coach_id or (
                    cand.emp_name.coach_id or cand.emp_name.parent_id
                    if cand.emp_name
                    else False
                )

                res.update({
                    'candidate_id': cand.id,
                    'employee_id': emp.id if emp else False,
                    'current_position': _format_clean_text(curr_pos) or 'N/A',
                    'current_work_unit': _format_clean_text(curr_unit) or 'N/A',
                    'target_work_unit': _format_clean_text(target_unit) or 'N/A',
                    'new_job_position_id': new_job.id if new_job else False,
                    'new_job_grade': _format_clean_text(new_grade_str) or 'N/A',
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

        # 1. Capture old employee state before changes
        old_ou = emp.default_operating_unit_id
        old_dept = emp.department_id
        old_job = emp.job_id or (emp.job_position if hasattr(emp, 'job_position') else False)
        old_grade = emp.job_grade if hasattr(emp, 'job_grade') else (emp.grade if hasattr(emp, 'grade') else False)

        # 2. Resolve destination values
        dest_ou = _resolve_operating_unit(self.env, cand, parent_rec)
        grade_val = parent_rec.job_grade or getattr(parent_rec, 'job_grade_id', False) if parent_rec else False
        grade_rec = _resolve_grade_record(self.env, grade_val, parent_rec=parent_rec)
        job_pos = parent_rec.job_position if parent_rec else False

        # 3. Build unified write vals for hr.employee
        vals = {}
        if job_pos:
            if hasattr(emp, 'job_id'):
                vals['job_id'] = job_pos.id
            if hasattr(emp, 'job_position'):
                vals['job_position'] = job_pos.id
            if hasattr(emp, 'job_name'):
                vals['job_name'] = job_pos.name
            if hasattr(emp, 'department_id') and job_pos.department_id:
                vals['department_id'] = job_pos.department_id.id

        if grade_rec:
            if hasattr(emp, 'job_grade'):
                vals['job_grade'] = grade_rec.id
            if hasattr(emp, 'grade'):
                vals['grade'] = grade_rec.id
            if hasattr(emp, 'emp_grade'):
                vals['emp_grade'] = grade_rec.grade_name or str(grade_val)
        elif grade_val and hasattr(emp, 'emp_grade'):
            vals['emp_grade'] = str(grade_val)

        if dest_ou and hasattr(emp, 'default_operating_unit_id'):
            vals['default_operating_unit_id'] = dest_ou.id

        # 4. Perform write with job_history_reason='promotion'
        if vals:
            emp.sudo().with_context(job_history_reason='promotion').write(vals)

        # Update salary on hr.version / contract upon release
        if cand.promoted_salary:
            if hasattr(emp, 'version_id') and emp.version_id:
                try:
                    emp.version_id.sudo().write({'wage': cand.promoted_salary})
                except Exception as e:
                    _logger.warning("Could not update version_id wage on release: %s", e)
            if hasattr(emp, 'contract_id') and emp.contract_id:
                try:
                    emp.contract_id.sudo().write({'wage': cand.promoted_salary})
                except Exception as e:
                    _logger.warning("Could not update contract wage on release: %s", e)

        # 5. History Logging Rule:
        # If Grade CHANGED -> Log ONLY under Job History (handled automatically by HrEmployeeJobHistory)
        # If Grade SAME -> Log ONLY under Transfer History (handled automatically by HrEmployeeJobHistory)
        today = self.release_date or fields.Date.context_today(self)
        old_grade_id = old_grade.id if old_grade else False
        new_grade_id = grade_rec.id if grade_rec else False
        grade_changed = (old_grade_id != new_grade_id)

        # Log department.history only if grade changed (promotion)
        if grade_changed and 'department.history' in self.env:
            try:
                self.env['department.history'].sudo().create({
                    'employee_id': emp.id,
                    'employee_name': emp.name,
                    'new_job_title': job_pos.id if job_pos else (emp.job_id.id if emp.job_id else False),
                    'job_grade': grade_rec.id if grade_rec else (emp.job_grade.id if hasattr(emp, 'job_grade') and emp.job_grade else False),
                    'job_history_start_date': today,
                    'reason': _('Promotion via Internal Recruitment (Release Form)'),
                    'operating_unit': dest_ou.id if dest_ou else (emp.default_operating_unit_id.id if emp.default_operating_unit_id else False),
                })
            except Exception as e:
                _logger.warning("Failed to create department.history: %s", e)

        # 6. Update candidate line status
        cand.write({
            'promotion_status': 'released',
            'release_date': self.release_date,
            'coach_id': self.coach_id.id,
            'release_remarks': self.release_remarks,
            'release_handover': self.handover_status,
        })

        target_unit_name = dest_ou.name if dest_ou else (cand.preferred_location or (parent_rec.job_location if parent_rec else 'N/A'))

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
                    job_pos.name if job_pos else 'N/A',
                    grade_rec.grade_name if grade_rec else (parent_rec.job_grade or 'N/A'),
                    target_unit_name,
                    self.release_remarks or 'None'
                )
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidate Released & Promoted'),
                'message': _('Employee %s has been successfully released and updated to the new position, grade, and work unit.') % emp.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
