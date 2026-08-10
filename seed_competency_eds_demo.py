# -*- coding: utf-8 -*-
"""
Omni-Bank ERP — Competency Management & EDS Demo Data Seed Script
==================================================================
Usage inside Odoo Docker container:
    docker exec -i odoo19-app odoo shell -d ERP --no-http < omni-bank-erp/seed_competency_eds_demo.py

Populates:
  1. Users with passwords ('123456') for all RBAC roles
  2. Employee records & reporting hierarchy (parent_id / Line Manager)
  3. Operating Units & Job Positions
  4. Competency Framework, Competencies, Levels, Role Mappings
  5. Competency Assessment Cycle, Self & Supervisor Assessments, Gap Analysis, IDPs
  6. EDS Curriculum, Courses, TNA, Annual L&D Plan & Calendar
  7. Training Providers, Venues, Trainers
  8. Training Sessions, Nominations (Approved & Waitlisted capacity control)
  9. Attendance logs (>80% threshold rules)
 10. Kirkpatrick Level 1-4 Evaluations
 11. Certificates with verification hashes
 12. Budgets, Staff Education Sponsorships, Internships, Unscheduled Requests
"""

import logging
from datetime import date, datetime, timedelta

_logger = logging.getLogger('seed_competency_eds_demo')

TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)
NEXT_WEEK = TODAY + timedelta(days=7)
END_OF_MONTH = TODAY + timedelta(days=30)


def _find(model, domain):
    return env[model].search(domain, limit=1)


def _log(msg):
    print('[SEED-COMPETENCY-EDS] %s' % msg)


_log('Starting Competency & EDS Demo Data Seeding...')

# Monkey-patch hr.version.write during seeding to prevent hr_contract.py recursion loop
try:
    HrVersionClass = type(env['hr.version'])
    _orig_hr_version_write = HrVersionClass.write
    def _safe_hr_version_write(self, vals):
        if isinstance(vals, dict) and 'resource_calendar_id' in vals:
            vals = dict(vals)
            vals.pop('resource_calendar_id', None)
        return _orig_hr_version_write(self, vals)
    HrVersionClass.write = _safe_hr_version_write
    _log('Applied safe monkey-patch to hr.version.write for seed execution.')
except Exception as e:
    _log('Could not patch hr.version: %s' % e)

# ─────────────────────────────────────────────────────────────────────────────
# 1. OPERATING UNITS & JOB POSITIONS
# ─────────────────────────────────────────────────────────────────────────────
_log('Creating / Verifying Operating Units & Jobs...')

ou_it = _find('operating.unit', [('name', '=', 'DEMO IT & Digital Banking Directorate')])
if not ou_it:
    ou_it = _find('operating.unit', [])
if not ou_it:
    ou_it = env['operating.unit'].create({
        'name': 'DEMO IT & Digital Banking Directorate',
        'company_id': env.company.id,
        'sol_id': 9001,
        'work_unit_type': 'head_office',
    })

ou_hr = _find('operating.unit', [('name', '=', 'DEMO People Performance Directorate')])
if not ou_hr:
    ou_hr = env['operating.unit'].create({
        'name': 'DEMO People Performance Directorate',
        'company_id': env.company.id,
        'sol_id': 9002,
        'work_unit_type': 'head_office',
    })

job_dev = _find('hr.job', [('name', '=', 'DEMO Senior Software Engineer')])
if not job_dev:
    job_dev = env['hr.job'].create({
        'name': 'DEMO Senior Software Engineer',
        'company_id': env.company.id,
    })

job_mgr = _find('hr.job', [('name', '=', 'DEMO IT Manager')])
if not job_mgr:
    job_mgr = env['hr.job'].create({
        'name': 'DEMO IT Manager',
        'company_id': env.company.id,
    })

job_hr_off = _find('hr.job', [('name', '=', 'DEMO HR & L&D Officer')])
if not job_hr_off:
    job_hr_off = env['hr.job'].create({
        'name': 'DEMO HR & L&D Officer',
        'company_id': env.company.id,
    })


# ─────────────────────────────────────────────────────────────────────────────
# 2. USERS & ROLE-BASED ACCESS CONTROL (RBAC)
# ─────────────────────────────────────────────────────────────────────────────
_log('Creating Test Users & Assigning Security Groups...')

