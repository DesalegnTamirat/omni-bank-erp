#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migrate Competency Baseline Assessment - 26/27 from Comepetency migration.xlsx
into Odoo database (ERP_local_full & Bunna).
"""

import sys
import os
import re
import argparse
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
import psycopg2
from psycopg2.extras import execute_batch

def col2idx(c_ref):
    col_letters = ''.join([c for c in c_ref if c.isalpha()])
    idx = 0
    for char in col_letters:
        idx = idx * 26 + (ord(char) - ord('A') + 1)
    return idx - 1

def extract_text(val):
    if not val:
        return ''
    if isinstance(val, dict):
        return (val.get('en_US') or next(iter(val.values()), '')).strip()
    return str(val).strip()

def parse_excel(excel_path):
    print(f"[*] Parsing Excel: {excel_path} ...")
    rows_by_emp = defaultdict(list)
    emp_meta = {}
    total_baseline_rows = 0

    with zipfile.ZipFile(excel_path, 'r') as z:
        with z.open('xl/worksheets/sheet1.xml') as f:
            row_count = 0
            for event, elem in ET.iterparse(f, events=('end',)):
                if elem.tag.endswith('row'):
                    row_count += 1
                    if row_count > 1:
                        row_vals = {}
                        for c in elem.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                            val = None
                            v = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                            if v is not None and v.text: val = v.text
                            is_node = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is')
                            if is_node is not None:
                                t = is_node.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')
                                if t is not None: val = t.text
                            col_idx = col2idx(c.attrib.get('r', ''))
                            row_vals[col_idx] = val

                        campaign = row_vals.get(3)
                        if campaign == 'Competency Baseline Assessment - 26/27':
                            total_baseline_rows += 1
                            emp_name = (row_vals.get(4) or '').strip()
                            comp_name = (row_vals.get(11) or '').strip()
                            classification = (row_vals.get(10) or '').strip()
                            
                            req_lvl = row_vals.get(13) or '2'
                            self_lvl = row_vals.get(15) or '2'
                            self_comm = row_vals.get(16) or ''
                            coach_lvl = row_vals.get(20) or '2'
                            coach_comm = row_vals.get(21) or ''

                            if emp_name and comp_name:
                                rows_by_emp[emp_name].append({
                                    'comp': comp_name,
                                    'classification': classification,
                                    'req_lvl': str(int(float(req_lvl))),
                                    'self_lvl': str(int(float(self_lvl))),
                                    'self_comm': self_comm,
                                    'coach_lvl': str(int(float(coach_lvl))),
                                    'coach_comm': coach_comm,
                                })
                                if emp_name not in emp_meta:
                                    emp_meta[emp_name] = {
                                        'assessment_code': row_vals.get(1) or '',
                                        'department': row_vals.get(5) or '',
                                        'operating_unit': row_vals.get(6) or '',
                                        'job': row_vals.get(7) or '',
                                        'grade': row_vals.get(8) or '',
                                    }
                    elem.clear()

    print(f"[+] Parsed {total_baseline_rows} baseline rows across {len(rows_by_emp)} employees.")
    return rows_by_emp, emp_meta

def migrate_database(db_name, excel_path, host='db', port=5432, user='odoo', password='odoo'):
    print(f"\n========================================================")
    print(f"[*] STARTING MIGRATION ON DATABASE: {db_name}")
    print(f"========================================================")

    rows_by_emp, emp_meta = parse_excel(excel_path)

    conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=db_name)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 1. Fallback User
        cur.execute("SELECT id FROM res_users WHERE login = 'eds_officer@omnibank.et' LIMIT 1;")
        res = cur.fetchone()
        admin_user_id = res[0] if res else 2
        print(f"[+] Fallback Admin User ID: {admin_user_id}")

        # 2. Synchronize Missing Competencies
        print("[*] Synchronizing Competency Catalog ...")
        cur.execute("SELECT id, name, code, pillar FROM competency_competency;")
        db_comps = {extract_text(r[1]): r[0] for r in cur.fetchall()}
        
        cur.execute("SELECT id, name FROM competency_competency;")
        db_comps_norm = {extract_text(r[1]).lower().replace('&', 'and').replace(' ', '').replace('-', '').replace('/', ''): r[0] for r in cur.fetchall()}

        excel_comps = {}
        for emp_name, lines in rows_by_emp.items():
            for l in lines:
                c_name = l['comp']
                if c_name not in excel_comps:
                    excel_comps[c_name] = l['classification']

        cur.execute("SELECT count(*) FROM competency_competency WHERE code LIKE 'TECH-MIG-%';")
        mig_code_seq = cur.fetchone()[0] + 1

        missing_comps_inserted = 0
        for c_name, cls in excel_comps.items():
            if c_name in db_comps:
                continue
            norm = c_name.lower().replace('&', 'and').replace(' ', '').replace('-', '').replace('/', '')
            if norm in db_comps_norm:
                db_comps[c_name] = db_comps_norm[norm]
                continue

            code = f"TECH-MIG-{mig_code_seq:03d}"
            mig_code_seq += 1
            pillar = 'leadership' if 'leadership' in cls.lower() else ('core' if 'core' in cls.lower() else 'technical')
            
            cur.execute("""
                INSERT INTO competency_competency 
                (name, code, pillar, version, status, state, evaluation_method, active, create_uid, write_uid, create_date, write_date)
                VALUES (%s, %s, %s, 'v1.0', 'active', 'approved', 'star', true, %s, %s, NOW(), NOW())
                RETURNING id;
            """, (c_name, code, pillar, admin_user_id, admin_user_id))
            new_id = cur.fetchone()[0]
            db_comps[c_name] = new_id
            db_comps_norm[norm] = new_id
            missing_comps_inserted += 1

        print(f"[+] Competencies Synchronized: {missing_comps_inserted} new competencies added to catalog.")

        # 3. Employee Resolution
        print("[*] Resolving Employees & Hierarchy ...")
        cur.execute("""
            SELECT id, name, user_id, coach_id, department_id, default_operating_unit_id, job_position, job_grade, active, gender
            FROM hr_employee;
        """)
        emp_records = cur.fetchall()
        db_emps = {}
        for r in emp_records:
            name_clean = extract_text(r[1])
            if name_clean not in db_emps or (not db_emps[name_clean]['active'] and r[8]):
                db_emps[name_clean] = {
                    'id': r[0],
                    'name': name_clean,
                    'user_id': r[2],
                    'coach_id': r[3],
                    'department_id': r[4],
                    'ou_id': r[5],
                    'job_id': r[6],
                    'grade_id': r[7],
                    'active': r[8],
                    'gender': r[9] or None,
                }

        alias_map = {
            'Yohaness Mekonnen Telila': 'Yohannes Mekonnen Telila',
            'Zelalem Gedamu Mekonen': 'Zelalem Gedamu Mekonnen',
            'Biruk Yemataw Negash': 'Hunyalew Yemataw Negash',
        }

        # Load reference maps for grades and jobs
        cur.execute("SELECT id, grade_code, grade_name FROM employee_grade;")
        grades_map = {}
        for r in cur.fetchall():
            c_code = extract_text(r[1]).upper()
            c_name = extract_text(r[2]).upper()
            if c_code: grades_map[c_code] = r[0]
            if c_name: grades_map[c_name] = r[0]

        cur.execute("SELECT id, name FROM hr_job;")
        jobs_map = {}
        for r in cur.fetchall():
            j_n = extract_text(r[1]).lower()
            if j_n: jobs_map[j_n] = r[0]

        new_emps_created = 0
        for exc_name, meta in emp_meta.items():
            resolved_name = alias_map.get(exc_name, exc_name)
            if resolved_name in db_emps:
                continue

            cur.execute("""
                INSERT INTO resource_resource (name, resource_type, active, company_id, tz, time_efficiency, create_uid, write_uid, create_date, write_date)
                VALUES (%s, 'user', true, 1, 'Europe/Brussels', 100.0, %s, %s, NOW(), NOW()) RETURNING id;
            """, (exc_name, admin_user_id, admin_user_id))
            res_id = cur.fetchone()[0]

            dept_id = None
            if meta['department']:
                cur.execute("SELECT id FROM hr_department WHERE name::text ILIKE %s LIMIT 1;", (f"%{meta['department'].strip()}%",))
                d_res = cur.fetchone()
                if d_res: dept_id = d_res[0]

            ou_id = None
            if meta['operating_unit']:
                cur.execute("SELECT id FROM operating_unit WHERE name::text ILIKE %s LIMIT 1;", (f"%{meta['operating_unit'].strip()}%",))
                ou_res = cur.fetchone()
                if ou_res: ou_id = ou_res[0]

            j_grade_id = grades_map.get((meta['grade'] or '').strip().upper())
            j_pos_id = jobs_map.get((meta['job'] or '').strip().lower())

            cur.execute("""
                INSERT INTO hr_employee 
                (name, resource_id, active, company_id, user_id, department_id, default_operating_unit_id, job_position, job_grade, job_name, create_uid, write_uid, create_date, write_date)
                VALUES (%s, %s, true, 1, NULL, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                RETURNING id;
            """, (exc_name, res_id, dept_id, ou_id, j_pos_id, j_grade_id, meta['job'], admin_user_id, admin_user_id))
            new_emp_id = cur.fetchone()[0]

            db_emps[exc_name] = {
                'id': new_emp_id,
                'name': exc_name,
                'user_id': admin_user_id,
                'coach_id': None,
                'department_id': dept_id,
                'ou_id': ou_id,
                'job_id': j_pos_id,
                'grade_id': j_grade_id,
                'active': True,
                'gender': None,
            }
            new_emps_created += 1

        print(f"[+] Employees Resolved: {new_emps_created} missing employee profiles created.")

        cur.execute("SELECT id, user_id, coach_id FROM hr_employee;")
        emp_coaches = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

        # 4. Create Assessment Cycle
        print("[*] Creating / Verifying Competency Assessment Cycle ...")
        cycle_name = 'Competency Baseline Assessment - 26/27'
        cur.execute("SELECT id FROM competency_assessment_cycle WHERE name = %s;", (cycle_name,))
        c_res = cur.fetchone()
        if c_res:
            cycle_id = c_res[0]
            print(f"[+] Assessment Cycle '{cycle_name}' already exists (ID: {cycle_id}). Cleaning up old lines/assessments...")
            cur.execute("DELETE FROM competency_assessment WHERE cycle_id = %s;", (cycle_id,))
        else:
            cur.execute("""
                INSERT INTO competency_assessment_cycle
                (name, code, state, period_start, period_end, assessment_deadline, active, notes, is_open_or_latest, create_uid, write_uid, create_date, write_date)
                VALUES (%s, 'CYCLE-26-27-BASE', 'closed', '2026-07-01', '2026-10-31', '2026-10-31', true,
                        'Historical baseline cycle migrated from production (Self + Coach). Peer & Subordinate assumed unassigned.',
                        false, %s, %s, NOW(), NOW())
                RETURNING id;
            """, (cycle_name, admin_user_id, admin_user_id))
            cycle_id = cur.fetchone()[0]
            print(f"[+] Assessment Cycle created with ID: {cycle_id}")

        # 5. Bulk Create Assessment Headers (Self + Coach)
        print("[*] Generating Assessment Headers for Self and Coach ...")
        self_headers = []
        coach_headers = []

        cur.execute("SELECT MAX(id) FROM competency_assessment;")
        max_asm_id = cur.fetchone()[0] or 1000

        for exc_name in rows_by_emp.keys():
            resolved_name = alias_map.get(exc_name, exc_name)
            emp = db_emps.get(resolved_name)
            if not emp:
                continue

            emp_id = emp['id']
            emp_user = emp['user_id'] or admin_user_id
            
            c_info = emp_coaches.get(emp_id, (None, None))
            coach_id = emp['coach_id'] or c_info[1]
            coach_user = None
            if coach_id and coach_id in emp_coaches:
                coach_user = emp_coaches[coach_id][0]
            if not coach_user:
                coach_user = admin_user_id

            max_asm_id += 1
            self_asm_id = max_asm_id
            max_asm_id += 1
            coach_asm_id = max_asm_id

            meta = emp_meta.get(exc_name, {})
            ref_self = f"COMP/26-27/{self_asm_id}"
            ref_coach = f"COMP/26-27/{coach_asm_id}"

            self_headers.append((
                self_asm_id, cycle_id, emp_id, emp_user, 'self', 'approved', True, False,
                emp['department_id'], emp['ou_id'], emp['job_id'], emp['grade_id'], ref_self,
                admin_user_id, admin_user_id
            ))

            coach_headers.append((
                coach_asm_id, cycle_id, emp_id, coach_user, coach_id, 'team', 'approved', True, True, self_asm_id,
                emp['department_id'], emp['ou_id'], emp['job_id'], emp['grade_id'], ref_coach,
                admin_user_id, admin_user_id
            ))

        execute_batch(cur, """
            INSERT INTO competency_assessment
            (id, cycle_id, employee_id, assessor_id, assessment_type, state, active, is_rater_assessment,
             department_id, operating_unit_id, job_id, grade_id, name, create_uid, write_uid, create_date, write_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW());
        """, self_headers, page_size=1000)

        execute_batch(cur, """
            INSERT INTO competency_assessment
            (id, cycle_id, employee_id, assessor_id, assessor_employee_id, assessment_type, state, active, is_rater_assessment, parent_assessment_id,
             department_id, operating_unit_id, job_id, grade_id, name, create_uid, write_uid, create_date, write_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW());
        """, coach_headers, page_size=1000)

        print(f"[+] Created {len(self_headers)} Self Assessment headers.")
        print(f"[+] Created {len(coach_headers)} Coach Assessment headers.")

        self_asm_map = {h[2]: h[0] for h in self_headers}
        coach_asm_map = {h[2]: h[0] for h in coach_headers}

        # 6. Bulk Create Assessment Lines (Self & Coach)
        print("[*] Preparing Assessment Lines for batch insertion ...")
        self_lines = []
        coach_lines = []

        cur.execute("SELECT id, pillar, functional_domain FROM competency_competency;")
        comp_details = {r[0]: (extract_text(r[1]), extract_text(r[2])) for r in cur.fetchall()}

        for exc_name, lines in rows_by_emp.items():
            resolved_name = alias_map.get(exc_name, exc_name)
            emp = db_emps.get(resolved_name)
            if not emp:
                continue

            emp_id = emp['id']
            self_asm_id = self_asm_map.get(emp_id)
            coach_asm_id = coach_asm_map.get(emp_id)
            if not self_asm_id or not coach_asm_id:
                continue

            for l in lines:
                c_name = l['comp']
                comp_id = db_comps.get(c_name)
                if not comp_id:
                    norm = c_name.lower().replace('&', 'and').replace(' ', '').replace('-', '').replace('/', '')
                    comp_id = db_comps_norm.get(norm)
                if not comp_id:
                    continue

                cd = comp_details.get(comp_id, ('technical', ''))
                pillar = cd[0]
                domain = cd[1]

                s_score = int(re.sub(r'[^0-9]', '', l['self_lvl']) or 0)
                c_score = int(re.sub(r'[^0-9]', '', l['coach_lvl']) or 0)
                req_score = int(re.sub(r'[^0-9]', '', l['req_lvl']) or 0)

                self_rating = float(s_score)
                supervisor_avg = float(c_score)
                peer_avg = 0.0
                subordinate_avg = 0.0
                team_avg = 0.0
                weighted_current_level = round(((s_score * 2.0) + (c_score * 3.0)) / 5.0, 2)
                self_gap = round(float(s_score - req_score), 2)
                supervisor_gap = round(float(c_score - req_score), 2)
                peer_gap = 0.0
                subordinate_gap = 0.0

                # Self Line specifics
                s_gap = s_score - req_score
                s_tna = 'below' if s_gap < 0 else ('meets' if s_gap == 0 else 'exceeds')
                s_prio = 'critical' if s_gap <= -3 else ('high' if s_gap == -2 else ('medium' if s_gap == -1 else 'low'))

                self_lines.append((
                    self_asm_id, cycle_id, emp_id, comp_id,
                    l['self_lvl'], l['req_lvl'], s_score, req_score,
                    s_gap, s_tna, s_tna, s_prio, l['self_comm'],
                    True, pillar, domain, 'approved', True,
                    emp['department_id'], emp['ou_id'], emp['job_id'], emp['grade_id'], emp.get('gender'),
                    self_rating, supervisor_avg, peer_avg, subordinate_avg, team_avg,
                    weighted_current_level, self_gap, supervisor_gap, peer_gap, subordinate_gap,
                    admin_user_id, admin_user_id
                ))

                # Coach Line specifics
                c_gap = c_score - req_score
                c_tna = 'below' if c_gap < 0 else ('meets' if c_gap == 0 else 'exceeds')
                c_prio = 'critical' if c_gap <= -3 else ('high' if c_gap == -2 else ('medium' if c_gap == -1 else 'low'))

                coach_lines.append((
                    coach_asm_id, cycle_id, emp_id, comp_id,
                    l['coach_lvl'], l['req_lvl'], c_score, req_score,
                    c_gap, c_tna, c_tna, c_prio, l['coach_comm'],
                    False, pillar, domain, 'approved', True,
                    emp['department_id'], emp['ou_id'], emp['job_id'], emp['grade_id'], emp.get('gender'),
                    self_rating, supervisor_avg, peer_avg, subordinate_avg, team_avg,
                    weighted_current_level, self_gap, supervisor_gap, peer_gap, subordinate_gap,
                    admin_user_id, admin_user_id
                ))

        insert_sql = """
            INSERT INTO competency_assessment_line
            (assessment_id, cycle_id, employee_id, competency_id,
             current_level, required_level, current_level_num, required_level_num,
             gap, tna_measure, achievement_status, gap_priority, comments,
             is_primary_reporting_line, pillar, functional_domain, state, active,
             department_id, operating_unit_id, job_id, grade_id, gender,
             self_rating, supervisor_avg, peer_avg, subordinate_avg, team_avg,
             weighted_current_level, self_gap, supervisor_gap, peer_gap, subordinate_gap,
             create_uid, write_uid, create_date, write_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW());
        """

        print(f"[*] Bulk inserting {len(self_lines)} Self lines ...")
        execute_batch(cur, insert_sql, self_lines, page_size=2000)

        print(f"[*] Bulk inserting {len(coach_lines)} Coach lines ...")
        execute_batch(cur, insert_sql, coach_lines, page_size=2000)

        print(f"[+] All {len(self_lines) + len(coach_lines)} assessment lines inserted successfully with 360 values and TNA measures.")

        # 7. Post-Insert Bulk SQL Recompute
        print("[*] Recomputing Header Averages and Cycle Counters ...")

        # 7.1 Header average gaps
        cur.execute("""
            UPDATE competency_assessment a
            SET average_gap = sub.avg_gap
            FROM (
                SELECT assessment_id, ROUND(AVG(gap), 2) as avg_gap
                FROM competency_assessment_line
                WHERE cycle_id = %s
                GROUP BY assessment_id
            ) sub
            WHERE a.id = sub.assessment_id;
        """, (cycle_id,))

        # 7.5 Update Cycle counters
        cur.execute("""
            UPDATE competency_assessment_cycle
            SET eligible_rater_count = %s,
                selected_rater_count = %s
            WHERE id = %s;
        """, (len(self_headers) + len(coach_headers), len(self_headers) + len(coach_headers), cycle_id))

        # 8. Reset Postgres Sequences to max(id)
        cur.execute("SELECT setval('competency_assessment_id_seq', (SELECT MAX(id) FROM competency_assessment));")
        cur.execute("SELECT setval('competency_assessment_line_id_seq', (SELECT MAX(id) FROM competency_assessment_line));")
        cur.execute("SELECT setval('competency_competency_id_seq', (SELECT MAX(id) FROM competency_competency));")
        cur.execute("SELECT setval('hr_employee_id_seq', (SELECT MAX(id) FROM hr_employee));")
        cur.execute("SELECT setval('resource_resource_id_seq', (SELECT MAX(id) FROM resource_resource));")
        cur.execute("SELECT setval('competency_assessment_cycle_id_seq', (SELECT MAX(id) FROM competency_assessment_cycle));")

        conn.commit()
        print(f"\n[+++] SUCCESS: Database '{db_name}' fully migrated and committed!")

    except Exception as e:
        conn.rollback()
        print(f"\n[---] ERROR during migration on '{db_name}': {e}")
        raise e
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Migrate Baseline Competency Assessment Data.")
    parser.add_argument('--db', required=True, help="Target database name (ERP_local_full or Bunna)")
    parser.add_argument('--excel', default='/mnt/extra-addons/competency_management/migration_source.xlsx', help="Path to migration excel")
    parser.add_argument('--host', default='db', help="PostgreSQL host")
    parser.add_argument('--port', default=5432, type=int, help="PostgreSQL port")
    parser.add_argument('--user', default='odoo', help="PostgreSQL user")
    parser.add_argument('--password', default='odoo', help="PostgreSQL password")

    args = parser.parse_args()
    migrate_database(args.db, args.excel, host=args.host, port=args.port, user=args.user, password=args.password)
