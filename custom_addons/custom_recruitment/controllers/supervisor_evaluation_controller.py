# -*- coding: utf-8 -*-

import logging
from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class SupervisorEvaluationController(http.Controller):

    @http.route('/recruitment/supervisor_evaluation/<int:vacancy_id>', type='http', auth='user', website=False)
    def supervisor_evaluation(self, vacancy_id, **kw):
        """
        Direct landing route for supervisors to evaluate their subordinates for a vacancy.
        Pops up the supervisor.recommendation.wizard with ONLY their eligible subordinates.
        """
        vacancy = request.env['job.vacancy'].sudo().browse(vacancy_id)
        if not vacancy.exists():
            return request.not_found()

        if vacancy.scores_computed:
            ref_str = vacancy.reference or vacancy.job_title or _('Vacancy')
            return request.make_response(
                f"""<!DOCTYPE html>
                <html>
                <head>
                    <title>Supervisor Evaluation Closed</title>
                    <style>
                        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f8f9fa; }}
                        .card {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); max-width: 520px; text-align: center; }}
                        h2 {{ color: #541718; margin-top: 0; margin-bottom: 12px; }}
                        p {{ color: #555; font-size: 15px; line-height: 1.6; margin-bottom: 24px; }}
                        .btn {{ display: inline-block; padding: 10px 22px; background: #541718; color: white; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; }}
                        .btn:hover {{ background: #3d1011; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h2>Evaluation Period Closed</h2>
                        <p>Candidate ranking and scores for <b>{ref_str}</b> have already been computed and finalized by HR.</p>
                        <a href="/web" class="btn">Return to Odoo</a>
                    </div>
                </body>
                </html>""",
                headers=[('Content-Type', 'text/html;charset=utf-8')]
            )

        user = request.env.user
        user_emp = user.employee_id or request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        sel = vacancy._get_selected_recruitment_record()
        cands = request.env['new.internal.recruitment.selected.candidates']
        if sel and hasattr(sel, 'new_int_rec_sel'):
            cands = sel.new_int_rec_sel.filtered(lambda c: c.emp_name)
        elif hasattr(vacancy, 'new_int_rec_sel') and vacancy.new_int_rec_sel:
            cands = vacancy.new_int_rec_sel.filtered(lambda c: c.emp_name)

        is_hr = user.has_group('custom_recruitment.group_recruitment_officer') or user.has_group('custom_recruitment.group_recruitment_manager') or user.has_group('base.group_system')
        if not is_hr:
            if not user_emp:
                return request.make_response(
                    """<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:50px;">
                    <h3>No Linked Employee Profile</h3>
                    <p>Your user account is not linked to an employee profile. Please contact HR.</p>
                    <a href="/web" style="display:inline-block;padding:10px 20px;background:#541718;color:white;text-decoration:none;border-radius:4px;">Back to Home</a>
                    </body></html>""",
                    headers=[('Content-Type', 'text/html;charset=utf-8')]
                )
            cands = cands.filtered(
                lambda c: c.emp_name and (
                    (c.emp_name.parent_id and c.emp_name.parent_id.id == user_emp.id) or
                    (c.emp_name.coach_id and c.emp_name.coach_id.id == user_emp.id)
                )
            )

        if not cands:
            ref_str = vacancy.reference or vacancy.job_title or _('Vacancy')
            return request.make_response(
                f"""<!DOCTYPE html>
                <html>
                <head>
                    <title>Supervisor Evaluation</title>
                    <style>
                        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f8f9fa; }}
                        .card {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); max-width: 520px; text-align: center; }}
                        h2 {{ color: #541718; margin-top: 0; margin-bottom: 12px; }}
                        p {{ color: #555; font-size: 15px; line-height: 1.6; margin-bottom: 24px; }}
                        .btn {{ display: inline-block; padding: 10px 22px; background: #541718; color: white; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; }}
                        .btn:hover {{ background: #3d1011; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h2>No Subordinates Pending Evaluation</h2>
                        <p>No candidates assigned to you as supervisor were found for <b>{ref_str}</b>, or their recommendation marks have already been submitted.</p>
                        <a href="/web" class="btn">Return to Odoo</a>
                    </div>
                </body>
                </html>""",
                headers=[('Content-Type', 'text/html;charset=utf-8')]
            )

        # Build wizard record
        is_batch = len(cands) > 1
        first_cand = cands[0]
        emp = first_cand.emp_name
        sup = emp.parent_id or emp.coach_id

        lines = [(0, 0, {
            'candidate_id': c.id,
            'employee_id': c.emp_name.id,
            'current_position': c.emp_name.job_id.name if c.emp_name.job_id else '',
            'current_work_unit': c.emp_name.default_operating_unit_id.name if c.emp_name.default_operating_unit_id else '',
            'service_in_company': c.service_in_company or 0.0,
            'pms_score': c.pms_score or 0.0,
            'recommendation_score': c.supervisor_recommendation_score if c.supervisor_recommendation_score > 0 else 100.0,
            'recommendation_remarks': c.supervisor_remarks or '',
        }) for c in cands]

        wiz_vals = {
            'vacancy_id': vacancy.id,
            'selected_recruitment_id': sel.id if sel else False,
            'is_batch': is_batch,
            'candidate_id': first_cand.id if not is_batch else False,
            'employee_id': emp.id if not is_batch and emp else False,
            'job_position': vacancy.job_position.name if vacancy.job_position else (vacancy.job_title or ''),
            'current_position': emp.job_id.name if emp and emp.job_id else '',
            'current_grade': emp.job_grade.grade_name if emp and emp.job_grade else '',
            'current_work_unit': emp.default_operating_unit_id.name if emp and emp.default_operating_unit_id else '',
            'current_department': emp.department_id.name if emp and emp.department_id else '',
            'service_in_company': first_cand.service_in_company or 0.0,
            'pms_score': first_cand.pms_score or 0.0,
            'supervisor_id': sup.id if sup else False,
            'evaluator_user_id': user.id,
            'recommendation_score': first_cand.supervisor_recommendation_score if first_cand.supervisor_recommendation_score > 0 else 100.0,
            'recommendation_remarks': first_cand.supervisor_remarks or '',
            'line_ids': lines,
        }
        wiz = request.env['supervisor.recommendation.wizard'].sudo().create(wiz_vals)

        action = request.env.ref('custom_recruitment.action_supervisor_recommendation_wizard')
        return request.redirect(f'/odoo/action-{action.id}/{wiz.id}')