# Groups lookup
g_emp_comp = env.ref('competency_management.group_competency_employee')
g_sup_comp = env.ref('competency_management.group_competency_supervisor')
g_adm_comp = env.ref('competency_management.group_competency_admin')

g_emp_eds = env.ref('employee_development_system.group_eds_employee')
g_mgr_eds = env.ref('employee_development_system.group_eds_line_manager')
g_trn_eds = env.ref('employee_development_system.group_eds_trainer')
g_off_eds = env.ref('employee_development_system.group_eds_officer')
g_ldm_eds = env.ref('employee_development_system.group_eds_manager')
g_adm_eds = env.ref('employee_development_system.group_eds_admin')

g_hr_user = env.ref('hr.group_hr_user')
g_hr_mgr = env.ref('hr.group_hr_manager')
g_internal_user = env.ref('base.group_user')


def _create_user(login, name, groups):
    u = _find('res.users', [('login', '=', login)])
    all_ou_ids = env['operating.unit'].search([]).ids
    if not u:
        partner = env['res.partner'].create({'name': name, 'email': login})
        group_ids = [(6, 0, [g.id for g in groups if g])]
        u = env['res.users'].with_context(
            no_reset_password=True,
            mail_create_nosubscribe=True,
            tracking_disable=True
        ).create({
            'name': name,
            'login': login,
            'password': '123456',
            'partner_id': partner.id,
            'group_ids': group_ids,
            'operating_unit_ids': [(6, 0, all_ou_ids)],
        })
        _log('Created user %s (Login: %s, Pass: 123456)' % (name, login))
    else:
        # Update password and operating units to ensure user can read team records
        u.write({
            'password': '123456',
            'operating_unit_ids': [(6, 0, all_ou_ids)],
        })
        # Ensure groups
        for g in groups:
            if g and g not in u.group_ids:
                u.write({'group_ids': [(4, g.id)]})
    return u


u_mgr = _create_user('line_manager@bunna.et', 'Abebe Kebede (Line Manager)',
                     [g_internal_user, g_sup_comp, g_mgr_eds, g_hr_user])

u_emp1 = _create_user('employee1@bunna.et', 'Tewodros Kassaye (Senior Developer)',
                      [g_internal_user, g_emp_comp, g_emp_eds])

u_emp2 = _create_user('employee2@bunna.et', 'Bethlehem Tadesse (HR Specialist)',
                      [g_internal_user, g_emp_comp, g_emp_eds])

u_emp3 = _create_user('employee3@bunna.et', 'Demeke Tesfaye (Junior Analyst)',
                      [g_internal_user, g_emp_comp, g_emp_eds])

u_ldo = _create_user('ld_officer@bunna.et', 'Dawit Worku (L&D Officer)',
                     [g_internal_user, g_sup_comp, g_off_eds, g_hr_user])

u_ldm = _create_user('ld_manager@bunna.et', 'Solomon Haile (L&D Manager)',
                     [g_internal_user, g_adm_comp, g_ldm_eds, g_hr_mgr])

u_admin = _create_user('hr_admin@bunna.et', 'Genet Assefa (HR Administrator)',
                       [g_internal_user, g_adm_comp, g_adm_eds, g_hr_mgr])

u_trainer = _create_user('trainer1@bunna.et', 'Mulugeta Berhanu (Senior Facilitator)',
                         [g_internal_user, g_trn_eds])


# ─────────────────────────────────────────────────────────────────────────────
# 3. EMPLOYEES & REPORTING HIERARCHY
# ─────────────────────────────────────────────────────────────────────────────
_log('Creating Employees & Manager Hierarchy...')


env = env(context=dict(env.context, no_version_sync=True, tracking_disable=True, mail_notrack=True, mail_create_nosubscribe=True, no_reset_password=True))


