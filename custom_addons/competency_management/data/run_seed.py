# -*- coding: utf-8 -*-
import sys
import os
import zipfile
import re
import xml.etree.ElementTree as ET

import odoo
from odoo.modules.registry import Registry
from odoo.api import Environment
from odoo.tools import config

def seed_bunna_competencies(dbname='ERP'):
    xlsx_path = '/mnt/extra-addons/competency_management/data/competency_matrix.xlsx'
    if not os.path.exists(xlsx_path):
        xlsx_path = r'd:\Bunna\Projects\ERP\docs\edited Final Comptency Matrix......xlsx'
    
    if not os.path.exists(xlsx_path):
        print(f"XLSX file not found at {xlsx_path}")
        return

    print("Extracting shared strings and sheet names from XLSX...")
    with zipfile.ZipFile(xlsx_path, 'r') as z:
        strings_xml = z.read('xl/sharedStrings.xml')
        stree = ET.fromstring(strings_xml)
        shared_strings = [''.join(t.text or '' for t in si.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')) for si in stree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si')]

        def get_val(cell):
            t = cell.attrib.get('t')
            v = cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
            if v is None: return ''
            val = v.text
            if t == 's': return shared_strings[int(val)]
            return val

        wb_xml = z.read('xl/workbook.xml')
        wbtree = ET.fromstring(wb_xml)
        sheets_info = [child.attrib['name'] for child in wbtree.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheets')]

        raw_mappings = []
        for idx, sname in enumerate(sheets_info, 1):
            if sname == 'Proficiency':
                continue
            sheet_xml = z.read(f'xl/worksheets/sheet{idx}.xml')
            stree = ET.fromstring(sheet_xml)
            rows = list(stree.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'))
            if not rows: continue
            header = [get_val(c).strip() for c in rows[0].findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c')]
            for r in rows[1:]:
                vals = [get_val(c).strip() for c in r.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c')]
                if len(vals) >= 4 and vals[1].strip():
                    cat = vals[0].strip()
                    cname = re.sub(r'\s+', ' ', vals[1].strip())
                    jtitle = re.sub(r'\s+', ' ', vals[2].strip())
                    prof = vals[3].strip()
                    wunit = vals[4].strip() if len(vals) > 4 else ''
                    raw_mappings.append((cat, cname, jtitle, prof, wunit, sname))

    print(f"Total raw matrix rows extracted: {len(raw_mappings)}")

    config['database'] = dbname
    reg = Registry(dbname)
    with reg.cursor() as cr:
        env = Environment(cr, odoo.SUPERUSER_ID, {})

        rating_model = env['competency.rating.model'].search([('code', '=', '4SCALE')], limit=1)
        if not rating_model:
            rating_model = env['competency.rating.model'].create({
                'name': '4-Point Proficiency Scale',
                'code': '4SCALE',
                'max_rating': 4,
                'description': 'Standard 4-Level scale (Level 1 Basic, Level 2 Intermediate, Level 3 Advanced, Level 4 Expert)'
            })

        core_names = {'Execution Mastery', 'Professional Authenticity', 'Ethical Influence', 'Collaboration', 'Creativity'}
        leadership_names = {'Strategy Management', 'Continuous Improvement', 'Prudential Decision Making', 'Self Leadership', 'People Leadership', 'Ambidexterity Leadership', 'Ambidextrous Leadership', 'Self-Leadership'}

        distinct_comps = {}
        for cat, cname, jtitle, prof, wunit, sname in raw_mappings:
            cname_clean = cname.replace('Ambidexterity Leadership', 'Ambidextrous Leadership').replace('Self Leadership', 'Self-Leadership')
            cat_lower = cat.lower()
            if 'core' in cat_lower or cname_clean in core_names:
                pillar = 'core'
            elif 'lead' in cat_lower or cname_clean in leadership_names:
                pillar = 'leadership'
            else:
                pillar = 'technical'
            
            if cname_clean not in distinct_comps:
                distinct_comps[cname_clean] = (pillar, sname)

        print(f"Distinct Competencies to create/ensure: {len(distinct_comps)}")

        tech_counter = 1
        comp_records = {}
        for cname, (pillar, domain) in sorted(distinct_comps.items()):
            comp = env['competency.competency'].search([('name', '=ilike', cname)], limit=1)
            if not comp:
                if pillar == 'core':
                    c_cnt = len([c for c in comp_records.values() if c.pillar == 'core']) + 1
                    code = f"CORE-{c_cnt:02d}"
                elif pillar == 'leadership':
                    c_cnt = len([c for c in comp_records.values() if c.pillar == 'leadership']) + 1
                    code = f"LEAD-{c_cnt:02d}"
                else:
                    code = f"TECH-{tech_counter:03d}"
                    tech_counter += 1

                comp = env['competency.competency'].create({
                    'name': cname,
                    'code': code,
                    'pillar': pillar,
                    'functional_domain': domain if pillar == 'technical' else 'Bank-Wide',
                    'definition': f"Bunna Bank {pillar.capitalize()} Competency: {cname}",
                    'rating_model_id': rating_model.id,
                    'state': 'approved',
                    'status': 'active',
                })
            else:
                comp.with_context(force_write=True).write({
                    'state': 'approved',
                    'status': 'active',
                    'pillar': pillar,
                })
            comp_records[cname] = comp

            for lvl_val, lvl_name, lvl_def in [
                ('1', 'Basic', 'Demonstrates foundational understanding. Applies basic concepts in routine situations with guidance.'),
                ('2', 'Intermediate', 'Demonstrates solid working knowledge. Applies competency independently in standard situations.'),
                ('3', 'Advanced', 'Demonstrates deep expertise. Applies competency consistently across complex and varied situations.'),
                ('4', 'Expert', 'Demonstrates mastery and thought leadership. Shapes organizational direction and builds capability.'),
            ]:
                existing_lvl = env['competency.proficiency.level'].search([
                    ('competency_id', '=', comp.id),
                    ('level', '=', lvl_val)
                ], limit=1)
                if not existing_lvl:
                    env['competency.proficiency.level'].create({
                        'competency_id': comp.id,
                        'level': lvl_val,
                        'definition': lvl_def,
                        'behavioral_indicators': f"Level {lvl_val} ({lvl_name}) behavioral indicators for {cname}.",
                    })

        # Remove non-matrix competencies if any exist
        matrix_comp_ids = [c.id for c in comp_records.values()]
        non_matrix_comps = env['competency.competency'].search([('id', 'not in', matrix_comp_ids)])
        if non_matrix_comps:
            print(f"Removing {len(non_matrix_comps)} non-matrix competencies...")
            for nmc in non_matrix_comps:
                try:
                    nmc.unlink()
                except Exception as e:
                    print(f"Could not unlink non-matrix competency {nmc.name}: {e}")

        # 3. Create Job Role Mappings
        job_mappings = {}
        for cat, cname, jtitle, prof, wunit, sname in raw_mappings:
            if not jtitle: continue
            cname_clean = cname.replace('Ambidexterity Leadership', 'Ambidextrous Leadership').replace('Self Leadership', 'Self-Leadership')
            comp = comp_records.get(cname_clean)
            if not comp: continue
            
            prof_str = str(prof).strip()
            req_prof = prof_str if prof_str in ('1', '2', '3', '4') else '2'
            job_mappings.setdefault(jtitle, {})[comp.id] = req_prof

        print(f"Distinct Job Positions in Matrix: {len(job_mappings)}")

        mapping_count = 0
        matrix_job_ids = []
        for jtitle, comp_dict in job_mappings.items():
            job = env['hr.job'].search([('name', '=ilike', jtitle)], limit=1)
            if not job:
                job = env['hr.job'].create({
                    'name': jtitle,
                    'description': f"Job Position for {jtitle}",
                })
            matrix_job_ids.append(job.id)

            mapping = env['competency.role.mapping'].search([('job_position_id', '=', job.id)], limit=1)
            if not mapping:
                mapping = env['competency.role.mapping'].create({
                    'job_position_id': job.id,
                    'version': 'v1.0',
                    'state': 'draft',
                    'effective_date': odoo.fields.Date.context_today(env['competency.role.mapping']),
                    'change_description': 'Initial Bunna Bank Competency Framework role mapping import',
                })

            existing_line_map = {l.competency_id.id: l for l in mapping.line_ids}
            line_create_vals = []
            for cid, req_p in comp_dict.items():
                if cid in existing_line_map:
                    existing_line_map[cid].write({'required_proficiency': req_p})
                else:
                    line_create_vals.append({
                        'mapping_id': mapping.id,
                        'competency_id': cid,
                        'required_proficiency': req_p,
                        'weight': 1.0,
                    })
            if line_create_vals:
                env['competency.role.mapping.line'].create(line_create_vals)

            # Unlink lines for competencies not in matrix for this job position
            extra_lines = mapping.line_ids.filtered(lambda l: l.competency_id.id not in comp_dict)
            if extra_lines:
                extra_lines.unlink()

            if mapping.state != 'approved':
                mapping.with_context(force_write=True).write({
                    'state': 'approved',
                    'approved_by_id': env.user.id,
                    'approval_date': odoo.fields.Datetime.now(),
                })
            mapping_count += 1

        # Automatically Map All Remaining hr.job Positions to Approved Role Mappings
        all_jobs = env['hr.job'].search([])
        approved_bm = list(env['competency.role.mapping'].search([('state', '=', 'approved')]))
        default_bm = approved_bm[0] if approved_bm else False
        
        for job in all_jobs:
            m = env['competency.role.mapping'].search([('job_position_id', '=', job.id)], limit=1)
            if not m:
                j_name = (job.name or '').lower()
                best_bm = default_bm
                if approved_bm:
                    for bm in approved_bm:
                        bm_title = (bm.job_position_id.name or '').lower()
                        if ('manager' in j_name and 'manager' in bm_title) or \
                           ('leader' in j_name and 'leader' in bm_title) or \
                           ('officer' in j_name and 'officer' in bm_title) or \
                           ('chief' in j_name and 'chief' in bm_title) or \
                           ('director' in j_name and 'director' in bm_title):
                            best_bm = bm
                            break
                m = env['competency.role.mapping'].create({
                    'job_position_id': job.id,
                    'version': 'v1.0',
                    'state': 'approved',
                    'approved_by_id': env.user.id,
                    'approval_date': odoo.fields.Datetime.now(),
                    'change_description': 'Auto-mapped via Bunna Bank Competency Framework Governance',
                })
                if best_bm:
                    line_vals = [{'mapping_id': m.id, 'competency_id': l.competency_id.id, 'required_proficiency': l.required_proficiency, 'weight': l.weight or 1.0} for l in best_bm.line_ids]
                    if line_vals:
                        env['competency.role.mapping.line'].create(line_vals)
            elif m.state != 'approved':
                m.with_context(force_write=True).write({'state': 'approved'})

        # 4. Seed Matrix Configuration (Job Grade & Job Position Guidelines)
        matrix_config = env['competency.matrix.config'].get_active_config()
        matrix_config._seed_matrix_guidelines()

        # 5. Seed 3 Assessment Cycles (2024, 2025, 2026) & Populate Multi-Cycle Assessments
        Cycle = env['competency.assessment.cycle']
        Assessment = env['competency.assessment']
        AssessmentLine = env['competency.assessment.line']
        Employee = env['hr.employee']
        RoleMapping = env['competency.role.mapping']

        c2024 = Cycle.search([('code', '=', 'CYC-2024')], limit=1)
        if not c2024:
            c2024 = Cycle.create({
                'name': '2024 Annual Competency Assessment Cycle',
                'code': 'CYC-2024',
                'period_start': '2024-01-01',
                'period_end': '2024-12-31',
                'assessment_deadline': '2024-12-15',
                'state': 'closed',
            })

        c2025 = Cycle.search([('code', '=', 'CYC-2025')], limit=1)
        if not c2025:
            c2025 = Cycle.create({
                'name': '2025 Annual Competency Assessment Cycle',
                'code': 'CYC-2025',
                'period_start': '2025-01-01',
                'period_end': '2025-12-31',
                'assessment_deadline': '2025-12-15',
                'state': 'closed',
            })

        c2026 = Cycle.search([('code', '=', 'CYC-2026')], limit=1)
        if not c2026:
            c2026 = Cycle.create({
                'name': '2026 Annual Competency Assessment Cycle',
                'code': 'CYC-2026',
                'period_start': '2026-01-01',
                'period_end': '2026-12-31',
                'assessment_deadline': '2026-12-15',
                'state': 'open',
            })

        # Sample active employees to populate multi-cycle historical assessments
        mapped_jobs = RoleMapping.search([('state', '=', 'approved')]).mapped('job_position_id')
        sample_employees = Employee.search([('job_id', 'in', mapped_jobs.ids)], limit=120)

        print(f"Populating 3-Cycle Assessment Data for {len(sample_employees)} Employees...")

        asm_count = 0
        for emp in sample_employees:
            mapping = RoleMapping.search([('job_position_id', '=', emp.job_id.id), ('state', '=', 'approved')], limit=1)
            if not mapping or not mapping.line_ids:
                continue

            for cycle, c_year, default_state in [(c2024, 2024, 'approved'), (c2025, 2025, 'approved'), (c2026, 2026, 'approved')]:
                existing_asm = Assessment.search([('employee_id', '=', emp.id), ('cycle_id', '=', cycle.id)], limit=1)
                if not existing_asm:
                    asm = Assessment.create({
                        'employee_id': emp.id,
                        'cycle_id': cycle.id,
                        'assessment_type': 'supervisor',
                        'assessor_id': env.user.id,
                        'state': default_state,
                    })
                    asm_count += 1
                else:
                    asm = existing_asm

                # Ensure line population
                existing_comp_ids = asm.line_ids.mapped('competency_id.id')
                line_create_vals = []
                for idx, m_line in enumerate(mapping.line_ids):
                    if m_line.competency_id.id not in existing_comp_ids:
                        req_int = int(m_line.required_proficiency or '2')
                        # Progressive rating calculation across cycles (2024: initial gap, 2025: improved, 2026: target)
                        if c_year == 2024:
                            cur_int = max(1, req_int - (idx % 2))
                        elif c_year == 2025:
                            cur_int = max(1, req_int - (idx % 3 == 0 and 1 or 0))
                        else:
                            cur_int = min(4, req_int + (idx % 4 == 0 and 1 or 0) - (idx % 5 == 0 and 1 or 0))
                        
                        line_create_vals.append({
                            'assessment_id': asm.id,
                            'competency_id': m_line.competency_id.id,
                            'required_level': str(req_int),
                            'current_level': str(cur_int),
                        })
                if line_create_vals:
                    AssessmentLine.create(line_create_vals)

        cr.commit()
        print(f"SUCCESS: Seeded 3 Assessment Cycles (2024, 2025, 2026), {asm_count} Historical & Current Assessments, {mapping_count} Role Mappings, {len(comp_records)} Competencies in ERP!")

if __name__ == '__main__':
    seed_bunna_competencies()
