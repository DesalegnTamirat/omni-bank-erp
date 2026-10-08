# -*- coding: utf-8 -*-
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from odoo import fields, models
from odoo.exceptions import UserError


def get_employee_hire_date(employee):
    """Retrieve the hire date or service start date of an employee."""
    if not employee:
        return False
    for field_name in ('service_hire_date', 'hire_date', 'service_start_date', 'first_contract_date', 'start_date'):
        if hasattr(employee, field_name) and getattr(employee, field_name):
            return getattr(employee, field_name)
    if hasattr(employee, 'contract_ids') and employee.contract_ids:
        contracts = employee.contract_ids.filtered('date_start').sorted('date_start')
        if contracts and contracts[0].date_start:
            return contracts[0].date_start
    if hasattr(employee, 'contract_id') and employee.contract_id and employee.contract_id.date_start:
        return employee.contract_id.date_start
    if hasattr(employee, 'version_id') and employee.version_id:
        v = employee.version_id
        for field_name in ('service_hire_date', 'service_start_date', 'start_date', 'probation_start_date'):
            if hasattr(v, field_name) and getattr(v, field_name):
                return getattr(v, field_name)
    if employee.create_date:
        return employee.create_date.date()
    return False


def is_eligible_for_period(employee, period_start, period_end):
    """
    Check if employee has worked at least 3 months by the appraisal period end date.
    Employees who have not completed 3 months of service by the period end are excluded.
    """
    hire_date = get_employee_hire_date(employee)
    if not hire_date:
        return True
    if period_end:
        if hire_date > period_end:
            return False
        min_service_date = hire_date + relativedelta(months=3)
        if min_service_date > period_end:
            return False
    return True