def _create_emp(name, user, job, ou, manager=None):
    emp = _find('hr.employee', [('user_id', '=', user.id)])
    if not emp:
        emp = env['hr.employee'].with_context(
            tracking_disable=True,
            mail_notrack=True,
            no_version_sync=True,
            mail_create_nosubscribe=True,
        ).create({
            'name': name,
            'user_id': user.id,
            'job_id': job.id,
            'default_operating_unit_id': ou.id,
            'parent_id': manager.id if manager else False,
            'work_email': user.login,
        })
    else:
        vals = {}
        if emp.job_id != job:
            vals['job_id'] = job.id
        if emp.default_operating_unit_id != ou:
            vals['default_operating_unit_id'] = ou.id
        if manager and emp.parent_id != manager:
            vals['parent_id'] = manager.id
        if vals:
            emp.with_context(
                tracking_disable=True,
                mail_notrack=True,
                no_version_sync=True,
                mail_create_nosubscribe=True,
            ).write(vals)
    return emp


emp_mgr = _create_emp('Abebe Kebede', u_mgr, job_mgr, ou_it)
emp_1 = _create_emp('Tewodros Kassaye', u_emp1, job_dev, ou_it, manager=emp_mgr)
emp_2 = _create_emp('Bethlehem Tadesse', u_emp2, job_hr_off, ou_hr, manager=emp_mgr)
emp_3 = _create_emp('Demeke Tesfaye', u_emp3, job_dev, ou_it, manager=emp_mgr)
emp_ldo = _create_emp('Dawit Worku', u_ldo, job_hr_off, ou_hr)
emp_ldm = _create_emp('Solomon Haile', u_ldm, job_hr_off, ou_hr)
emp_admin = _create_emp('Genet Assefa', u_admin, job_hr_off, ou_hr)
emp_trainer = _create_emp('Mulugeta Berhanu', u_trainer, job_dev, ou_it)

env.cr.commit()

# ─────────────────────────────────────────────────────────────────────────────
# 4. COMPETENCY FRAMEWORK, DICTIONARY & ROLE MAPPINGS
# ─────────────────────────────────────────────────────────────────────────────
_log('Seeding Competency Framework & Dictionary...')

fw = _find('competency.framework', [('code', '=', 'FW-2026')])
if not fw:
    fw = env['competency.framework'].create({
        'name': 'DEMO Enterprise Competency Framework 2026',
        'code': 'FW-2026',
        'version': 'v1.0',
        'state': 'draft',
        'description': 'Standard competency dictionary for Bunna Bank technical and managerial roles.',
    })


def _create_comp(name, code, pillar, desc):
    c = _find('competency.competency', [('code', '=', code)])
    if not c:
        c = env['competency.competency'].create({
            'name': name,
            'code': code,
            'pillar': pillar,
            'definition': desc,
            'status': 'active',
        })
        levels = [
            ('1', 'Level 1 - Basic', 'Understands core principles with supervision'),
            ('2', 'Level 2 - Intermediate', 'Applies skills to routine tasks independently'),
            ('3', 'Level 3 - Advanced', 'Handles complex tasks and solves operational issues'),
            ('4', 'Level 4 - Expert', 'Architects solutions and mentors team members'),
        ]
        for lvl, lname, ldesc in levels:
            env['competency.proficiency.level'].create({
                'competency_id': c.id,
                'level': lvl,
                'name': lname,
                'definition': ldesc,
            })
    return c


comp_python = _create_comp('Python & Odoo Development', 'CMP-PY-01', 'technical',
                           'Ability to write, debug, and architect modular Odoo applications and Python backend services.')

comp_sql = _create_comp('PostgreSQL Database Architecture & Tuning', 'CMP-DB-01', 'technical',
                        'Expertise in relational database schema design, indexing, and query performance optimization.')

comp_lead = _create_comp('Leadership & Team Management', 'CMP-MG-01', 'leadership',
                         'Capability to motivate teams, delegate effectively, and manage project deliverables.')

comp_comm = _create_comp('Professional Business Communication', 'CMP-BH-01', 'core',
                         'Effective verbal and written communication with stakeholders and leadership.')

# Attach competency lines to framework and approve
if fw.state == 'draft':
    fw.write({
        'line_ids': [
            (0, 0, {'competency_id': comp_python.id}),
            (0, 0, {'competency_id': comp_sql.id}),
            (0, 0, {'competency_id': comp_lead.id}),
            (0, 0, {'competency_id': comp_comm.id}),
        ],
        'state': 'approved',
    })

