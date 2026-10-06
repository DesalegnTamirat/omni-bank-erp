# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import io
import base64

try:
    import openpyxl
except ImportError:
    openpyxl = None


class EdsTemplateImportWizard(models.TransientModel):
    """Wizard to parse and import EDS 2026/27 business templates.
    Supports importing from multi-sheet workbook (EDS_LD_Templates_2026-27.xlsx)
    or individual sheets for TNA, Curriculum, Calendar, and Providers.
    """
    _name = 'eds.template.import.wizard'
    _description = 'EDS Business Template Import Wizard'

    file_data = fields.Binary(string='Excel File (.xlsx)', required=True)
    file_name = fields.Char(string='File Name')
    template_type = fields.Selection([
        ('auto', 'Full Workbook (Auto-detect all sheets)'),
        ('tna', 'TNA Needs Assessment (TNA Sheet)'),
        ('curriculum', 'Curriculum & Courses (Curriculum Sheet)'),
        ('calendar', 'Bank-level Calendar (Cal_BankLevel Sheet)'),
        ('providers', 'External Providers (Provider_Register Sheet)'),
    ], string='Template / Sheet Type', default='auto', required=True)

    fiscal_year = fields.Char(string='Fiscal Year', default='2026', required=True)
    annual_plan_id = fields.Many2one('eds.annual.plan', string='Target Annual Plan',
                                     help='Target annual plan when importing calendar lines')
    tna_cycle_id = fields.Many2one('eds.tna.cycle', string='Target TNA Cycle',
                                   help='Target cycle for importing TNA entries')

    result_summary = fields.Text(string='Import Summary', readonly=True)

    def _find_header_and_cols(self, ws, key_patterns, default_start_row=5, default_cols=None):
        """Dynamically detects header row by searching top 15 rows for key column patterns.
        Returns (start_row, col_map) where col_map maps key -> 1-based column index.
        """
        header_row = None
        col_map = {}
        for r in range(1, min(15, ws.max_row + 1)):
            row_texts = {c: str(ws.cell(r, c).value or '').strip().lower() for c in range(1, ws.max_column + 1)}
            temp_map = {}
            matches = 0
            for key, patterns in key_patterns.items():
                for c, text in row_texts.items():
                    if not text:
                        continue
                    if any(p in text for p in patterns):
                        temp_map[key] = c
                        matches += 1
                        break
            if matches >= 2:
                header_row = r
                col_map = temp_map
                break

        if header_row:
            return header_row + 1, col_map
        return default_start_row, default_cols or {}

    def action_import(self):
        self.ensure_one()
        if not openpyxl:
            raise UserError(_('openpyxl Python library is required to import Excel templates.'))
        if not self.file_data:
            raise UserError(_('Please upload an Excel file (.xlsx) to proceed.'))

        file_bytes = base64.b64decode(self.file_data)
        wb = openpyxl.load_workbook(filename=io.BytesIO(file_bytes), data_only=True)

        summary_lines = []

        if self.template_type in ('auto', 'tna'):
            tna_sheet_name = next((s for s in wb.sheetnames if 'tna' in s.lower()), None)
            if tna_sheet_name:
                res = self._import_tna_sheet(wb[tna_sheet_name])
                summary_lines.append(f"TNA Sheet: {res.get('created', 0)} training needs imported, {res.get('skipped', 0)} skipped.")
            elif self.template_type == 'tna':
                res = self._import_tna_sheet(wb.active)
                summary_lines.append(f"Active Sheet (TNA): {res.get('created', 0)} training needs imported.")

        if self.template_type in ('auto', 'curriculum'):
            curr_sheet_name = next((s for s in wb.sheetnames if 'curriculum' in s.lower()), None)
            if curr_sheet_name:
                res = self._import_curriculum_sheet(wb[curr_sheet_name])
                summary_lines.append(f"Curriculum Sheet: {res.get('courses', 0)} courses created/updated, {res.get('topics', 0)} module topics registered.")
            elif self.template_type == 'curriculum':
                res = self._import_curriculum_sheet(wb.active)
                summary_lines.append(f"Active Sheet (Curriculum): {res.get('courses', 0)} courses created/updated.")

        if self.template_type in ('auto', 'calendar'):
            cal_sheet_name = next((s for s in wb.sheetnames if 'cal' in s.lower() or 'calendar' in s.lower()), None)
            if cal_sheet_name:
                res = self._import_calendar_sheet(wb[cal_sheet_name])
                summary_lines.append(f"Calendar Sheet: {res.get('lines', 0)} plan lines created/updated.")
            elif self.template_type == 'calendar':
                res = self._import_calendar_sheet(wb.active)
                summary_lines.append(f"Active Sheet (Calendar): {res.get('lines', 0)} plan lines created/updated.")

        if self.template_type in ('auto', 'providers'):
            prov_sheet_name = next((s for s in wb.sheetnames if 'provider' in s.lower()), None)
            if prov_sheet_name:
                res = self._import_provider_sheet(wb[prov_sheet_name])
                summary_lines.append(f"Provider Sheet: {res.get('created', 0)} external providers registered/updated.")
            elif self.template_type == 'providers':
                res = self._import_provider_sheet(wb.active)
                summary_lines.append(f"Active Sheet (Providers): {res.get('created', 0)} external providers registered/updated.")

        if not summary_lines:
            summary_lines.append("No matching template sheets found in the uploaded workbook. Available sheets: " + ", ".join(wb.sheetnames))

        self.result_summary = "\n".join(summary_lines)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.template.import.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _import_tna_sheet(self, ws):
        cycle = self.tna_cycle_id
        if not cycle:
            cycle = self.env['eds.tna.cycle'].search([
                ('fiscal_year', '=', self.fiscal_year),
                ('state', 'in', ('collecting', 'draft'))
            ], limit=1)
        if not cycle:
            cycle = self.env['eds.tna.cycle'].search([], order='id desc', limit=1)

        key_patterns = {
            'work_unit': ['work unit', 'unit', 'department', 'branch'],
            'topic': ['training topic', 'course', 'topic'],
            'target_group': ['target group', 'target', 'audience'],
            'participants': ['estimated no of participants', 'participants', 'headcount', 'pax'],
            'competency': ['related competency', 'competency'],
            'comp_level': ['competency level', 'level'],
            'priority': ['priority', 'urgency'],
            'delivery': ['delivery method', 'delivery mode', 'delivery'],
            'quarter': ['preferred quarter', 'quarter'],
            'remark': ['remark', 'notes', 'justification'],
        }
        default_cols = {
            'work_unit': 2, 'topic': 3, 'target_group': 4, 'participants': 5,
            'competency': 6, 'comp_level': 7, 'priority': 8, 'delivery': 9, 'quarter': 10, 'remark': 11
        }
        start_row, cols = self._find_header_and_cols(ws, key_patterns, 5, default_cols)

        created, skipped = 0, 0
        OperatingUnit = self.env['operating.unit']
        Competency = self.env['competency.competency']
        TnaEntry = self.env['eds.tna.entry']

        for r in range(start_row, ws.max_row + 1):
            work_unit_name = str(ws.cell(r, cols.get('work_unit', 2)).value or '').strip() if cols.get('work_unit') else ''
            topic = str(ws.cell(r, cols.get('topic', 3)).value or '').strip() if cols.get('topic') else ''
            if not topic:
                continue

            target_group = str(ws.cell(r, cols.get('target_group', 4)).value or '').strip().lower() if cols.get('target_group') else ''
            pax = ws.cell(r, cols.get('participants', 5)).value if cols.get('participants') else 1
            comp_name = str(ws.cell(r, cols.get('competency', 6)).value or '').strip() if cols.get('competency') else ''
            comp_level = str(ws.cell(r, cols.get('comp_level', 7)).value or '').strip().lower() if cols.get('comp_level') else ''
            priority_val = str(ws.cell(r, cols.get('priority', 8)).value or '').strip().lower() if cols.get('priority') else ''
            delivery = str(ws.cell(r, cols.get('delivery', 9)).value or '').strip().lower() if cols.get('delivery') else ''
            quarter_val = str(ws.cell(r, cols.get('quarter', 10)).value or '').strip().lower() if cols.get('quarter') else ''
            remark = str(ws.cell(r, cols.get('remark', 11)).value or '').strip() if cols.get('remark') else ''

            audience_map = {'bod': 'bod', 'smc': 'smc', 'mlm': 'mlm', 'below mlm': 'below_mlm', 'all staff': 'all_staff'}
            audience = audience_map.get(target_group, 'all_staff')

            delivery_map = {
                'classroom': 'classroom', 'virtual': 'virtual', 'e-learning': 'e_learning',
                'blended': 'blended', 'workshop': 'workshop', 'on-the-job': 'on_the_job',
                'coaching/mentoring': 'coaching', 'summit/conference': 'conference',
            }
            delivery_mode = delivery_map.get(delivery, 'classroom')

            p_map = {'high': 'high', 'medium': 'medium', 'low': 'low'}
            urgency = p_map.get(priority_val, 'medium')

            q_map = {'q1': 'q1', 'q2': 'q2', 'q3': 'q3', 'q4': 'q4'}
            quarter = q_map.get(quarter_val, False)

            lvl_map = {'basic': 'basic', 'intermediate': 'intermediate', 'advanced': 'advanced', 'expert': 'expert'}
            req_level = lvl_map.get(comp_level, 'intermediate')

            ou = OperatingUnit.search([('name', '=ilike', work_unit_name)], limit=1) if work_unit_name else False
            comp = Competency.search([('name', '=ilike', comp_name)], limit=1) if comp_name else False

            try:
                pax_int = int(pax or 1)
            except (ValueError, TypeError):
                pax_int = 1

            vals = {
                'cycle_id': cycle.id if cycle else False,
                'proposed_program': topic,
                'work_unit_id': ou.id if ou else False,
                'competency_id': comp.id if comp else False,
                'target_audience': audience,
                'target_participant_count': pax_int,
                'competency_level': req_level,
                'urgency': urgency,
                'delivery_mode': delivery_mode,
                'quarter': quarter,
                'hr_target_quarter': quarter,
                'justification': remark or f"TNA requirement for {work_unit_name}",
                'state': 'submitted',
            }
            TnaEntry.create(vals)
            created += 1

        return {'created': created, 'skipped': skipped}

    def _import_curriculum_sheet(self, ws):
        Course = self.env['eds.course']
        Curriculum = self.env['eds.curriculum']
        Module = self.env['eds.curriculum.module']

        key_patterns = {
            'code': ['course code', 'code'],
            'audience': ['target audience', 'audience', 'target group'],
            'focus_area': ['focus area', 'focus'],
            'title': ['course title', 'title', 'course name'],
            'topic': ['training topic', 'topic'],
            'days': ['days', 'duration'],
            'place': ['delivery place', 'place', 'delivery method'],
        }
        default_cols = {'code': 2, 'audience': 3, 'focus_area': 4, 'title': 5, 'topic': 6, 'days': 7, 'place': 8}
        start_row, cols = self._find_header_and_cols(ws, key_patterns, 5, default_cols)

        courses_data = {}
        for r in range(start_row, ws.max_row + 1):
            code = str(ws.cell(r, cols.get('code', 2)).value or '').strip() if cols.get('code') else ''
            audience = str(ws.cell(r, cols.get('audience', 3)).value or '').strip() if cols.get('audience') else ''
            focus_area = str(ws.cell(r, cols.get('focus_area', 4)).value or '').strip() if cols.get('focus_area') else ''
            title = str(ws.cell(r, cols.get('title', 5)).value or '').strip() if cols.get('title') else ''
            topic = str(ws.cell(r, cols.get('topic', 6)).value or '').strip() if cols.get('topic') else ''
            days = ws.cell(r, cols.get('days', 7)).value if cols.get('days') else 1
            place = str(ws.cell(r, cols.get('place', 8)).value or '').strip() if cols.get('place') else ''

            if not title:
                continue

            course_key = code or title
            if course_key not in courses_data:
                courses_data[course_key] = {
                    'code': code,
                    'title': title,
                    'audience': audience,
                    'focus_area': focus_area,
                    'days': days,
                    'place': place,
                    'topics': []
                }
            if topic:
                courses_data[course_key]['topics'].append(topic)

        course_count = 0
        topic_count = 0
        for c_key, data in courses_data.items():
            domain = [('code', '=', data['code'])] if data['code'] else [('name', '=', data['title'])]
            course = Course.search(domain, limit=1)

            audience_map = {'bod': 'bod', 'smc': 'smc', 'mlm': 'mlm', 'below mlm': 'below_mlm', 'all staff': 'all_staff'}
            aud = audience_map.get(data['audience'].lower(), 'all_staff')
            place_val = 'international' if 'international' in data['place'].lower() else 'local'

            try:
                days_int = int(data['days'] or 1)
            except (ValueError, TypeError):
                days_int = 1

            vals = {
                'name': data['title'],
                'target_audience': aud,
                'duration_days': days_int,
                'delivery_place': place_val,
                'category': 'technical_compliance',
                'program_category': 'technical_functional',
                
            }
            if data['code']:
                vals['code'] = data['code']

            if course:
                course.write(vals)
            else:
                course = Course.create(vals)
            course_count += 1

            curriculum = Curriculum.search([('course_id', '=', course.id), ('version', '=', 'v1.0')], limit=1)
            if not curriculum:
                curriculum = Curriculum.create({
                    'course_id': course.id,
                    'version': 'v1.0',
                    'learning_objectives': f"Build capability in {data['focus_area'] or data['title']}",
                    'state': 'approved',
                })

            for seq, topic_name in enumerate(data['topics'], start=1):
                mod = Module.search([('curriculum_id', '=', curriculum.id), ('name', '=', topic_name)], limit=1)
                if not mod:
                    Module.create({
                        'curriculum_id': curriculum.id,
                        'name': topic_name,
                        'sequence': seq,
                        'duration_hours': 4.0,
                    })
                    topic_count += 1

        return {'courses': course_count, 'topics': topic_count}

    def _import_calendar_sheet(self, ws):
        plan = self.annual_plan_id
        if not plan:
            plan = self.env['eds.annual.plan'].search([
                ('fiscal_year', '=', self.fiscal_year),
                ('state', 'in', ('draft', 'director_review'))
            ], limit=1)
        if not plan:
            plan = self.env['eds.annual.plan'].search([], order='id desc', limit=1)
        if not plan:
            plan = self.env['eds.annual.plan'].create({
                'name': f"Annual L&D Plan {self.fiscal_year}",
                'fiscal_year': self.fiscal_year,
                'state': 'draft',
            })

        key_patterns = {
            'category': ['program category', 'category'],
            'prog_name': ['program name', 'course name', 'program'],
            'train_cat': ['training category', 'training type'],
            'target_group': ['target group', 'target audience', 'audience'],
            'quarter': ['quarter', 'period'],
            'month': ['month', 'scheduled month'],
            'days': ['duration (days)', 'duration', 'days'],
            'participants': ['participants', 'planned participants', 'pax'],
            'delivery': ['delivery method', 'method'],
            'num_sessions': ['number of sessions', 'sessions'],
            'provider_cost': ['est. provider cost', 'provider cost', 'provider rate'],
            'venue_cost': ['est. venue/lunch', 'venue cost', 'venue rate'],
        }
        default_cols = {
            'category': 2, 'prog_name': 3, 'train_cat': 4, 'target_group': 5, 'quarter': 6,
            'month': 7, 'days': 8, 'participants': 9, 'delivery': 10, 'num_sessions': 11,
            'provider_cost': 12, 'venue_cost': 14
        }
        start_row, cols = self._find_header_and_cols(ws, key_patterns, 5, default_cols)

        PlanLine = self.env['eds.annual.plan.line']
        Course = self.env['eds.course']
        lines_created = 0

        for r in range(start_row, ws.max_row + 1):
            prog_name = str(ws.cell(r, cols.get('prog_name', 3)).value or '').strip() if cols.get('prog_name') else ''
            if not prog_name:
                continue

            cat_str = str(ws.cell(r, cols.get('category', 2)).value or '').strip().lower() if cols.get('category') else ''
            train_cat_str = str(ws.cell(r, cols.get('train_cat', 4)).value or '').strip().lower() if cols.get('train_cat') else ''
            group_str = str(ws.cell(r, cols.get('target_group', 5)).value or '').strip().lower() if cols.get('target_group') else ''
            quarter_str = str(ws.cell(r, cols.get('quarter', 6)).value or '').strip().lower() if cols.get('quarter') else ''
            month_str = str(ws.cell(r, cols.get('month', 7)).value or '').strip() if cols.get('month') else ''
            days = ws.cell(r, cols.get('days', 8)).value if cols.get('days') else 1
            participants = ws.cell(r, cols.get('participants', 9)).value if cols.get('participants') else 25
            delivery_str = str(ws.cell(r, cols.get('delivery', 10)).value or '').strip().lower() if cols.get('delivery') else ''
            num_sessions = ws.cell(r, cols.get('num_sessions', 11)).value if cols.get('num_sessions') else 1
            provider_rate = ws.cell(r, cols.get('provider_cost', 12)).value if cols.get('provider_cost') else 0.0
            venue_rate = ws.cell(r, cols.get('venue_cost', 14)).value if cols.get('venue_cost') else 0.0

            prog_cat_map = {
                'induction': 'induction', 'compliance': 'compliance', 'leadership': 'leadership',
                'technical': 'technical_functional', 'functional': 'technical_functional',
                'digital': 'digital_it', 'it': 'digital_it', 'soft': 'soft_skills',
                'risk': 'risk_audit', 'audit': 'risk_audit', 'customer': 'customer_service'
            }
            category = next((v for k, v in prog_cat_map.items() if k in cat_str), 'technical_functional')

            train_map = {'in-house': 'in_house', 'in house': 'in_house', 'local': 'local_external', 'international': 'international', 'e-learning': 'e_learning'}
            train_category = train_map.get(train_cat_str, 'in_house')

            audience_map = {'bod': 'bod', 'smc': 'smc', 'mlm': 'mlm', 'below mlm': 'below_mlm', 'all staff': 'all_staff'}
            audience = audience_map.get(group_str, 'all_staff')

            q_map = {'q1': 'q1', 'q2': 'q2', 'q3': 'q3', 'q4': 'q4'}
            quarter = q_map.get(quarter_str, False)

            course = Course.search([('name', '=ilike', prog_name)], limit=1)

            try:
                days_int = int(days or 1)
            except (ValueError, TypeError):
                days_int = 1

            try:
                pax_int = int(participants or 25)
            except (ValueError, TypeError):
                pax_int = 25

            try:
                sessions_int = int(num_sessions or 1)
            except (ValueError, TypeError):
                sessions_int = 1

            try:
                prov_cost = float(provider_rate or 0.0)
            except (ValueError, TypeError):
                prov_cost = 0.0

            try:
                ven_cost = float(venue_rate or 0.0)
            except (ValueError, TypeError):
                ven_cost = 0.0

            vals = {
                'plan_id': plan.id,
                'course_id': course.id if course else False,
                'program_name': prog_name,
                'program_category': category,
                'training_category': train_category,
                'target_audience': audience,
                'quarter': quarter,
                'duration_days': days_int,
                'planned_participants': pax_int,
                'num_sessions': sessions_int,
                'est_provider_cost_per_pax': prov_cost,
                'est_venue_cost_per_pax_day': ven_cost,
                'status': 'planned',
            }
            PlanLine.create(vals)
            lines_created += 1

        return {'lines': lines_created}

    def _import_provider_sheet(self, ws):
        Provider = self.env['eds.external.provider']
        created = 0

        key_patterns = {
            'prv_code': ['provider id', 'code', 'id'],
            'name': ['provider name', 'name', 'vendor'],
            'type': ['provider type', 'type'],
            'specialization': ['specialisation', 'focus', 'specialization'],
            'contact': ['contact person', 'contact'],
            'phone': ['phone', 'mobile', 'telephone'],
            'email': ['email', 'mail'],
            'rate': ['indicative rate', 'rate', 'session fee'],
            'contract_ref': ['accreditation', 'contract ref', 'contract', 'reference'],
        }
        default_cols = {
            'prv_code': 2, 'name': 3, 'type': 4, 'specialization': 5,
            'contact': 6, 'phone': 7, 'email': 8, 'rate': 9, 'contract_ref': 10
        }
        start_row, cols = self._find_header_and_cols(ws, key_patterns, 5, default_cols)

        for r in range(start_row, ws.max_row + 1):
            prv_code = str(ws.cell(r, cols.get('prv_code', 2)).value or '').strip() if cols.get('prv_code') else ''
            name = str(ws.cell(r, cols.get('name', 3)).value or '').strip() if cols.get('name') else ''
            if not name:
                continue

            prv_type = str(ws.cell(r, cols.get('type', 4)).value or '').strip().lower() if cols.get('type') else ''
            specialization = str(ws.cell(r, cols.get('specialization', 5)).value or '').strip() if cols.get('specialization') else ''
            contact = str(ws.cell(r, cols.get('contact', 6)).value or '').strip() if cols.get('contact') else ''
            phone = str(ws.cell(r, cols.get('phone', 7)).value or '').strip() if cols.get('phone') else ''
            email = str(ws.cell(r, cols.get('email', 8)).value or '').strip() if cols.get('email') else ''
            rate = ws.cell(r, cols.get('rate', 9)).value if cols.get('rate') else 0.0
            contract_ref = str(ws.cell(r, cols.get('contract_ref', 10)).value or '').strip() if cols.get('contract_ref') else ''

            type_map = {
                'university': 'university', 'consultancy': 'consultancy',
                'vendor': 'vendor', 'individual': 'individual',
                'association': 'association', 'regulatory': 'regulatory'
            }
            provider_type = next((v for k, v in type_map.items() if k in prv_type), 'consultancy')

            try:
                rate_flt = float(rate or 0.0)
            except (ValueError, TypeError):
                rate_flt = 0.0

            vals = {
                'name': name,
                'provider_type': provider_type,
                'specialization_areas': specialization,
                'contact_name': contact,
                'phone': phone,
                'email': email,
                'rate_per_session': rate_flt,
                'accreditation': contract_ref,
                'active': True,
            }
            if prv_code:
                vals['code'] = prv_code

            prov = Provider.search([('name', '=ilike', name)], limit=1)
            if prov:
                prov.write(vals)
            else:
                Provider.create(vals)
            created += 1

        return {'created': created}