class PopulateT2ScorecardWizard(models.TransientModel):
    _name = 'populate.t2.scorecard.wizard'
    _description = 'Populate Tier 2 Scorecard Wizard'

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

        # 1. Fetch only ACTIVE objectives with parent objective (cascaded from CEO / coach)
        all_active_objectives = self.env['performance.objective'].search([
            ('active', '=', True),
            ('parent_objective_id', '!=', False),
        ])
        if not all_active_objectives:
            raise UserError('No active cascaded Strategic Objectives found. Configure Tier 2 Objectives first.')

        # 2. Group active objectives and active measures by Operating Unit
        OperatingUnit = self.env['operating.unit'].sudo()
        Employee = self.env['hr.employee'].sudo()

        unit_objs_map = defaultdict(lambda: self.env['performance.objective'])
        for obj in all_active_objectives:
            ou = obj.employee_operating_unit_id
            if not ou and obj.employee_id:
                ou = OperatingUnit.search([('manager_id', '=', obj.employee_id.id)], limit=1)
                if not ou and hasattr(obj.employee_id, 'default_operating_unit_id') and obj.employee_id.default_operating_unit_id:
                    ou = obj.employee_id.default_operating_unit_id
            if ou:
                unit_objs_map[ou.id] |= obj

        valid_unit_ids = set()
        incomplete_units = []
        unit_measure_ids_map = {}

        for ou_id, objs in unit_objs_map.items():
            ou = OperatingUnit.browse(ou_id)
            active_measures = objs.mapped('measure_ids').filtered(lambda m: m.active)
            total_weight = sum(active_measures.mapped('weight'))
            if round(total_weight, 2) == 100.0:
                valid_unit_ids.add(ou_id)
                unit_measure_ids_map[ou_id] = active_measures.ids
            else:
                incomplete_units.append(f"{ou.name} ({round(total_weight, 2)}%)")

        if not valid_unit_ids:
            msg = "No Operating Units with active Performance Objectives totaling exactly 100% weight were found."
            if incomplete_units:
                msg += "\n\nThe following Work Units have incomplete weights:\n- " + "\n- ".join(incomplete_units[:5])
                msg += "\n\nPlease adjust the measures so the total weight equals 100% before populating."
            raise UserError(msg)

        # 3. Collect Target Managers / Employees for Tier 2 Scorecards
        branch_types = ('branch', 'sub_branch', 'service_center')

        # Find branch template measure IDs if available
        branch_template_measure_ids = []
        for ou_id in valid_unit_ids:
            if OperatingUnit.browse(ou_id).work_unit_type in branch_types:
                branch_template_measure_ids = unit_measure_ids_map[ou_id]
                break

        # Map target employee -> (operating_unit_rec, measure_ids)
        target_emp_map = {}

        # A. Non-branch units with valid 100% objectives
        for ou_id in valid_unit_ids:
            ou = OperatingUnit.browse(ou_id)
            if ou.work_unit_type not in branch_types:
                mgr = ou.manager_id
                if not mgr:
                    objs = unit_objs_map[ou_id]
                    mgr = objs.mapped('employee_id')[:1]
                if mgr:
                    target_emp_map[mgr] = (ou, unit_measure_ids_map[ou_id])

        # B. Branch units
        if branch_template_measure_ids:
            all_branch_ous = OperatingUnit.search([
                ('work_unit_type', 'in', branch_types)
            ])
            for b_ou in all_branch_ous:
                b_mgr = b_ou.manager_id
                if not b_mgr:
                    b_mgr = Employee.search([
                        ('default_operating_unit_id', '=', b_ou.id),
                        ('coach_id', '!=', False),
                    ], limit=1)
                if b_mgr:
                    # Specific branch measures if configured, otherwise branch template measures
                    b_measures = unit_measure_ids_map.get(b_ou.id, branch_template_measure_ids)
                    target_emp_map[b_mgr] = (b_ou, b_measures)
        else:
            for ou_id in valid_unit_ids:
                ou = OperatingUnit.browse(ou_id)
                if ou.work_unit_type in branch_types:
                    mgr = ou.manager_id or unit_objs_map[ou_id].mapped('employee_id')[:1]
                    if mgr:
                        target_emp_map[mgr] = (ou, unit_measure_ids_map[ou_id])

        target_employees = self.env['hr.employee'].concat(*target_emp_map.keys())

        if not target_employees:
            raise UserError(
                'No eligible Operating Unit Managers found for the 100% complete Objectives. '
                'Please ensure Managers are assigned to the Operating Units.'
            )

        # 4. Filter managers by 3-Month Tenure requirement
        eligible_target_employees = target_employees.filtered(
            lambda emp: is_eligible_for_period(emp, fyl.date_start, fyl.date_end)
        )
        if not eligible_target_employees:
            raise UserError(
                f"No eligible Managers found with at least 3 months of service for the appraisal period "
                f"({fyl.date_start} to {fyl.date_end})."
            )

        # 5. Handle Existing Scorecards (unlink draft, preserve locked)
        existing = self.env['t2.scorecard'].search([
            ('employee_id', 'in', eligible_target_employees.ids),
            ('appraisal_period_id', '=', self.appraisal_period_id.id),
            ('fiscal_year_id', '=', self.fiscal_year_id.id),
        ])
        draft_existing = existing.filtered(lambda r: r.state == 'draft')
        locked_existing = existing - draft_existing

        if draft_existing:
            draft_existing.unlink()

        locked_employee_ids = set(locked_existing.mapped('employee_id').ids)

        # 6. Build and create new Scorecards in batch with pre-embedded lines
        vals_list = []
        for emp in eligible_target_employees:
            if emp.id in locked_employee_ids:
                continue

            op_unit, measure_ids = target_emp_map[emp]
            unit_name = op_unit.name if op_unit else emp.name
            planning_name = '%s Scorecard Plan %s %s' % (
                unit_name, self.fiscal_year_id.name, self.appraisal_period_id.name
            )

            line_commands = [(0, 0, {'measure_id': mid}) for mid in measure_ids]

            vals_list.append({
                'employee_id': emp.id,
                'planning_name': planning_name,
                'fiscal_year_id': self.fiscal_year_id.id,
                'appraisal_period_id': self.appraisal_period_id.id,
                'start_date': fyl.date_start,
                'end_date': fyl.date_end,
                'company_id': emp.company_id.id if emp.company_id else False,
                'operating_unit_id': op_unit.id if op_unit else False,
                'manager_id': emp.coach_id.id if emp.coach_id else (emp.parent_id.id if emp.parent_id else False),
                'job_id': emp.job_id.id if emp.job_id else False,
                'line_ids': line_commands,
            })

        if not vals_list:
            raise UserError('No new Tier 2 Scorecards were created — they may already exist or are locked.')

        new_scorecards = self.env['t2.scorecard'].create(vals_list)

        # 7. Strict validation: Ensure every created scorecard has exactly 100% total weight
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
                    "Tier 2 Scorecard generation restricted: The generated scorecard(s) did not reach exactly 100% total weight:\n- "
                    + "\n- ".join(error_details)
                    + "\n\nPlease check the Strategic Objectives and ensure all assigned measures sum to exactly 100%."
                )
            new_scorecards = valid_new_scs

        return {
            'name': 'Populated Tier 2 Scorecards',
            'type': 'ir.actions.act_window',
            'res_model': 't2.scorecard',
            'view_mode': 'list,form',
            'domain': [('id', 'in', new_scorecards.ids)],
        }