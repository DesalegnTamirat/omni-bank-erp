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
                    'status': 'active',
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

        # 2. Create / Ensure Approved Competency Framework
        framework = env['competency.framework'].search([('code', '=', 'BUNNA-FW-v1.0')], limit=1)
        if not framework:
            framework = env['competency.framework'].create({
                'name': "Bunna Bank Integrated Competency Framework",
                'code': 'BUNNA-FW-v1.0',
                'version': 'v1.0',
                'description': "Bunna Bank's official Integrated Competency Framework comprising Core, Leadership, and Technical competencies.",
                'state': 'draft',
            })
        
        fw_existing_comps = framework.line_ids.mapped('competency_id.id')
        fw_line_vals = []
        for cname, comp in comp_records.items():
            if comp.id not in fw_existing_comps:
                fw_line_vals.append({
                    'framework_id': framework.id,
                    'competency_id': comp.id,
                })
        if fw_line_vals:
            env['competency.framework.line'].create(fw_line_vals)

        if framework.state != 'approved':
            framework.with_context(force_write=True).write({
                'state': 'approved',
                'approved_by_id': env.user.id,
                'approval_date': odoo.fields.Datetime.now(),
            })

        print(f"Competency Framework Approved with {len(framework.line_ids)} competencies!")

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
        for jtitle, comp_dict in job_mappings.items():
            job = env['hr.job'].search([('name', '=ilike', jtitle)], limit=1)
            if not job:
                job = env['hr.job'].create({
                    'name': jtitle,
                    'description': f"Job Position for {jtitle}",
                })

            mapping = env['competency.role.mapping'].search([('job_position_id', '=', job.id)], limit=1)
            if not mapping:
                mapping = env['competency.role.mapping'].create({
                    'job_position_id': job.id,
                    'version': 'v1.0',
                    'state': 'draft',
                    'effective_date': odoo.fields.Date.context_today(env['competency.role.mapping']),
                    'change_description': 'Initial Bunna Bank Competency Framework role mapping import',
                })

            existing_comp_ids = mapping.line_ids.mapped('competency_id.id')
            line_create_vals = []
            for cid, req_p in comp_dict.items():
                if cid not in existing_comp_ids:
                    line_create_vals.append({
                        'mapping_id': mapping.id,
                        'competency_id': cid,
                        'required_proficiency': req_p,
                        'weight': 1.0,
                    })
            if line_create_vals:
                env['competency.role.mapping.line'].create(line_create_vals)

            if mapping.state != 'approved':
                mapping.with_context(force_write=True).write({
                    'state': 'approved',
                    'approved_by_id': env.user.id,
                    'approval_date': odoo.fields.Datetime.now(),
                })
            mapping_count += 1

        # 4. Seed Matrix Configuration (Job Grade & Job Position Guidelines)
        matrix_config = env['competency.matrix.config'].get_active_config()
        matrix_config._seed_matrix_guidelines()

        cr.commit()
        print(f"SUCCESS: Seeded {mapping_count} Role Mappings, {len(comp_records)} Competencies, and Matrix Settings in database ERP!")

if __name__ == '__main__':
    seed_bunna_competencies()