# Role Competency Mapping
map_dev = _find('competency.role.mapping', [('job_position_id', '=', job_dev.id)])
if not map_dev:
    map_dev = env['competency.role.mapping'].create({
        'job_position_id': job_dev.id,
        'version': 'v1.0',
        'state': 'approved',
        'line_ids': [
            (0, 0, {'competency_id': comp_python.id, 'required_proficiency': '4', 'weight': 40.0}),
            (0, 0, {'competency_id': comp_sql.id, 'required_proficiency': '4', 'weight': 35.0}),
            (0, 0, {'competency_id': comp_comm.id, 'required_proficiency': '3', 'weight': 25.0}),
        ]
    })


# ─────────────────────────────────────────────────────────────────────────────
# 5. COMPETENCY ASSESSMENT, GAP ANALYSIS & IDP
# ─────────────────────────────────────────────────────────────────────────────
_log('Seeding Competency Assessment Cycle, Assessments & IDP...')

cycle = _find('competency.assessment.cycle', [('name', '=', 'DEMO Q3 2026 Technical Review')])
if not cycle:
    cycle = env['competency.assessment.cycle'].create({
        'name': 'DEMO Q3 2026 Technical Review',
        'period_start': TODAY - timedelta(days=15),
        'period_end': TODAY + timedelta(days=15),
        'state': 'open',
    })

# Assessment for Tewodros (Senior Developer)
ass_tewodros = _find('competency.assessment', [('employee_id', '=', emp_1.id), ('cycle_id', '=', cycle.id)])
if not ass_tewodros:
    ass_tewodros = env['competency.assessment'].create({
        'employee_id': emp_1.id,
        'cycle_id': cycle.id,
        'assessor_id': u_mgr.id,
        'assessment_type': 'supervisor',
        'state': 'approved',
        'line_ids': [
            (0, 0, {
                'competency_id': comp_python.id,
                'required_level': '4',
                'current_level': '3',
                'comments': 'Strong Python skills, needs deeper understanding of Odoo ORM performance tuning.',
            }),
            (0, 0, {
                'competency_id': comp_sql.id,
                'required_level': '4',
                'current_level': '2',
                'comments': 'Basic SQL knowledge. Needs structured training on PostgreSQL indexing and query execution plans.',
            }),
        ]
    })

# Assessment for Bethlehem (HR Specialist) - Draft/Submitted for Manager Review
ass_bethlehem = _find('competency.assessment', [('employee_id', '=', emp_2.id), ('cycle_id', '=', cycle.id)])
if not ass_bethlehem:
    ass_bethlehem = env['competency.assessment'].create({
        'employee_id': emp_2.id,
        'cycle_id': cycle.id,
        'assessor_id': u_mgr.id,
        'assessment_type': 'supervisor',
        'state': 'submitted',
        'line_ids': [
            (0, 0, {
                'competency_id': comp_python.id,
                'required_level': '3',
                'current_level': '2',
                'comments': 'Intermediate Python proficiency.',
            }),
            (0, 0, {
                'competency_id': comp_sql.id,
                'required_level': '3',
                'current_level': '2',
                'comments': 'Intermediate database query knowledge.',
            }),
        ]
    })

# Individual Development Plan (IDP) for Tewodros
idp_tewodros = _find('competency.idp', [('employee_id', '=', emp_1.id)])
if not idp_tewodros:
    idp_tewodros = env['competency.idp'].create({
        'employee_id': emp_1.id,
        'assessment_id': ass_tewodros.id,
        'state': 'active',
        'goal_ids': [
            (0, 0, {
                'goal': 'Master Enterprise SQL Database Tuning and Indexing Strategies',
                'activity_type': 'training',
                'course_name': 'Enterprise SQL Database Tuning & PostgreSQL Performance',
                'status': 'in_progress',
            }),
            (0, 0, {
                'goal': 'Advanced Odoo Architecture & ORM Performance Mentorship',
                'activity_type': 'coaching',
                'course_name': 'Advanced Odoo ERP Development & ORM Optimization',
                'status': 'planned',
            }),
        ]
    })


# ─────────────────────────────────────────────────────────────────────────────
# 6. EDS CURRICULUM, COURSES, TNA & ANNUAL PLAN
# ─────────────────────────────────────────────────────────────────────────────
_log('Seeding EDS Curriculum, Courses & TNA...')

