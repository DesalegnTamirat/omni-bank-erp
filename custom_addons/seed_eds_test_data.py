# -*- coding: utf-8 -*-
import datetime
import random
import base64
import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry

def seed_eds_data():
    print("=== STARTING COMPREHENSIVE EDS SCENARIO TEST DATA SEEDING ===")
    registry = Registry('ERP')
    
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        
        # Fetch target employees
        employees = env['hr.employee'].search([('active', '=', True)], limit=200)
        if not employees:
            print("No active employees found!")
            return
        print(f"Loaded {len(employees)} employees for EDS seeding.")
        
        depts = env['hr.department'].search([])
        units = env['operating.unit'].search([])
        
        # Dummy binary for attachments
        dummy_base64 = base64.b64encode(b"Sample PDF Content for Test Data").decode('utf-8')
        
        # -------------------------------------------------------------
        # USE CASE 1 & 2: TNA CYCLES, ENTRIES, & CONSOLIDATIONS
        # -------------------------------------------------------------
        print("Seeding Use Case 1 & 2: TNA Cycles, Entries, and Consolidations...")
        
        cycle = env['eds.tna.cycle'].search([('year', '=', '2026')], limit=1)
        if not cycle:
            cycle = env['eds.tna.cycle'].create({
                'name': '2026 Annual Bank-Wide TNA Cycle',
                'year': '2026',
                'start_date': '2026-01-01',
                'end_date': '2026-03-31',
                'state': 'in_progress',
            })
            
        tna_entries = []
        delivery_modes = ['classroom', 'e_learning', 'blended']
        identification_sources = ['manual', 'competency_gap', 'pms']
        priorities = ['critical', 'high', 'medium', 'low']
        
        tna_titles = [
            "Core Banking Software System Training",
            "Credit Risk Assessment & Loan Structuring",
            "Anti-Money Laundering (AML) Compliance",
            "Customer Service Excellence & Communication",
            "Leadership & Branch Management Essentials",
            "Cybersecurity & Data Protection Awareness",
            "International Trade Finance & Forex Operations",
            "Agile Project Management for Bank Operations",
        ]
        
        for idx, emp in enumerate(employees[:40]):
            title = tna_titles[idx % len(tna_titles)]
            entry = env['eds.tna.entry'].create({
                'name': f"TNA-2026-{idx+1:04d}",
                'cycle_id': cycle.id,
                'employee_id': emp.id,
                'department_id': emp.department_id.id if emp.department_id else False,
                'work_unit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                'proposed_program': f"{title} for {emp.name}",
                'source': random.choice(identification_sources),
                'delivery_mode': random.choice(delivery_modes),
                'gap_severity': random.choice(priorities),
                'justification': f"Essential skill upgrade identified during annual appraisal for {emp.name}.",
                'state': 'approved',
            })
            tna_entries.append(entry)
            
        print(f"Seeded {len(tna_entries)} TNA Entries.")
        
        # Consolidations
        cons = env['eds.tna.consolidation'].search([('cycle_id', '=', cycle.id)], limit=1)
        if not cons:
            cons = env['eds.tna.consolidation'].create({
                'name': "2026 Corporate Bank-Wide TNA Consolidation",
                'cycle_id': cycle.id,
                'work_unit_id': units[0].id if units else False,
            })
            if tna_entries:
                for entry in tna_entries[:15]:
                    entry.consolidation_id = cons.id

        # -------------------------------------------------------------
        # USE CASE 3: COURSES & CURRICULUMS
        # -------------------------------------------------------------
        print("Seeding Use Case 3: Course Catalog & Curriculums...")
        
        course_data = [
            ("CB-101", "Core Banking Operations & System Workflow", 3),
            ("CR-201", "Credit Risk Appraisal & Loan Structuring", 4),
            ("AML-301", "Anti-Money Laundering (AML) & Fraud Detection", 2),
            ("CS-102", "Customer Service Excellence in Retail Banking", 2),
            ("LM-401", "Branch Manager Leadership & Team Management", 5),
            ("CY-501", "Cybersecurity & Data Privacy for Financial Institutions", 1),
            ("TF-202", "International Trade Finance & Forex Operations", 3),
            ("PM-302", "Agile Project Management for Bank Operations", 3),
        ]
        
        courses = []
        for code, name, days in course_data:
            c = env['eds.course'].search([('code', '=', code)], limit=1)
            if not c:
                c = env['eds.course'].create({
                    'code': code,
                    'name': name,
                    'delivery_method': 'internal',
                    'duration_days': days,
                    'status': 'active',
                })
            courses.append(c)
            
        print(f"Loaded/Created {len(courses)} Courses.")

        # -------------------------------------------------------------
        # USE CASE 4: VENUES, TRAINERS & ANNUAL PLANS
        # -------------------------------------------------------------
        print("Seeding Use Case 4: Venues, Trainers, and Annual Plans...")
        
        venue = env['eds.venue'].search([('name', '=', 'Head Office Main Auditorium')], limit=1)
        if not venue:
            venue = env['eds.venue'].create({
                'name': 'Head Office Main Auditorium',
                'location': 'Addis Ababa Head Office, 4th Floor',
                'capacity': 50,
                'active': True,
            })
            
        trainer = env['eds.trainer'].search([('name', '=', 'Ato Solomon Tekle')], limit=1)
        if not trainer:
            trainer = env['eds.trainer'].create({
                'name': 'Ato Solomon Tekle',
                'trainer_type': 'internal',
                'email': 'solomon.tekle@bunnabank.com',
                'employee_id': employees[0].id if employees else False,
            })
            
        provider = env['eds.external.provider'].search([('name', '=', 'Ethiopian Financial Studies Institute')], limit=1)
        if not provider:
            provider = env['eds.external.provider'].create({
                'name': 'Ethiopian Financial Studies Institute',
                'category': 'local',
            })
            
        annual_plan = env['eds.annual.plan'].search([('fiscal_year', '=', '2026')], limit=1)
        if not annual_plan:
            annual_plan = env['eds.annual.plan'].create({
                'name': '2026 Corporate Learning & Development Master Plan',
                'fiscal_year': '2026',
                'state': 'approved',
            })
            
        budget = env['eds.budget'].search([('fiscal_year', '=', '2026')], limit=1)
        if not budget:
            budget = env['eds.budget'].create({
                'name': "2026 L&D Budget",
                'fiscal_year': '2026',
                'category': 'internal',
                'allocated': 500000.0,
                'state': 'approved',
            })

        # -------------------------------------------------------------
        # USE CASE 4 & 5: SESSIONS, BATCHES, NOMINATIONS & ENROLLMENTS
        # -------------------------------------------------------------
        print("Seeding Use Case 4 & 5: Sessions, Nominations, and Enrollments...")
        
        sessions = []
        base_start = datetime.date(2026, 9, 1)
        
        for idx, course in enumerate(courses[:4]):
            sess = env['eds.session'].search([('course_id', '=', course.id)], limit=1)
            if not sess:
                start_dt = base_start + datetime.timedelta(days=idx*7)
                end_dt = start_dt + datetime.timedelta(days=4)
                sess = env['eds.session'].create({
                    'name': f"Session 2026-0{idx+1}: {course.name}",
                    'course_id': course.id,
                    'venue_id': venue.id,
                    'trainer_ids': [(6, 0, [trainer.id])],
                    'date_start': f"{start_dt.strftime('%Y-%m-%d')} 08:00:00",
                    'date_end': f"{end_dt.strftime('%Y-%m-%d')} 17:00:00",
                    'capacity': 30,
                    'status': 'scheduled',
                })
            sessions.append(sess)
            
        nominations = []
        enrollments = []
        
        for sess in sessions:
            for idx, emp in enumerate(employees[:20]):
                tna_ref = tna_entries[idx % len(tna_entries)].id if tna_entries else False
                nom = env['eds.nomination'].create({
                    'name': f"NOM-2026-{sess.id}-{idx+1:03d}",
                    'session_id': sess.id,
                    'employee_id': emp.id,
                    'nomination_type': 'tna_based' if tna_ref else 'ad_hoc',
                    'tna_entry_id': tna_ref if tna_ref else False,
                    'justification': "Approved training nomination for professional capacity building." if not tna_ref else False,
                    'state': 'approved',
                })
                nominations.append(nom)
                
                # Enrollment
                enr = env['eds.enrollment'].create({
                    'name': f"ENR-2026-{sess.id}-{idx+1:03d}",
                    'session_id': sess.id,
                    'employee_id': emp.id,
                    'nomination_id': nom.id,
                    'state': 'enrolled',
                })
                enrollments.append(enr)
                
        print(f"Seeded {len(nominations)} Nominations & {len(enrollments)} Enrollments.")

        # -------------------------------------------------------------
        # USE CASE 6: ATTENDANCE & DELIVERY CAPTURE
        # -------------------------------------------------------------
        print("Seeding Use Case 6: Attendance and Delivery Capture...")
        
        attendance_records = []
        for sess in sessions:
            for enr in enrollments:
                if enr.session_id.id == sess.id:
                    att = env['eds.session.attendance'].create({
                        'session_id': sess.id,
                        'employee_id': enr.employee_id.id,
                        'attendance_date': sess.date_start.date(),
                        'attended': True,
                        'hours_attended': 8.0,
                        'meets_min_attendance': True,
                    })
                    attendance_records.append(att)
                    
        print(f"Seeded {len(attendance_records)} Session Attendance logs.")

        # -------------------------------------------------------------
        # USE CASE 7 & 8: EVALUATIONS (LEVEL 1, LEVEL 2, LEVEL 3)
        # -------------------------------------------------------------
        print("Seeding Use Case 7 & 8: Level 1, Level 2, and Level 3 Evaluations...")
        
        for sess in sessions:
            for enr in enrollments:
                if enr.session_id.id == sess.id:
                    # Level 1 Reaction Survey
                    env['eds.evaluation.level1'].create({
                        'session_id': sess.id,
                        'course_id': sess.course_id.id,
                        'employee_id': enr.employee_id.id,
                        'overall_score': random.uniform(85.0, 98.0),
                        'state': 'submitted',
                    })
                    
                    # Level 2 Pre/Post Assessment
                    env['eds.assessment'].create({
                        'session_id': sess.id,
                        'employee_id': enr.employee_id.id,
                        'assessment_type': 'post',
                        'score': random.uniform(75.0, 95.0),
                        'threshold': 70.0,
                        'passed': True,
                        'assessment_date': sess.date_end.date(),
                    })
                    
                    # Level 3 Behavior Follow-Up (30-day post training observation)
                    env['eds.evaluation.level3'].create({
                        'session_id': sess.id,
                        'employee_id': enr.employee_id.id,
                        'manager_id': enr.employee_id.parent_id.id if enr.employee_id.parent_id else employees[0].id,
                        'due_date': '2026-10-01',
                        'status': 'completed',
                        'observation_notes': "Demonstrates clear application of course concepts in daily tasks.",
                    })

        # -------------------------------------------------------------
        # USE CASE 9: COMPLETION & CERTIFICATE ISSUANCE
        # -------------------------------------------------------------
        print("Seeding Use Case 9: Certificates...")
        
        for enr in enrollments[:30]:
            env['eds.certificate'].create({
                'session_id': enr.session_id.id,
                'employee_id': enr.employee_id.id,
                'issue_date': '2026-09-06',
                'state': 'issued',
            })
            
        # -------------------------------------------------------------
        # USE CASE 13: STAFF EDUCATION (ACADEMIC / DEGREE SUPPORT)
        # -------------------------------------------------------------
        print("Seeding Use Case 13: Staff Education & Sponsorships...")
        
        for idx, emp in enumerate(employees[:10]):
            env['eds.sponsorship'].create({
                'name': f"SPON-2026-{idx+1:03d}",
                'employee_id': emp.id,
                'program_name': "Master of Science in Banking & Finance",
                'sponsorship_type': 'education',
                'approved_amount': 45000.0,
                'bond_duration_months': 24,
                'state': 'approved',
            })
            
        # -------------------------------------------------------------
        # USE CASE 14: INTERNSHIP FACILITATION
        # -------------------------------------------------------------
        print("Seeding Use Case 14: Internship Facilitation Applications...")
        
        intern_names = [
            ("Abebe Kebede", "Addis Ababa University", "Banking & Finance"),
            ("Tigist Haile", "St. Mary University", "Accounting"),
            ("Yonas Berhanu", "Hawassa University", "Information Technology"),
            ("Marta Alemu", "Jimma University", "Business Administration"),
            ("Dawit Tadesse", "Unity University", "Economics"),
        ]
        
        for idx, (name, univ, field) in enumerate(intern_names):
            env['eds.internship.application'].create({
                'name': f"INT-2026-{idx+1:03d}",
                'applicant_name': name,
                'institution': univ,
                'field_of_study': field,
                'scanned_application': dummy_base64,
                'submitted_date': '2026-08-01',
                'status': 'accepted',
            })
            
        cr.commit()
        print("=== SUCCESSFULLY SEEDED COMPREHENSIVE EDS SCENARIO TEST DATA ACROSS ALL 14 USE CASES! ===")

if __name__ == '__main__':
    seed_eds_data()
