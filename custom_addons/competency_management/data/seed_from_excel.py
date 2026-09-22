#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seed Competency Dictionary and Role-Competency Mappings from Excel files.
Supports both:
1. Business Team Flat Templates (Competency_Dictionary_Template.xlsx & Role_Competency_Mapping_Template.xlsx)
2. Native Odoo Import Multi-level Templates

Usage:
    docker exec odoo19-app python3 /mnt/extra-addons/competency_management/data/seed_from_excel.py --all
    docker exec odoo19-app python3 /mnt/extra-addons/competency_management/data/seed_from_excel.py --all --dry-run
"""

import sys
import os
import re
import argparse
from openpyxl import load_workbook

import odoo
from odoo.modules.registry import Registry
from odoo import api, SUPERUSER_ID


def get_cell_val(cell):
    if cell is None or cell.value is None:
        return ""
    val = str(cell.value).strip()
    return val


def parse_level_digit(val_str):
    """Extracts '1', '2', '3', or '4' from strings like '3 - Advanced', 'Level 3', '3'."""
    if not val_str:
        return '2'
    m = re.search(r'([1-4])', val_str)
    if m:
        return m.group(1)
    return '2'


def seed_competencies(env, excel_path):
    print(f"\n=======================================================")
    print(f"[*] Seeding Competency Dictionary from: {excel_path}")
    print(f"=======================================================")
    if not os.path.exists(excel_path):
        print(f"[-] Error: File not found: {excel_path}")
        return

    wb = load_workbook(excel_path, data_only=True)
    
    # Identify sheet
    sheet_name = None
    for name in ["Competencies", "Competency Dictionary (Import)", "Quick Flat Entry (Alternative)"]:
        if name in wb.sheetnames:
            sheet_name = name
            break
    if not sheet_name:
        sheet_name = wb.sheetnames[0]

    ws = wb[sheet_name]
    headers = [get_cell_val(c).lower() for c in ws[1]]
    is_flat_business = ("competency code" in headers or "level 1" in str(headers)) and "proficiency_level_ids/level" not in headers

    print(f"[*] Sheet selected: '{sheet_name}' (Mode: {'Business Team 1-Row Format' if is_flat_business else 'Hierarchical Odoo Import Format'})")

    CompObj = env['competency.competency']
    LevelObj = env['competency.proficiency.level']
    RatingModelObj = env['competency.rating.model']

    scale_4 = RatingModelObj.search([('code', '=', '4SCALE')], limit=1)
    if not scale_4:
        scale_4 = RatingModelObj.search([], limit=1)

    created_comps = 0
    updated_comps = 0

    if is_flat_business:
        # Find column indices
        col_code = 2
        col_name = 3
        col_pillar = 4
        col_domain = 5
        col_def = 6
        col_lvl1 = 7
        col_lvl2 = 8
        col_lvl3 = 9
        col_lvl4 = 10

        for col_i, h in enumerate(headers, start=1):
            if "code" in h: col_code = col_i
            elif "name" in h: col_name = col_i
            elif "pillar" in h: col_pillar = col_i
            elif "domain" in h or "dept" in h: col_domain = col_i
            elif "definition" in h or "description" in h: col_def = col_i
            elif "level 1" in h: col_lvl1 = col_i
            elif "level 2" in h: col_lvl2 = col_i
            elif "level 3" in h: col_lvl3 = col_i
            elif "level 4" in h: col_lvl4 = col_i

        for row_idx in range(2, ws.max_row + 1):
            code = get_cell_val(ws.cell(row=row_idx, column=col_code))
            name = get_cell_val(ws.cell(row=row_idx, column=col_name))
            if not code or not name:
                continue

            pillar_raw = get_cell_val(ws.cell(row=row_idx, column=col_pillar)).lower()
            pillar = 'core'
            if 'lead' in pillar_raw: pillar = 'leadership'
            elif 'tech' in pillar_raw: pillar = 'technical'

            domain = get_cell_val(ws.cell(row=row_idx, column=col_domain))
            definition = get_cell_val(ws.cell(row=row_idx, column=col_def))

            lvl_indicators = {
                '1': get_cell_val(ws.cell(row=row_idx, column=col_lvl1)) or f"Level 1 basic indicator for {name}.",
                '2': get_cell_val(ws.cell(row=row_idx, column=col_lvl2)) or f"Level 2 intermediate indicator for {name}.",
                '3': get_cell_val(ws.cell(row=row_idx, column=col_lvl3)) or f"Level 3 advanced indicator for {name}.",
                '4': get_cell_val(ws.cell(row=row_idx, column=col_lvl4)) or f"Level 4 expert indicator for {name}.",
            }

            comp = CompObj.with_context(active_test=False).search([('code', '=ilike', code)], limit=1)
            comp_vals = {
                'name': name,
                'code': code,
                'pillar': pillar,
                'functional_domain': domain,
                'definition': definition,
                'rating_model_id': scale_4.id if scale_4 else False,
                'state': 'approved',
                'active': True,
            }

            if not comp:
                level_lines = []
                level_names = {'1': 'Level 1 - Basic', '2': 'Level 2 - Intermediate', '3': 'Level 3 - Advanced', '4': 'Level 4 - Expert'}
                for lvl_k in ['1', '2', '3', '4']:
                    level_lines.append((0, 0, {
                        'level': lvl_k,
                        'name': level_names[lvl_k],
                        'behavioral_indicators': lvl_indicators[lvl_k],
                        'definition': f"{level_names[lvl_k]} definition.",
                    }))
                comp_vals['proficiency_level_ids'] = level_lines
                comp = CompObj.create(comp_vals)
                created_comps += 1
                print(f"  [+] Created: [{code}] {name} ({pillar})")
            else:
                comp.write(comp_vals)
                for lvl_k in ['1', '2', '3', '4']:
                    lvl_rec = LevelObj.search([('competency_id', '=', comp.id), ('level', '=', lvl_k)], limit=1)
                    if lvl_rec:
                        lvl_rec.write({'behavioral_indicators': lvl_indicators[lvl_k]})
                    else:
                        LevelObj.create({
                            'competency_id': comp.id,
                            'level': lvl_k,
                            'name': f"Level {lvl_k}",
                            'behavioral_indicators': lvl_indicators[lvl_k],
                        })
                updated_comps += 1
                print(f"  [*] Updated: [{code}] {name} ({pillar})")

    else:
        # Hierarchical format
        current_comp_vals = {}
        pending_levels = []

        def save_pending_comp(c_vals, levels):
            nonlocal created_comps, updated_comps
            if not c_vals.get('code'):
                return
            code = c_vals['code']
            comp = CompObj.with_context(active_test=False).search([('code', '=ilike', code)], limit=1)
            
            if not comp:
                level_lines = []
                for lvl in levels:
                    level_lines.append((0, 0, {
                        'level': str(lvl['level']),
                        'name': lvl.get('name') or f"Level {lvl['level']}",
                        'behavioral_indicators': lvl.get('indicators') or f"Indicators for Level {lvl['level']}",
                        'definition': f"Level {lvl['level']} definition",
                    }))
                c_vals['proficiency_level_ids'] = level_lines
                comp = CompObj.create(c_vals)
                created_comps += 1
                print(f"  [+] Created: [{code}] {c_vals['name']} ({c_vals['pillar']}) with {len(levels)} levels")
            else:
                comp.write(c_vals)
                for lvl in levels:
                    lvl_rec = LevelObj.search([('competency_id', '=', comp.id), ('level', '=', str(lvl['level']))], limit=1)
                    if lvl_rec:
                        lvl_rec.write({
                            'name': lvl.get('name') or lvl_rec.name,
                            'behavioral_indicators': lvl.get('indicators') or lvl_rec.behavioral_indicators,
                        })
                    else:
                        LevelObj.create({
                            'competency_id': comp.id,
                            'level': str(lvl['level']),
                            'name': lvl.get('name') or f"Level {lvl['level']}",
                            'behavioral_indicators': lvl.get('indicators') or f"Indicators for Level {lvl['level']}",
                        })
                updated_comps += 1
                print(f"  [*] Updated: [{code}] {c_vals['name']} ({c_vals['pillar']})")

        for row_idx in range(2, ws.max_row + 1):
            code_cell = get_cell_val(ws.cell(row=row_idx, column=2))
            lvl_rank = get_cell_val(ws.cell(row=row_idx, column=8))
            lvl_name = get_cell_val(ws.cell(row=row_idx, column=9))
            lvl_ind = get_cell_val(ws.cell(row=row_idx, column=10))

            if code_cell:
                if current_comp_vals:
                    save_pending_comp(current_comp_vals, pending_levels)
                
                name = get_cell_val(ws.cell(row=row_idx, column=3))
                pillar = get_cell_val(ws.cell(row=row_idx, column=4)).lower()
                if pillar not in ('core', 'leadership', 'technical'):
                    pillar = 'core'
                domain = get_cell_val(ws.cell(row=row_idx, column=5))
                definition = get_cell_val(ws.cell(row=row_idx, column=6))
                state = get_cell_val(ws.cell(row=row_idx, column=7)).lower() or 'approved'

                current_comp_vals = {
                    'name': name,
                    'code': code_cell,
                    'pillar': pillar,
                    'functional_domain': domain,
                    'definition': definition,
                    'rating_model_id': scale_4.id if scale_4 else False,
                    'state': state,
                    'active': True,
                }
                pending_levels = []
                if lvl_rank:
                    pending_levels.append({'level': lvl_rank, 'name': lvl_name, 'indicators': lvl_ind})
            else:
                if lvl_rank:
                    pending_levels.append({'level': lvl_rank, 'name': lvl_name, 'indicators': lvl_ind})

        if current_comp_vals:
            save_pending_comp(current_comp_vals, pending_levels)

    print(f"\n[✔] Competency Dictionary Seeding Summary:")
    print(f"    - Created Competencies: {created_comps}")
    print(f"    - Updated Competencies: {updated_comps}")


def seed_role_mappings(env, excel_path):
    print(f"\n=======================================================")
    print(f"[*] Seeding Role-Competency Mappings from: {excel_path}")
    print(f"=======================================================")
    if not os.path.exists(excel_path):
        print(f"[-] Error: File not found: {excel_path}")
        return

    wb = load_workbook(excel_path, data_only=True)
    
    sheet_name = None
    for name in ["Position Mapping", "Role Mapping (Import)"]:
        if name in wb.sheetnames:
            sheet_name = name
            break
    if not sheet_name:
        sheet_name = wb.sheetnames[0]

    print(f"[*] Sheet selected: '{sheet_name}'")
    ws = wb[sheet_name]
    headers = [get_cell_val(c).lower() for c in ws[1]]

    MapObj = env['competency.role.mapping']
    MapLineObj = env['competency.role.mapping.line']
    JobObj = env['hr.job']
    CompObj = env['competency.competency']

    all_jobs = JobObj.search([])
    job_by_name = {j.name.lower().strip(): j for j in all_jobs if j.name}

    created_maps = 0
    updated_maps = 0
    created_lines = 0

    # Determine column mapping based on headers
    col_job = 2
    col_code = 3
    col_name = 4
    col_req = 5
    col_weight = 6

    for col_i, h in enumerate(headers, start=1):
        if "job" in h or "position" in h: col_job = col_i
        elif "code" in h: col_code = col_i
        elif "competency" in h and "code" not in h: col_name = col_i
        elif "required" in h or "level" in h: col_req = col_i
        elif "weight" in h: col_weight = col_i

    # Group rows by Job Position Name
    mappings_data = {}

    for row_idx in range(2, ws.max_row + 1):
        job_val = get_cell_val(ws.cell(row=row_idx, column=col_job))
        c_code = get_cell_val(ws.cell(row=row_idx, column=col_code))
        c_name = get_cell_val(ws.cell(row=row_idx, column=col_name))
        req_lvl_raw = get_cell_val(ws.cell(row=row_idx, column=col_req))
        weight_raw = get_cell_val(ws.cell(row=row_idx, column=col_weight))

        if not job_val:
            # Check if this row is a child line belonging to previous job
            # Find the most recent job
            if not mappings_data:
                continue
            last_job = list(mappings_data.keys())[-1]
            job_val = last_job
        else:
            if job_val not in mappings_data:
                mappings_data[job_val] = []

        if c_code or c_name:
            req_lvl = parse_level_digit(req_lvl_raw)
            try:
                wt = float(weight_raw) if weight_raw else 1.0
            except:
                wt = 1.0
            mappings_data[job_val].append({
                'code': c_code,
                'name': c_name,
                'req_level': req_lvl,
                'weight': wt,
            })

    # Now process each Job Position
    for job_name, lines in mappings_data.items():
        job = job_by_name.get(job_name.lower().strip())
        if not job:
            print(f"  [!] Warning: Job Position '{job_name}' not found in Odoo! Skipping.")
            continue

        mapping = MapObj.search([('job_position_id', '=', job.id), ('state', 'in', ['approved', 'under_approval', 'draft'])], limit=1)
        if not mapping:
            mapping = MapObj.create({
                'job_position_id': job.id,
                'version': 'v1.0',
                'state': 'approved',
            })
            created_maps += 1
            print(f"  [+] Created Role Mapping: {job.name} (v1.0)")
        else:
            updated_maps += 1
            print(f"  [*] Updating Existing Role Mapping: {job.name} ({mapping.version})")

        for l in lines:
            c_code = l.get('code', '').strip().lower()
            c_name = l.get('name', '').strip().lower()
            comp = None
            if c_code:
                comp = CompObj.with_context(active_test=False).search([('code', '=ilike', c_code)], limit=1)
            if not comp and c_name:
                comp = CompObj.with_context(active_test=False).search([('name', '=ilike', c_name)], limit=1)

            if not comp:
                print(f"    [!] Competency not found: code='{l.get('code')}', name='{l.get('name')}'. Skipping line.")
                continue

            req_lvl = l['req_level']
            wt = l['weight']

            existing_line = MapLineObj.search([('mapping_id', '=', mapping.id), ('competency_id', '=', comp.id)], limit=1)
            if not existing_line:
                MapLineObj.create({
                    'mapping_id': mapping.id,
                    'competency_id': comp.id,
                    'required_proficiency': req_lvl,
                    'weight': wt,
                    'override_default': True,
                })
                created_lines += 1
                print(f"    + Mapped [{comp.code}] {comp.name} -> Level {req_lvl} (weight: {wt})")
            else:
                existing_line.write({
                    'required_proficiency': req_lvl,
                    'weight': wt,
                    'override_default': True,
                })
                print(f"    * Updated [{comp.code}] {comp.name} -> Level {req_lvl} (weight: {wt})")

    print(f"\n[✔] Role-Competency Mapping Seeding Summary:")
    print(f"    - Created Mappings: {created_maps}")
    print(f"    - Updated Mappings: {updated_maps}")
    print(f"    - Competency Lines Added/Updated: {created_lines}")


def main():
    parser = argparse.ArgumentParser(description="Seed Competency and Role Mappings from Excel into Odoo.")
    parser.add_argument("--db", default="ERP_TEST3", help="Target Odoo database (default: ERP_TEST3)")
    parser.add_argument("--comp", help="Path to Competency Dictionary Excel file")
    parser.add_argument("--map", help="Path to Role Mapping Excel file")
    parser.add_argument("--all", action="store_true", help="Seed both using default business template files")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run without committing transactions")
    args = parser.parse_args()

    default_template_dir = "/mnt/extra-addons/competency_management/data/templates"
    comp_file = args.comp
    map_file = args.map

    if args.all:
        comp_candidates = [
            os.path.join(default_template_dir, "Competency_Dictionary_Template.xlsx"),
            os.path.join(default_template_dir, "competency_dictionary_template.xlsx"),
        ]
        map_candidates = [
            os.path.join(default_template_dir, "Role_Competency_Mapping_Template.xlsx"),
            os.path.join(default_template_dir, "role_competency_mapping_template.xlsx"),
        ]
        for c in comp_candidates:
            if os.path.exists(c):
                comp_file = c
                break
        for m in map_candidates:
            if os.path.exists(m):
                map_file = m
                break

    if not comp_file and not map_file:
        print("Usage error: Please specify --all, or at least one of --comp or --map.")
        sys.exit(1)

    print(f"[*] Initializing Odoo Registry for database '{args.db}'...")
    reg = Registry(args.db)
    with reg.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        try:
            if comp_file:
                seed_competencies(env, comp_file)
            if map_file:
                seed_role_mappings(env, map_file)

            if args.dry_run:
                print("\n[!] DRY RUN COMPLETED: Rolling back all database changes (Nothing was saved).")
                cr.rollback()
            else:
                cr.commit()
                print("\n[✔] Database changes successfully committed to database!")
        except Exception as e:
            cr.rollback()
            print(f"\n[-] Exception occurred during seeding: {e}")
            raise

if __name__ == "__main__":
    main()