course_odoo = _find('eds.course', [('name', '=', 'Advanced Odoo ERP Development & ORM Optimization')])
if not course_odoo:
    course_odoo = env['eds.course'].create({
        'name': 'Advanced Odoo ERP Development & ORM Optimization',
        'category': 'technical_compliance',
        'delivery_method': 'internal',
        'duration_days': 5,
        'status': 'active',
    })

course_sql = _find('eds.course', [('name', '=', 'Enterprise SQL Database Tuning & PostgreSQL Performance')])
if not course_sql:
    course_sql = env['eds.course'].create({
        'name': 'Enterprise SQL Database Tuning & PostgreSQL Performance',
        'category': 'technical_compliance',
        'delivery_method': 'internal',
        'duration_days': 3,
        'status': 'active',
    })

# ─────────────────────────────────────────────────────────────────────────────
# 7. PROVIDER, TRAINER, VENUE & SESSIONS
# ─────────────────────────────────────────────────────────────────────────────
_log('Seeding Vendors, Trainers, Venues & Training Sessions...')

provider_emi = _find('eds.external.provider', [('name', '=', 'Ethiopian Management Institute (EMI)')])
if not provider_emi:
    provider_emi = env['eds.external.provider'].create({
        'name': 'Ethiopian Management Institute (EMI)',
        'category': 'local',
    })

trainer_internal = _find('eds.trainer', [('employee_id', '=', emp_trainer.id)])
if not trainer_internal:
    trainer_internal = env['eds.trainer'].create({
        'name': 'Mulugeta Berhanu',
        'trainer_type': 'internal',
        'employee_id': emp_trainer.id,
        'email': u_trainer.login,
        'state': 'active',
    })

venue_hall_a = _find('eds.venue', [('name', '=', 'Bunna Bank HQ Learning Center - Hall A')])
if not venue_hall_a:
    venue_hall_a = env['eds.venue'].create({
        'name': 'Bunna Bank HQ Learning Center - Hall A',
        'capacity': 2,
        'active': True,
    })

session_sql = _find('eds.session', [('course_id', '=', course_sql.id)])
if not session_sql:
    session_sql = env['eds.session'].create({
        'course_id': course_sql.id,
        'venue_id': venue_hall_a.id,
        'trainer_ids': [(4, trainer_internal.id)],
        'date_start': datetime.combine(TOMORROW, datetime.min.time()),
        'date_end': datetime.combine(TOMORROW + timedelta(days=3), datetime.max.time()),
        'capacity': 2,
        'status': 'scheduled',
    })


# ─────────────────────────────────────────────────────────────────────────────
# 8. NOMINATIONS & CAPACITY CONTROL (WAITLIST DEMONSTRATION)
# ─────────────────────────────────────────────────────────────────────────────
_log('Seeding Nominations & Waitlist Capacity Control...')

nom_1 = _find('eds.nomination', [('session_id', '=', session_sql.id), ('employee_id', '=', emp_1.id)])
if not nom_1:
    nom_1 = env['eds.nomination'].create({
        'session_id': session_sql.id,
        'employee_id': emp_1.id,
        'nominated_by': u_mgr.id,
        'state': 'approved',
        'waitlisted': False,
    })

nom_2 = _find('eds.nomination', [('session_id', '=', session_sql.id), ('employee_id', '=', emp_2.id)])
if not nom_2:
    nom_2 = env['eds.nomination'].create({
        'session_id': session_sql.id,
        'employee_id': emp_2.id,
        'nominated_by': u_mgr.id,
        'state': 'approved',
        'waitlisted': False,
    })

nom_3 = _find('eds.nomination', [('session_id', '=', session_sql.id), ('employee_id', '=', emp_3.id)])
if not nom_3:
    nom_3 = env['eds.nomination'].create({
        'session_id': session_sql.id,
        'employee_id': emp_3.id,
        'nominated_by': u_mgr.id,
        'state': 'approved',
        'waitlisted': True,
        'waitlist_position': 1,
    })


# ─────────────────────────────────────────────────────────────────────────────
# 9. ATTENDANCE, EVALUATIONS & CERTIFICATES
# ─────────────────────────────────────────────────────────────────────────────
_log('Seeding Attendance, Kirkpatrick Evaluations & Certificate...')

