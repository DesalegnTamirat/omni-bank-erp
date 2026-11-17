# -*- coding: utf-8 -*-
import io
import base64
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError
from .t2_appraisal import detect_period_type

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class PerformanceComprehensiveReport(models.TransientModel):
    _name = 'performance.comprehensive.report'
    _description = 'Comprehensive Performance Report Line'
    _order = 'tier asc, operating_unit_name asc, employee_name asc'

    wizard_id = fields.Many2one('performance.comprehensive.report.wizard', string='Wizard', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    employee_code = fields.Char(string='Employee ID')
    employee_name = fields.Char(string='Employee Name', required=True)
    tier = fields.Selection([
        ('tier1', 'Tier 1 (Corporate)'),
        ('tier2', 'Tier 2 (Operating Unit)'),
        ('tier3', 'Tier 3 (Employee)'),
    ], string='Employee Tier', required=True)
    tier_label = fields.Char(string='Tier')
    sol_id = fields.Char(string='SOL ID')
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit')
    operating_unit_name = fields.Char(string='Operating Name')
    planning_name = fields.Char(string='Planning Name')
    fiscal_year_id = fields.Many2one('performance.fiscal.year', string='Fiscal Year')
    fiscal_year_name = fields.Char(string='Fiscal Year Name')

    # Status
    appraisal_status_h1 = fields.Char(string='H1 Status', default='Not Created')
    appraisal_status_h2 = fields.Char(string='H2 Status', default='Not Created')
    overall_status = fields.Char(string='Appraisal Status')

    # H1 Scores
    employee_score_h1 = fields.Float(string='Employee Score H1', digits=(16, 2))
    operating_score_h1 = fields.Float(string='Operating Score H1', digits=(16, 2))
    average_score_h1 = fields.Float(string='Average Score H1', digits=(16, 2))

    # H2 Scores
    employee_score_h2 = fields.Float(string='Employee Score H2', digits=(16, 2))
    operating_score_h2 = fields.Float(string='Operating Score H2', digits=(16, 2))
    average_score_h2 = fields.Float(string='Average Score H2', digits=(16, 2))

    # Annual Score & Rating
    annual_score = fields.Float(string='Employee Annual Score', digits=(16, 2))
    performance_rating = fields.Char(string='Performance Rating')


class PerformanceComprehensiveReportWizard(models.TransientModel):
    _name = 'performance.comprehensive.report.wizard'
    _description = 'Comprehensive Performance Report Generator'

    def _default_fiscal_year(self):
        active_fy = self.env['performance.fiscal.year'].search([('active', '=', True)], limit=1)
        if not active_fy:
            active_fy = self.env['performance.fiscal.year'].search([], order='date_start desc', limit=1)
        return active_fy

    fiscal_year_id = fields.Many2one(
        'performance.fiscal.year',
        string='Fiscal Year',
        required=True,
        default=_default_fiscal_year,
    )
    tier = fields.Selection([
        ('all', 'All Tiers (Corporate, Unit & Employee)'),
        ('tier1', 'Tier 1 (Corporate / CEO)'),
        ('tier2', 'Tier 2 (Operating Unit / Manager)'),
        ('tier3', 'Tier 3 (Individual Employee)'),
    ], string='Tier Level', default='all', required=True)

    appraisal_period_id = fields.Many2one(
        'appraisal.period',
        string='Appraisal Period',
        help='Optional. Leave empty to aggregate all periods (H1 & H2) for the selected fiscal year.',
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit',
        help='Optional. Filter results for a specific branch or head office unit.',
    )

    excel_file = fields.Binary(string='Excel File', readonly=True)
    excel_filename = fields.Char(string='Excel Filename', readonly=True)

    report_line_ids = fields.One2many(
        'performance.comprehensive.report',
        'wizard_id',
        string='Generated Report Lines',
    )

    def _get_rating_for_score(self, score):
        if not score:
            return 'Not Rated'
        lookup_score = max(0.0, min(100.0, score))
        ranking = self.env['pms.ranking'].sudo().search([
            ('score_from', '<=', lookup_score),
            ('score_to', '>=', lookup_score),
        ], limit=1)
        if not ranking:
            ranking = self.env['pms.ranking'].sudo().search([
                ('score_from', '<=', lookup_score),
            ], order='score_from desc', limit=1)
        if not ranking:
            ranking = self.env['pms.ranking'].sudo().search([], order='score_from asc', limit=1)

        if ranking:
            return dict(ranking._fields['ranking'].selection).get(ranking.ranking, ranking.ranking)
        return 'Not Rated'

    def _format_status_label(self, state_val, model_name):
        if not state_val or state_val == 'not_created':
            return 'Not Created'
        if model_name in self.env:
            field = self.env[model_name]._fields.get('state')
            if field and hasattr(field, 'selection'):
                return dict(field.selection).get(state_val, state_val.capitalize())
        return state_val.capitalize()

    def _get_record_planning_name(self, app_h1, app_h2, scorecard, default_title):
        for rec in (app_h1, app_h2):
            if rec:
                pname = getattr(rec, 'planning_name', False)
                if pname:
                    return pname
                if getattr(rec, 'scorecard_id', False) and getattr(rec.scorecard_id, 'name', False):
                    return rec.scorecard_id.name
                if getattr(rec, 'name', False):
                    return rec.name
        if scorecard and getattr(scorecard, 'name', False):
            return scorecard.name
        return default_title

    def _collect_report_rows(self):
        self.ensure_one()
        rows = []
        fy = self.fiscal_year_id
        selected_tier = self.tier
        target_ou = self.operating_unit_id

        # -------------------------------------------------------------
        # Tier 1 (Corporate / CEO)
        # -------------------------------------------------------------
        if selected_tier in ('all', 'tier1'):
            t1_domain = [('fiscal_year_id', '=', fy.id)]
            t1_appraisals = self.env['corporate.appraisal'].sudo().search(t1_domain)
            
            # Map H1 and H2 for Corporate
            ceo_apps_by_emp = {}
            for app in t1_appraisals:
                emp_id = app.employee_id.id if app.employee_id else 0
                if emp_id not in ceo_apps_by_emp:
                    ceo_apps_by_emp[emp_id] = {'H1': None, 'H2': None, 'other': []}
                pt = detect_period_type(app.appraisal_period_id)
                if pt == 'H1' and not ceo_apps_by_emp[emp_id]['H1']:
                    ceo_apps_by_emp[emp_id]['H1'] = app
                elif pt == 'H2' and not ceo_apps_by_emp[emp_id]['H2']:
                    ceo_apps_by_emp[emp_id]['H2'] = app
                else:
                    ceo_apps_by_emp[emp_id]['other'].append(app)

            # If no appraisals found, also check corporate scorecard to show corporate placeholder
            if not ceo_apps_by_emp:
                cs_records = self.env['corporate.scorecard'].sudo().search(t1_domain)
                for cs in cs_records:
                    emp_id = cs.employee_id.id if cs.employee_id else 0
                    if emp_id not in ceo_apps_by_emp:
                        ceo_apps_by_emp[emp_id] = {'H1': None, 'H2': None, 'scorecard': cs}

            for emp_id, data in ceo_apps_by_emp.items():
                app_h1 = data.get('H1')
                app_h2 = data.get('H2')
                cs = data.get('scorecard') or (app_h1.scorecard_id if app_h1 else (app_h2.scorecard_id if app_h2 else False))
                emp = (app_h1.employee_id if app_h1 else (app_h2.employee_id if app_h2 else (cs.employee_id if cs else False)))
                if not emp:
                    emp = self.env.user.employee_id

                emp_code = (
                    getattr(emp, 'employee_identification', False)
                    or getattr(emp, 'identification_id', False)
                    or getattr(emp, 'barcode', '')
                    or (str(emp.id) if emp else 'CEO-01')
                )
                emp_name = emp.name if emp else 'Chief Executive Officer'
                ou = (app_h1.operating_unit_id if app_h1 and app_h1.operating_unit_id else 
                     (app_h2.operating_unit_id if app_h2 and app_h2.operating_unit_id else 
                     (cs.operating_unit_id if cs and cs.operating_unit_id else getattr(emp, 'default_operating_unit_id', False))))

                sol_id = getattr(ou, 'code', '') or getattr(ou, 'sol_id', '') or '001'
                ou_name = ou.name if ou else 'Chief Executive Office'
                planning_name = self._get_record_planning_name(app_h1, app_h2, cs, f"Corporate Scorecard {fy.name}")

                # Scores: In Tier 1, employee score = operating score = average score
                score_h1 = round(app_h1.employee_score, 2) if app_h1 and app_h1.employee_score else 0.0
                score_h2 = round(app_h2.employee_score, 2) if app_h2 and app_h2.employee_score else 0.0

                status_h1 = self._format_status_label(app_h1.state if app_h1 else 'not_created', 'corporate.appraisal')
                status_h2 = self._format_status_label(app_h2.state if app_h2 else 'not_created', 'corporate.appraisal')

                # Annual Score: (h1 average + h2 average) / 2
                annual = round((score_h1 + score_h2) / 2.0, 2)

                rows.append({
                    'employee_id': emp.id if emp else False,
                    'employee_code': emp_code,
                    'employee_name': emp_name,
                    'tier': 'tier1',
                    'tier_label': 'Tier 1 (Corporate)',
                    'sol_id': sol_id,
                    'operating_unit_id': ou.id if ou else False,
                    'operating_unit_name': ou_name,
                    'planning_name': planning_name,
                    'fiscal_year_id': fy.id,
                    'fiscal_year_name': fy.name,
                    'appraisal_status_h1': status_h1,
                    'appraisal_status_h2': status_h2,
                    'overall_status': f"H1: {status_h1} | H2: {status_h2}",
                    'employee_score_h1': score_h1,
                    'operating_score_h1': score_h1,
                    'average_score_h1': score_h1,
                    'employee_score_h2': score_h2,
                    'operating_score_h2': score_h2,
                    'average_score_h2': score_h2,
                    'annual_score': annual,
                    'performance_rating': self._get_rating_for_score(annual),
                })

        # -------------------------------------------------------------
        # Tier 2 (Operating Unit / Division)
        # -------------------------------------------------------------
        if selected_tier in ('all', 'tier2'):
            t2_domain = [('fiscal_year_id', '=', fy.id)]
            if target_ou:
                t2_domain.append(('operating_unit_id', '=', target_ou.id))

            t2_appraisals = self.env['t2.appraisal'].sudo().search(t2_domain)
            t2_by_unit = {}
            for app in t2_appraisals:
                ou_id = app.operating_unit_id.id if app.operating_unit_id else 0
                if ou_id not in t2_by_unit:
                    t2_by_unit[ou_id] = {'H1': None, 'H2': None, 'unit': app.operating_unit_id, 'emp': app.employee_id}
                pt = detect_period_type(app.appraisal_period_id)
                if pt == 'H1' and not t2_by_unit[ou_id]['H1']:
                    t2_by_unit[ou_id]['H1'] = app
                elif pt == 'H2' and not t2_by_unit[ou_id]['H2']:
                    t2_by_unit[ou_id]['H2'] = app

            # Also check T2 scorecards to ensure units with scorecards are covered
            sc2_records = self.env['t2.scorecard'].sudo().search(t2_domain)
            for sc in sc2_records:
                ou_id = sc.operating_unit_id.id if sc.operating_unit_id else 0
                if ou_id not in t2_by_unit:
                    t2_by_unit[ou_id] = {'H1': None, 'H2': None, 'unit': sc.operating_unit_id, 'scorecard': sc}

            for ou_id, data in t2_by_unit.items():
                app_h1 = data.get('H1')
                app_h2 = data.get('H2')
                sc = data.get('scorecard') or (app_h1.scorecard_id if app_h1 else (app_h2.scorecard_id if app_h2 else False))
                ou = data.get('unit') or (app_h1.operating_unit_id if app_h1 else (app_h2.operating_unit_id if app_h2 else False))
                
                # Exclude Tier 1 Corporate unit if accidentally in T2
                if ou and ('chief executive' in (ou.name or '').lower() or (getattr(ou, 'code', '') or '').upper() == 'CEO'):
                    continue

                emp = (app_h1.employee_id if app_h1 else 
                      (app_h2.employee_id if app_h2 else 
                      (sc.employee_id if sc else (ou.manager_id if ou else False))))

                emp_code = (
                    getattr(emp, 'employee_identification', False)
                    or getattr(emp, 'identification_id', False)
                    or getattr(emp, 'barcode', '')
                    or (str(emp.id) if emp else '')
                )
                emp_name = emp.name if emp else (ou.manager_id.name if ou and ou.manager_id else 'Manager Not Assigned')
                sol_id = getattr(ou, 'code', '') or getattr(ou, 'sol_id', '') or ''
                ou_name = ou.name if ou else 'Unnamed Unit'
                planning_name = self._get_record_planning_name(app_h1, app_h2, sc, f"{ou_name} Plan {fy.name}")

                # Scores: In Tier 2, employee score = operating score = average score
                score_h1 = round(app_h1.employee_score, 2) if app_h1 and app_h1.employee_score else 0.0
                score_h2 = round(app_h2.employee_score, 2) if app_h2 and app_h2.employee_score else 0.0

                status_h1 = self._format_status_label(app_h1.state if app_h1 else 'not_created', 't2.appraisal')
                status_h2 = self._format_status_label(app_h2.state if app_h2 else 'not_created', 't2.appraisal')

                # Annual Score: (h1 average + h2 average) / 2
                annual = round((score_h1 + score_h2) / 2.0, 2)

                rows.append({
                    'employee_id': emp.id if emp else False,
                    'employee_code': emp_code,
                    'employee_name': emp_name,
                    'tier': 'tier2',
                    'tier_label': 'Tier 2 (Operating Unit)',
                    'sol_id': sol_id,
                    'operating_unit_id': ou.id if ou else False,
                    'operating_unit_name': ou_name,
                    'planning_name': planning_name,
                    'fiscal_year_id': fy.id,
                    'fiscal_year_name': fy.name,
                    'appraisal_status_h1': status_h1,
                    'appraisal_status_h2': status_h2,
                    'overall_status': f"H1: {status_h1} | H2: {status_h2}",
                    'employee_score_h1': score_h1,
                    'operating_score_h1': score_h1,
                    'average_score_h1': score_h1,
                    'employee_score_h2': score_h2,
                    'operating_score_h2': score_h2,
                    'average_score_h2': score_h2,
                    'annual_score': annual,
                    'performance_rating': self._get_rating_for_score(annual),
                })

        # -------------------------------------------------------------
        # Tier 3 (Individual Employee)
        # -------------------------------------------------------------
        if selected_tier in ('all', 'tier3'):
            t3_domain = [('fiscal_year_id', '=', fy.id)]
            if target_ou:
                t3_domain.append(('operating_unit_id', '=', target_ou.id))

            t3_appraisals = self.env['t3.appraisal'].sudo().search(t3_domain)
            t3_by_emp = {}
            for app in t3_appraisals:
                emp_id = app.employee_id.id if app.employee_id else 0
                if emp_id not in t3_by_emp:
                    t3_by_emp[emp_id] = {'H1': None, 'H2': None, 'emp': app.employee_id}
                pt = detect_period_type(app.appraisal_period_id)
                if pt == 'H1' and not t3_by_emp[emp_id]['H1']:
                    t3_by_emp[emp_id]['H1'] = app
                elif pt == 'H2' and not t3_by_emp[emp_id]['H2']:
                    t3_by_emp[emp_id]['H2'] = app

            # Also check T3 scorecards for employees who have scorecards in this fiscal year
            sc3_records = self.env['t3.scorecard'].sudo().search(t3_domain)
            for sc in sc3_records:
                emp_id = sc.employee_id.id if sc.employee_id else 0
                if emp_id not in t3_by_emp:
                    t3_by_emp[emp_id] = {'H1': None, 'H2': None, 'emp': sc.employee_id, 'scorecard': sc}

            for emp_id, data in t3_by_emp.items():
                app_h1 = data.get('H1')
                app_h2 = data.get('H2')
                sc = data.get('scorecard') or (app_h1.scorecard_id if app_h1 else (app_h2.scorecard_id if app_h2 else False))
                emp = data.get('emp') or (app_h1.employee_id if app_h1 else (app_h2.employee_id if app_h2 else (sc.employee_id if sc else False)))
                if not emp:
                    continue

                # Exclude CEO from Tier 3
                if 'chief executive officer' in (emp.job_id.name or '').lower() or (emp.job_id.name or '').lower() == 'ceo':
                    continue

                emp_code = (
                    getattr(emp, 'employee_identification', False)
                    or getattr(emp, 'identification_id', False)
                    or getattr(emp, 'barcode', '')
                    or str(emp.id)
                )
                emp_name = emp.name

                ou = (app_h1.operating_unit_id if app_h1 and app_h1.operating_unit_id else 
                     (app_h2.operating_unit_id if app_h2 and app_h2.operating_unit_id else 
                     (sc.operating_unit_id if sc and sc.operating_unit_id else getattr(emp, 'default_operating_unit_id', False))))

                sol_id = getattr(ou, 'code', '') or getattr(ou, 'sol_id', '') or ''
                ou_name = ou.name if ou else (emp.department_id.name if emp.department_id else 'General')
                planning_name = self._get_record_planning_name(app_h1, app_h2, sc, f"{emp_name} Scorecard {fy.name}")

                # Scores H1
                emp_score_h1 = round(app_h1.employee_score, 2) if app_h1 and app_h1.employee_score else 0.0
                ou_score_h1 = round(app_h1.work_unit_score, 2) if app_h1 and app_h1.work_unit_score else 0.0
                if app_h1:
                    avg_h1 = round(app_h1.average_score if (app_h1.work_unit_score and app_h1.average_score) else emp_score_h1, 2)
                else:
                    avg_h1 = 0.0

                # Scores H2
                emp_score_h2 = round(app_h2.employee_score, 2) if app_h2 and app_h2.employee_score else 0.0
                ou_score_h2 = round(app_h2.work_unit_score, 2) if app_h2 and app_h2.work_unit_score else 0.0
                if app_h2:
                    avg_h2 = round(app_h2.average_score if (app_h2.work_unit_score and app_h2.average_score) else emp_score_h2, 2)
                else:
                    avg_h2 = 0.0

                status_h1 = self._format_status_label(app_h1.state if app_h1 else 'not_created', 't3.appraisal')
                status_h2 = self._format_status_label(app_h2.state if app_h2 else 'not_created', 't3.appraisal')

                # Annual Score = (average h1 + average h2) / 2
                annual = round((avg_h1 + avg_h2) / 2.0, 2)

                rows.append({
                    'employee_id': emp.id,
                    'employee_code': emp_code,
                    'employee_name': emp_name,
                    'tier': 'tier3',
                    'tier_label': 'Tier 3 (Employee)',
                    'sol_id': sol_id,
                    'operating_unit_id': ou.id if ou else False,
                    'operating_unit_name': ou_name,
                    'planning_name': planning_name,
                    'fiscal_year_id': fy.id,
                    'fiscal_year_name': fy.name,
                    'appraisal_status_h1': status_h1,
                    'appraisal_status_h2': status_h2,
                    'overall_status': f"H1: {status_h1} | H2: {status_h2}",
                    'employee_score_h1': emp_score_h1,
                    'operating_score_h1': ou_score_h1,
                    'average_score_h1': avg_h1,
                    'employee_score_h2': emp_score_h2,
                    'operating_score_h2': ou_score_h2,
                    'average_score_h2': avg_h2,
                    'annual_score': annual,
                    'performance_rating': self._get_rating_for_score(annual),
                })

        return rows

    def _check_allowed_access(self):
        user = self.env.user
        allowed = (
            user.has_group('performance_management.group_performance_admin') or
            user.has_group('performance_management.group_performance_planning') or
            user.has_group('performance_management.group_performance_hr') or
            user.has_group('base.group_system') or
            self.env.is_admin()
        )
        if not allowed:
            raise AccessError(_("Access Denied: Only Administrator, Planning, and HR roles are authorized to access this report."))

    def action_view_report(self):
        self.ensure_one()
        self._check_allowed_access()
        # Clean previous lines for this wizard
        self.report_line_ids.unlink()

        # Build lines
        row_data = self._collect_report_rows()
        if not row_data:
            raise UserError(f"No performance scorecard or appraisal records found for Fiscal Year '{self.fiscal_year_id.name}'.")

        ReportLine = self.env['performance.comprehensive.report'].sudo()
        created_lines = []
        for r in row_data:
            r['wizard_id'] = self.id
            created_lines.append(ReportLine.create(r).id)

        tree_view_id = self.env.ref('performance_management.view_performance_comprehensive_report_tree').id
        pivot_view_id = self.env.ref('performance_management.view_performance_comprehensive_report_pivot').id

        return {
            'name': f"Performance Comprehensive Report - {self.fiscal_year_id.name}",
            'type': 'ir.actions.act_window',
            'res_model': 'performance.comprehensive.report',
            'view_mode': 'list,pivot',
            'views': [[tree_view_id, 'list'], [pivot_view_id, 'pivot']],
            'domain': [('wizard_id', '=', self.id)],
            'context': {
                'search_default_group_tier': 1,
                'search_default_group_operating_unit': 1,
            },
            'target': 'current',
        }

    def action_export_excel(self):
        self.ensure_one()
        self._check_allowed_access()
        if not xlsxwriter:
            raise UserError("The Python library 'xlsxwriter' is required to export to Excel.")

        rows = self._collect_report_rows()
        if not rows:
            raise UserError(f"No performance scorecard or appraisal records found for Fiscal Year '{self.fiscal_year_id.name}'.")

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Performance Report')

        # Formatting styles
        header_fmt = workbook.add_format({
            'bold': True,
            'bg_color': '#1d2b32',
            'font_color': '#ffffff',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
        })
        h1_fmt = workbook.add_format({
            'bold': True,
            'bg_color': '#425727',
            'font_color': '#ffffff',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
        })
        h2_fmt = workbook.add_format({
            'bold': True,
            'bg_color': '#541718',
            'font_color': '#ffffff',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
        })
        annual_fmt = workbook.add_format({
            'bold': True,
            'bg_color': '#c17540',
            'font_color': '#ffffff',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
        })

        title_fmt = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'font_color': '#1d2b32',
        })
        subtitle_fmt = workbook.add_format({
            'italic': True,
            'font_size': 10,
            'font_color': '#475569',
        })

        cell_fmt = workbook.add_format({'font_size': 9, 'border': 1, 'valign': 'vcenter'})
        num_fmt = workbook.add_format({'font_size': 9, 'border': 1, 'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
        bold_num_fmt = workbook.add_format({'font_size': 9, 'bold': True, 'border': 1, 'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter', 'bg_color': '#fef3c7'})

        # Title block
        worksheet.write(0, 0, f"COMPREHENSIVE PERFORMANCE MANAGEMENT REPORT", title_fmt)
        worksheet.write(1, 0, f"Fiscal Year: {self.fiscal_year_id.name} | Tier: {dict(self._fields['tier'].selection).get(self.tier, 'All')} | Total Records: {len(rows)}", subtitle_fmt)

        headers = [
            ("Employee ID", header_fmt),
            ("Employee Name", header_fmt),
            ("Tier", header_fmt),
            ("SOL ID", header_fmt),
            ("Operating Name", header_fmt),
            ("Planning Name", header_fmt),
            ("Fiscal Year", header_fmt),
            ("H1 Status", h1_fmt),
            ("Employee Score H1", h1_fmt),
            ("Operating Score H1", h1_fmt),
            ("Average Score H1", h1_fmt),
            ("H2 Status", h2_fmt),
            ("Employee Score H2", h2_fmt),
            ("Operating Score H2", h2_fmt),
            ("Average Score H2", h2_fmt),
            ("Employee Annual Score", annual_fmt),
            ("Performance Rating", annual_fmt),
        ]

        # Write Headers
        row_idx = 3
        for col_idx, (col_name, fmt) in enumerate(headers):
            worksheet.write(row_idx, col_idx, col_name, fmt)

        # Write Data
        row_idx += 1
        for item in rows:
            worksheet.write(row_idx, 0, item.get('employee_code') or '', cell_fmt)
            worksheet.write(row_idx, 1, item.get('employee_name') or '', cell_fmt)
            worksheet.write(row_idx, 2, item.get('tier_label') or '', cell_fmt)
            worksheet.write(row_idx, 3, item.get('sol_id') or '', cell_fmt)
            worksheet.write(row_idx, 4, item.get('operating_unit_name') or '', cell_fmt)
            worksheet.write(row_idx, 5, item.get('planning_name') or '', cell_fmt)
            worksheet.write(row_idx, 6, item.get('fiscal_year_name') or '', cell_fmt)
            worksheet.write(row_idx, 7, item.get('appraisal_status_h1') or '', cell_fmt)
            worksheet.write_number(row_idx, 8, item.get('employee_score_h1') or 0.0, num_fmt)
            worksheet.write_number(row_idx, 9, item.get('operating_score_h1') or 0.0, num_fmt)
            worksheet.write_number(row_idx, 10, item.get('average_score_h1') or 0.0, num_fmt)
            worksheet.write(row_idx, 11, item.get('appraisal_status_h2') or '', cell_fmt)
            worksheet.write_number(row_idx, 12, item.get('employee_score_h2') or 0.0, num_fmt)
            worksheet.write_number(row_idx, 13, item.get('operating_score_h2') or 0.0, num_fmt)
            worksheet.write_number(row_idx, 14, item.get('average_score_h2') or 0.0, num_fmt)
            worksheet.write_number(row_idx, 15, item.get('annual_score') or 0.0, bold_num_fmt)
            worksheet.write(row_idx, 16, item.get('performance_rating') or '', cell_fmt)
            row_idx += 1

        # Set column widths
        worksheet.set_column(0, 0, 14)  # Emp ID
        worksheet.set_column(1, 1, 24)  # Emp Name
        worksheet.set_column(2, 2, 18)  # Tier
        worksheet.set_column(3, 3, 10)  # SOL ID
        worksheet.set_column(4, 4, 25)  # Operating Name
        worksheet.set_column(5, 5, 26)  # Planning Name
        worksheet.set_column(6, 6, 15)  # Fiscal Year
        worksheet.set_column(7, 7, 13)  # H1 Status
        worksheet.set_column(8, 10, 16) # H1 Scores
        worksheet.set_column(11, 11, 13) # H2 Status
        worksheet.set_column(12, 14, 16) # H2 Scores
        worksheet.set_column(15, 15, 20) # Annual Score
        worksheet.set_column(16, 16, 18) # Rating

        workbook.close()
        output.seek(0)
        file_data = base64.b64encode(output.read())
        output.close()

        filename = f"Performance_Report_{self.fiscal_year_id.name.replace(' ', '_')}.xlsx"
        self.write({
            'excel_file': file_data,
            'excel_filename': filename,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model=performance.comprehensive.report.wizard&id={self.id}&field=excel_file&download=true&filename={filename}',
            'target': 'self',
        }

    def action_print_pdf(self):
        self.ensure_one()
        self._check_allowed_access()
        # Clean previous lines and populate lines
        self.report_line_ids.unlink()
        row_data = self._collect_report_rows()
        if not row_data:
            raise UserError(f"No performance scorecard or appraisal records found for Fiscal Year '{self.fiscal_year_id.name}'.")

        ReportLine = self.env['performance.comprehensive.report'].sudo()
        for r in row_data:
            r['wizard_id'] = self.id
            ReportLine.create(r)

        return self.env.ref('performance_management.action_report_comprehensive_performance_pdf').report_action(self)
