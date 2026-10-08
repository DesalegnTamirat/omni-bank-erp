# -*- coding: utf-8 -*-
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from odoo import fields, models
from odoo.exceptions import UserError


class PopulateT3ScorecardWizard(models.TransientModel):
    _name = 'populate.t3.scorecard.wizard'
    _description = 'Populate Tier 3 Scorecard Wizard'

    fiscal_year_id = fields.Many2one(
        'performance.fiscal.year', string='Fiscal Year', required=True,
    )
    appraisal_period_id = fields.Many2one(
        'appraisal.period', string='Appraisal Period', required=True,
    )

    def action_populate(self):
        self.ensure_one()

        fyl = self.fiscal_year_id.line_ids.filtered(
            lambda l: l.appraisal_period == self.appraisal_period_id
        )[:1]
        if not fyl:
            raise UserError(
                'No Fiscal Year Line found for the selected Fiscal Year and Appraisal Period.'
            )

        # 1. Sync all active templates once
        all_active_templates = self.env['performance.job.template'].search([('active', '=', True)])
        if all_active_templates:
            all_active_templates.with_context(skip_percent_constrain=True)._sync_to_job_measures()

        # 2. Filter only ACTIVE templates that have EXACTLY 100% total weight
        valid_templates = all_active_templates.filtered(lambda t: round(t.total_weight, 2) == 100.0)

        if not valid_templates:
            incomplete_templates = all_active_templates.filtered(lambda t: round(t.total_weight, 2) != 100.0)
            if incomplete_templates:
                names = ', '.join(incomplete_templates.mapped('name')[:3])
                raise UserError(
                    f"No active Job Position Scorecards with 100% weight found. "
                    f"The following template(s) are incomplete: {names}. "
                    f"Please ensure the Total Weight is exactly 100% before populating."
                )
            raise UserError('No active Job Position Scorecards found. Configure them under Configuration first.')

        # 3. Pre-cache template measures in fast in-memory lookups
        direct_template_measures = {}
        branch_template_measures = {}
        all_relevant_job_ids = set()

        for t in valid_templates:
            m_ids = t.line_ids.mapped('job_measure_id').filtered(
                lambda m: m and m.exists() and m.active
            ).ids
            if not m_ids:
                continue

            all_relevant_job_ids.add(t.job_id.id)
            if t.operating_unit_id:
                direct_template_measures[(t.operating_unit_id.id, t.job_id.id)] = m_ids
            if t.is_branch_unit:
                branch_template_measures[t.job_id.id] = m_ids

        if not all_relevant_job_ids:
            raise UserError('Active Job Position templates have no active measurements assigned.')

        # 4. Fetch Branch Operating Units in 1 query
        branch_types = ('branch', 'sub_branch', 'service_center')
        branch_units = self.env['operating.unit'].sudo().search([
            ('work_unit_type', 'in', branch_types)
        ])
        branch_unit_ids = set(branch_units.ids)

        # 5. Bulk fetch all relevant employees in 1 single search_read query
        Employee = self.env['hr.employee'].sudo()
        has_job_position_field = 'job_position' in Employee._fields
        if has_job_position_field:
            emp_domain = [
                ('active', '=', True),
                '|',
                ('job_id', 'in', list(all_relevant_job_ids)),
                ('job_position', 'in', list(all_relevant_job_ids)),
            ]
        else:
            emp_domain = [
                ('active', '=', True),
                ('job_id', 'in', list(all_relevant_job_ids)),
            ]

        emp_fields = ['id', 'name', 'job_id', 'department_id', 'company_id', 'coach_id', 'parent_id', 'create_date']
        for opt_field in ('job_position', 'default_operating_unit_id', 'operating_unit_ids',
                          'service_hire_date', 'hire_date', 'service_start_date',
                          'first_contract_date', 'start_date'):
            if opt_field in Employee._fields:
                emp_fields.append(opt_field)

        emp_records = Employee.search_read(emp_domain, emp_fields)
        if not emp_records:
            template_names = ', '.join(valid_templates.mapped('name'))
            raise UserError(
                f"No matching employees found for the active Job Position templates: {template_names}. "
                f"Please verify that employees have their Job Position and Work Unit (Branch / Unit) properly assigned."
            )

        # 6. Bulk read department operating units in 1 query
        dept_ids = {e['department_id'][0] for e in emp_records if e.get('department_id')}
        dept_ou_map = {}
        if dept_ids and 'operating_unit_id' in self.env['hr.department']._fields:
            dept_reads = self.env['hr.department'].sudo().browse(dept_ids).read(['operating_unit_id'])
            dept_ou_map = {
                d['id']: d['operating_unit_id'][0] if d.get('operating_unit_id') else False
                for d in dept_reads
            }

        # 7. Bulk read contracts for hire dates in 1 query (for employees missing direct hire date)
        contract_hire_map = {}
        if 'hr.contract' in self.env:
            c_reads = self.env['hr.contract'].sudo().search_read(
                [('employee_id', 'in', [e['id'] for e in emp_records]), ('date_start', '!=', False)],
                ['employee_id', 'date_start'],
                order='date_start asc'
            )
            for c in c_reads:
                eid = c['employee_id'][0]
                if eid not in contract_hire_map:
                    contract_hire_map[eid] = c['date_start']

        # 8. Fast in-memory template matching and 3-month tenure verification
        period_start = fyl.date_start
        period_end = fyl.date_end
        matched_emp_data = []

        for emp in emp_records:
            job_id = emp['job_id'][0] if emp.get('job_id') else (
                emp['job_position'][0] if emp.get('job_position') else False
            )
            if not job_id:
                continue

            ou_id = False
            if emp.get('default_operating_unit_id'):
                ou_id = emp['default_operating_unit_id'][0]
            elif emp.get('operating_unit_ids'):
                ou_id = emp['operating_unit_ids'][0]
            elif emp.get('department_id') and emp['department_id'][0] in dept_ou_map:
                ou_id = dept_ou_map[emp['department_id'][0]]

            assigned_measure_ids = []
            if ou_id and (ou_id, job_id) in direct_template_measures:
                assigned_measure_ids = direct_template_measures[(ou_id, job_id)]
            elif ou_id in branch_unit_ids and job_id in branch_template_measures:
                assigned_measure_ids = branch_template_measures[job_id]

            if not assigned_measure_ids:
                continue

            # 3-Month Minimum Service Rule
            hire_date = (
                emp.get('service_hire_date') or
                emp.get('hire_date') or
                emp.get('service_start_date') or
                emp.get('first_contract_date') or
                emp.get('start_date') or
                contract_hire_map.get(emp['id']) or
                (emp.get('create_date') and emp['create_date'].date())
            )
            if hire_date and period_end:
                if hire_date > period_end:
                    continue
                min_service_date = hire_date + relativedelta(months=3)
                if min_service_date > period_end:
                    continue

            matched_emp_data.append((emp, ou_id, job_id, assigned_measure_ids))

        if not matched_emp_data:
            raise UserError(
                f"No eligible employees found with at least 3 months of service for the appraisal period "
                f"({period_start} to {period_end}) matching the active templates."
            )

        # 9. Draft Cleanup & Non-Draft Lock Protection in 1 query
        matched_emp_ids = [m[0]['id'] for m in matched_emp_data]
        existing = self.env['t3.scorecard'].search([
            ('employee_id', 'in', matched_emp_ids),
            ('appraisal_period_id', '=', self.appraisal_period_id.id),
            ('fiscal_year_id', '=', self.fiscal_year_id.id),
        ])
        draft_existing = existing.filtered(lambda r: r.state == 'draft')
        locked_existing = existing - draft_existing

        if draft_existing:
            draft_existing.unlink()

        locked_emp_ids = set(locked_existing.mapped('employee_id').ids)

        # 10. Bulk build Scorecard and Line data payload
        vals_list = []
        fy_name = self.fiscal_year_id.name
        period_name = self.appraisal_period_id.name

        for emp, ou_id, job_id, assigned_measure_ids in matched_emp_data:
            emp_id = emp['id']
            if emp_id in locked_emp_ids:
                continue

            planning_name = f"{emp['name']} Scorecard Plan {fy_name} {period_name}"
            coach_or_parent = (
                emp['coach_id'][0] if emp.get('coach_id') else (
                    emp['parent_id'][0] if emp.get('parent_id') else False
                )
            )
            company_id = emp['company_id'][0] if emp.get('company_id') else False

            line_commands = [(0, 0, {'job_measure_id': mid}) for mid in assigned_measure_ids]

            vals_list.append({
                'employee_id': emp_id,
                'planning_name': planning_name,
                'fiscal_year_id': self.fiscal_year_id.id,
                'appraisal_period_id': self.appraisal_period_id.id,
                'start_date': period_start,
                'end_date': period_end,
                'company_id': company_id,
                'operating_unit_id': ou_id,
                'manager_id': coach_or_parent,
                'job_id': job_id,
                'line_ids': line_commands,
            })

        if not vals_list:
            raise UserError(
                'No new Tier 3 Scorecards were created — all eligible employees already have '
                'active/confirmed scorecards for this Fiscal Year and Appraisal Period.'
            )

        # 11. Single-pass ORM batch creation (< 2 seconds for 3,000+ employees)
        new_scorecards = self.env['t3.scorecard'].create(vals_list)

        # 12. Strict validation: Ensure every created scorecard has exactly 100% total weight
        incomplete_scs = new_scorecards.filtered(lambda sc: round(sc.total_weight, 2) != 100.0)
        if incomplete_scs:
            error_details = [
                f"{sc.employee_id.name} ({sc.operating_unit_id.name or 'No Unit'} - {round(sc.total_weight, 2)}%)"
                for sc in incomplete_scs
            ]
            incomplete_scs.unlink()
            valid_new_scs = new_scorecards - incomplete_scs
            if not valid_new_scs:
                raise UserError(
                    "Scorecard generation restricted: The generated scorecard(s) did not reach exactly 100% total weight:\n- "
                    + "\n- ".join(error_details)
                    + "\n\nPlease check the corresponding Position Scorecard Template to ensure all KPIs sum to exactly 100%."
                )
            new_scorecards = valid_new_scs

        return {
            'name': 'Populated Tier 3 Scorecards',
            'type': 'ir.actions.act_window',
            'res_model': 't3.scorecard',
            'view_mode': 'list,form',
            'domain': [('id', 'in', new_scorecards.ids)],
        }