# Daily Attendance for Tewodros (emp_1)
att_1 = _find('eds.session.attendance', [('session_id', '=', session_sql.id), ('employee_id', '=', emp_1.id)])
if not att_1:
    env['eds.session.attendance'].create({
        'session_id': session_sql.id,
        'employee_id': emp_1.id,
        'attendance_date': TOMORROW,
        'attended': True,
        'hours_attended': 8.0,
    })

# Certificate
cert_1 = _find('eds.certificate', [('employee_id', '=', emp_1.id), ('session_id', '=', session_sql.id)])
if not cert_1:
    cert_1 = env['eds.certificate'].create({
        'employee_id': emp_1.id,
        'session_id': session_sql.id,
        'issue_date': TODAY,
        'is_eligible': True,
        'state': 'issued',
    })


# ─────────────────────────────────────────────────────────────────────────────
# 10. BUDGET, SPONSORSHIPS, INTERNSHIPS & UNSCHEDULED REQUESTS
# ─────────────────────────────────────────────────────────────────────────────
_log('Seeding Budget Lines, Sponsorships, Internships & Unscheduled Requests...')

# Budget
budget_it = _find('eds.budget', [('fiscal_year', '=', '2025/2026')])
if not budget_it:
    budget_it = env['eds.budget'].create({
        'fiscal_year': '2025/2026',
        'category': 'internal',
        'allocated': 500000.0,
        'state': 'approved',
    })

# Staff Education Sponsorship
sponsorship = _find('eds.sponsorship', [('employee_id', '=', emp_2.id)])
if not sponsorship:
    sponsorship = env['eds.sponsorship'].create({
        'employee_id': emp_2.id,
        'program_name': 'MSc in IT Governance - Addis Ababa University',
        'sponsorship_type': 'education',
        'approved_amount': 120000.0,
        'state': 'approved',
    })

# Internship Program Application
internship = _find('eds.internship.application', [('applicant_name', '=', 'Kidist Alemu')])
if not internship:
    internship = env['eds.internship.application'].create({
        'applicant_name': 'Kidist Alemu',
        'institution': 'Addis Ababa Institute of Technology (AAiT)',
        'field_of_study': 'Software Engineering',
        'scanned_application': b'c2Nhbm5lZF9kb2N1bWVudF9jb250ZW50cw==',
    })

# Unscheduled / Ad-hoc Training Request
unscheduled = _find('eds.unscheduled.request', [('justification', '=', 'Immediate operational requirement due to new NBE cyber resilience directives.')])
if not unscheduled:
    unscheduled = env['eds.unscheduled.request'].create({
        'employee_id': emp_1.id,
        'course_id': course_sql.id,
        'justification': 'Immediate operational requirement due to new NBE cyber resilience directives.',
        'state': 'approved',
    })

# Venue Requirement Specification (VRS)
vrs = _find('eds.venue.requirement', [('course_id', '=', course_sql.id)])
if not vrs:
    vrs = env['eds.venue.requirement'].create({
        'course_id': course_sql.id,
        'capacity_required': 25,
        'location_preference': 'Addis Ababa (Near HQ)',
        'facilities_required': 'High-speed LAN internet, Projector, High-spec Workstations for hands-on SQL performance labs.',
        'state': 'director_approved',
    })

# Training Contract
contract = _find('eds.training.contract', [('provider_id', '=', provider_emi.id)])
if not contract:
    contract = env['eds.training.contract'].create({
        'name': 'EMI 2026 Technical Training SLA Contract',
        'provider_id': provider_emi.id,
        'contract_amount': 250000.0,
        'start_date': TODAY - timedelta(days=60),
        'end_date': TODAY + timedelta(days=300),
        'state': 'active',
    })

env.cr.commit()

_log('===================================================================')
_log('SUCCESS: Competency Management & EDS Demo Data Seeding Completed!')
_log('===================================================================')
_log('Test Credentials (All passwords: 123456):')
_log('  - Line Manager:      line_manager@bunna.et')
_log('  - Senior Developer:  employee1@bunna.et')
_log('  - HR Specialist:     employee2@bunna.et')
_log('  - L&D Officer:       ld_officer@bunna.et')
_log('  - L&D Manager:       ld_manager@bunna.et')
_log('  - HR Administrator:  hr_admin@bunna.et')
_log('  - Senior Trainer:    trainer1@bunna.et')
_log('===================================================================')
