# -*- coding: utf-8 -*-
"""
Omni-Bank ERP — Comprehensive KMS & LMS Demo Data Seed Script
============================================================
Populates at least 3 to 4 realistic banking records for EVERY UI menu:
- KMS: All Policies & SOPs, Pending Review, Digital Library, Communities of Practice,
       Knowledge Sessions, Lessons Learned, Mentoring & Handover, Expert Directory,
       Q&A Forum Topics & Answers, Best Contributor awards, Points Ledger, Audit Logs.
- LMS: Assigned Courses, Course Catalog, Completed & History, All Courses,
       Courses Awaiting Approval, Learning Paths, Assignment Campaigns,
       Assessments, Question Bank, Question Pools, Candidate Exam Sessions,
       Issued Certificates, Certificate Templates, All Enrollments,
       Compliance Matrix analytics, Best Scorer awards, Learning Points Ledger.
- Recognition Engine: Monthly Champions, Unified Points Ledger.
- Bridge: Bidirectional linkage between Courses, Library, and Lessons Learned.
"""

import base64
import hashlib
import logging
from datetime import date, datetime, timedelta

_logger = logging.getLogger('seed_comprehensive_kms_lms')

def _log(msg):
    print('[COMPREHENSIVE-SEED] %s' % msg)

def _find(model, domain):
    return env[model].search(domain, limit=1)

TODAY = date.today()
NOW = datetime.now()
DUE_DATE = TODAY + timedelta(days=30)

dummy_pdf_content = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R/Resources<<>>>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n"
    b"0000000101 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n185\n%%EOF"
)
dummy_pdf_b64 = base64.b64encode(dummy_pdf_content)

_log('>>> Phase 1: Identifying & Aligning Master Data...')

# Find or ensure Departments
dept_credit = _find('hr.department', [('name', 'ilike', 'Credit')]) or env['hr.department'].create({'name': 'Credit & Appraisal'})
dept_retail = _find('hr.department', [('name', 'ilike', 'Retail')]) or env['hr.department'].create({'name': 'Retail Banking'})
dept_risk = _find('hr.department', [('name', 'ilike', 'Compliance')]) or _find('hr.department', [('name', 'ilike', 'Risk')]) or env['hr.department'].create({'name': 'Regulatory Compliance & AML'})
dept_it = _find('hr.department', [('name', 'ilike', 'Information Technology')]) or _find('hr.department', [('name', 'ilike', 'IT')]) or env['hr.department'].create({'name': 'Information Systems'})

# Find or ensure Operating Units / Branches
ou_ho = _find('operating.unit', [('name', 'ilike', 'Head Office')]) or env['operating.unit'].search([], limit=1)
ou_bole = _find('operating.unit', [('name', 'ilike', 'Bole')])
if not ou_bole:
    try:
        ou_bole = env['operating.unit'].create({'name': 'Bole Medhanealem Branch', 'code': 'BUNNA-BOL'})
    except Exception:
        ou_bole = ou_ho
ou_arada = _find('operating.unit', [('name', 'ilike', 'Arada')])
if not ou_arada:
    try:
        ou_arada = env['operating.unit'].create({'name': 'Arada Central Branch', 'code': 'BUNNA-ARD'})
    except Exception:
        ou_arada = ou_ho

# Find 4 Employees
all_emps = env['hr.employee'].search([], limit=10)
emp_1 = all_emps[0] if len(all_emps) > 0 else False
emp_2 = all_emps[1] if len(all_emps) > 1 else emp_1
emp_3 = all_emps[2] if len(all_emps) > 2 else emp_1
emp_4 = all_emps[3] if len(all_emps) > 3 else emp_2

# Check if current user has an employee
admin_user = env['res.users'].search([('login', 'in', ['desalegntamirat1993@gmail.com', 'admin'])], limit=1)
if admin_user:
    admin_emp = _find('hr.employee', [('user_id', '=', admin_user.id)])
    if not admin_emp and emp_1:
        # Link emp_1 to admin user so user sees my learning items
        emp_1.write({'user_id': admin_user.id})
        admin_emp = emp_1
else:
    admin_emp = emp_1

_log('Active Employees: %s, %s, %s, %s' % (
    emp_1.name if emp_1 else 'None',
    emp_2.name if emp_2 else 'None',
    emp_3.name if emp_3 else 'None',
    emp_4.name if emp_4 else 'None'
))

# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: KMS SEEDING (Ensure >= 4 items per menu)
# ─────────────────────────────────────────────────────────────────────────────
_log('>>> Phase 2: Seeding KMS Data...')

cat_credit = _find('kms.category', [('code', '=', 'CAT_CREDIT')])
cat_retail = _find('kms.category', [('code', '=', 'CAT_RETAIL')])
cat_risk = _find('kms.category', [('code', '=', 'CAT_RISK')])
cat_digital = _find('kms.category', [('code', '=', 'CAT_DIGITAL')])
cat_cyber = _find('kms.category', [('code', '=', 'CAT_CYBER')])
cat_trade = _find('kms.category', [('code', '=', 'CAT_TRADE')])

type_pol = _find('kms.document.type', [('code', '=', 'POL')])
type_sop = _find('kms.document.type', [('code', '=', 'SOP')])
type_dir = _find('kms.document.type', [('code', '=', 'DIR')])
type_gdl = _find('kms.document.type', [('code', '=', 'GDL')])

class_pub = _find('kms.classification', [('code', '=', 'PUB')])
class_int = _find('kms.classification', [('code', '=', 'INT')])
class_conf = _find('kms.classification', [('code', '=', 'CONF')])
class_sconf = _find('kms.classification', [('code', '=', 'SCONF')])

# 1. Governed Documents - Approved (4 items)
docs_approved_data = [
    {
        'name': 'Bunna Bank Credit Risk Assessment & Underwriting Policy',
        'cat': cat_credit, 'type': type_pol, 'class': class_conf, 'dept': dept_credit, 'ou': ou_ho,
        'owner': emp_1, 'ver': '1.0',
        'summary': 'Establishes institutional credit risk tolerances, Single Borrower Limits (SBL), collateral haircuts, and lending governance principles.',
        'content': 'Credit Underwriting Policy Bunna Bank Collateral Debt Service Coverage Ratio DSCR Loan-to-Value LTV Credit Committee Approvals',
    },
    {
        'name': 'Standard Operating Procedure for High-Value Cash Remittance',
        'cat': cat_retail, 'type': type_sop, 'class': class_int, 'dept': dept_retail, 'ou': ou_bole,
        'owner': emp_2, 'ver': '1.2',
        'summary': 'Standardized protocol for vault balancing, cash-in-transit (CIT) handoffs, and dual-custody authorization.',
        'content': 'Cash Remittance Dual Custody Vault Security Armored Transport Branch Operations Teller Limits',
    },
    {
        'name': 'Customer Due Diligence (CDD) & Know-Your-Customer (KYC) Directive Policy',
        'cat': cat_risk, 'type': type_pol, 'class': class_sconf, 'dept': dept_risk, 'ou': ou_ho,
        'owner': emp_3, 'ver': '2.0',
        'summary': 'Mandatory directives for onboarding high-risk political persons (PEPs), ultimate beneficial ownership (UBO), and account freezing.',
        'content': 'CDD KYC Anti-Money Laundering Counter-Terrorist Financing PEP Sanctions Screening',
    },
    {
        'name': 'Information Security & Cyber Incident Response SOP',
        'cat': cat_cyber, 'type': type_sop, 'class': class_conf, 'dept': dept_it, 'ou': ou_ho,
        'owner': emp_4, 'ver': '1.1',
        'summary': 'Operational protocols for triage, containment, escalation, and forensic evidence collection during security incidents.',
        'content': 'Incident Response SOC Cyber Attack Phishing Malware Containment Disaster Recovery',
    },
]

for d in docs_approved_data:
    existing = _find('kms.document', [('name', '=', d['name'])])
    if not existing and d['cat'] and d['type'] and d['class']:
        env['kms.document'].create({
            'name': d['name'],
            'category_id': d['cat'].id,
            'doc_type_id': d['type'].id,
            'classification_id': d['class'].id,
            'department_id': d['dept'].id if d['dept'] else False,
            'operating_unit_id': d['ou'].id if d['ou'] else False,
            'owner_id': d['owner'].id if d['owner'] else False,
            'version': d['ver'],
            'state': 'approved',
            'effective_date': TODAY - timedelta(days=30),
            'summary': d['summary'],
            'content_text': d['content'],
            'require_watermark': True,
            'file_data': dummy_pdf_b64,
            'file_name': d['name'][:30].replace(' ', '_') + '.pdf',
            'view_count': 35,
            'download_count': 12,
        })
_log('Seeded Approved Documents (Total 4)')

# 2. Governed Documents - Pending Review (4 items so "Pending Review" menu is never empty!)
docs_pending_data = [
    {
        'name': 'Mobile Banking Limits & Biometric Authentication Directive',
        'cat': cat_digital, 'type': type_dir, 'class': class_int, 'dept': dept_it, 'ou': ou_ho,
        'owner': emp_3, 'ver': '1.0',
        'summary': 'Proposes updated daily transaction caps and mandatory biometric/OTP triggers for instant digital transfers.',
    },
    {
        'name': 'Collateral Valuation Guidelines for Commercial Mortgages',
        'cat': cat_credit, 'type': type_gdl, 'class': class_conf, 'dept': dept_credit, 'ou': ou_ho,
        'owner': emp_1, 'ver': '1.0',
        'summary': 'Appraisal standards and mandatory depreciation schedules for industrial properties and commercial buildings.',
    },
    {
        'name': 'Whistleblower Protection & Anti-Bribery Compliance Policy',
        'cat': cat_risk, 'type': type_pol, 'class': class_sconf, 'dept': dept_risk, 'ou': ou_ho,
        'owner': emp_2, 'ver': '1.0',
        'summary': 'Anonymous internal reporting channels, anti-retaliation protections, and disciplinary investigation guidelines.',
    },
    {
        'name': 'SWIFT Documentary Credit (MT700) Issuance Procedure',
        'cat': cat_trade, 'type': type_sop, 'class': class_conf, 'dept': dept_credit, 'ou': ou_ho,
        'owner': emp_4, 'ver': '1.0',
        'summary': 'Verification steps for cross-border documentary collections, counter-guarantees, and SWIFT message authentication.',
    },
]

for d in docs_pending_data:
    existing = _find('kms.document', [('name', '=', d['name'])])
    if not existing and d['cat'] and d['type'] and d['class']:
        env['kms.document'].create({
            'name': d['name'],
            'category_id': d['cat'].id,
            'doc_type_id': d['type'].id,
            'classification_id': d['class'].id,
            'department_id': d['dept'].id if d['dept'] else False,
            'operating_unit_id': d['ou'].id if d['ou'] else False,
            'owner_id': d['owner'].id if d['owner'] else False,
            'version': d['ver'],
            'state': 'review',
            'summary': d['summary'],
            'require_watermark': True,
            'file_data': dummy_pdf_b64,
            'file_name': d['name'][:30].replace(' ', '_') + '.pdf',
        })
_log('Seeded Pending Review Documents (Total 4)')

# 3. Digital Library (4 items)
library_data = [
    {
        'name': 'Basel III Capital Accord and Credit Risk Stress Testing Guide',
        'author': 'Bank for International Settlements (BIS) / NBE Advisory',
        'cat': cat_risk, 'type': 'ebook', 'year': '2024', 'rec': True,
        'summary': 'Comprehensive textbook on risk-weighted assets (RWA), liquidity coverage ratios (LCR), and countercyclical capital buffers.',
        'rating': 5.0,
    },
    {
        'name': 'FinTech & Real-Time Payments: Ethiopian Banking Industry Study',
        'author': 'National Digital Payments Strategy Research Group',
        'cat': cat_digital, 'type': 'whitepaper', 'year': '2025', 'rec': True,
        'summary': 'In-depth empirical research on mobile interoperability, QR standardizations, and digital credit scoring mechanisms.',
        'rating': 4.8,
    },
    {
        'name': 'ICC Uniform Customs and Practice for Documentary Credits (UCP 600)',
        'author': 'International Chamber of Commerce',
        'cat': cat_trade, 'type': 'training_reference', 'year': '2023', 'rec': False,
        'summary': 'Universal rules governing trade finance, letters of credit, bill of lading discrepancy exceptions, and international banking obligations.',
        'rating': 4.9,
    },
    {
        'name': 'National Bank of Ethiopia Directives Compendium 2026',
        'author': 'NBE Directorate of Banking Supervision',
        'cat': cat_risk, 'type': 'regulatory', 'year': '2026', 'rec': True,
        'summary': 'Full official compendium of foreign exchange allocations, capital adequacy norms, and statutory reserve requirements.',
        'rating': 5.0,
    },
]

for l in library_data:
    existing = _find('kms.digital.library', [('name', '=', l['name'])])
    if not existing and l['cat']:
        env['kms.digital.library'].create({
            'name': l['name'],
            'author': l['author'],
            'resource_type': l['type'],
            'category_id': l['cat'].id,
            'publication_year': l['year'],
            'is_recommended': l['rec'],
            'summary': l['summary'],
            'rating_average': l['rating'],
            'file_data': dummy_pdf_b64,
            'file_name': l['name'][:30].replace(' ', '_') + '.pdf',
            'view_count': 45,
            'download_count': 18,
        })
_log('Seeded Digital Library Assets (Total 4)')

# 4. Communities of Practice (4 CoPs)
cop_data = [
    {
        'name': 'Credit Risk & Lending Excellence CoP',
        'code': 'COP-CREDIT', 'cat': cat_credit, 'lead': emp_1,
        'desc': 'Collaborative domain space for underwriters, credit analysts, and relationship managers across all districts.',
    },
    {
        'name': 'Retail Banking & Frontline Customer Experience CoP',
        'code': 'COP-RETAIL', 'cat': cat_retail, 'lead': emp_2,
        'desc': 'Sharing best practices in teller operations, high-net-worth relationship onboarding, and branch queue management.',
    },
    {
        'name': 'Cyber Resilience & Core Banking Architecture CoP',
        'code': 'COP-CYBER', 'cat': cat_cyber, 'lead': emp_3,
        'desc': 'Technical guild addressing system uptime, SQL optimization, database clustering, and security patch testing.',
    },
    {
        'name': 'Trade Services & Foreign Exchange Operations CoP',
        'code': 'COP-TRADE', 'cat': cat_trade, 'lead': emp_4,
        'desc': 'Specialized forum for international banking staff managing import/export finance and FX priority matrices.',
    },
]

for c in cop_data:
    existing = _find('kms.cop', [('code', '=', c['code'])])
    if not existing and c['cat'] and c['lead']:
        env['kms.cop'].create({
            'name': c['name'],
            'code': c['code'],
            'category_id': c['cat'].id,
            'lead_id': c['lead'].id,
            'member_ids': [(6, 0, [emp_1.id, emp_2.id, emp_3.id, emp_4.id] if emp_4 else [emp_1.id, emp_2.id])],
            'description': '<p>%s</p>' % c['desc'],
            'meeting_cadence': 'monthly',
        })
_log('Seeded Communities of Practice (Total 4)')

# 5. Knowledge Capture Sessions (4 sessions)
cop_c = _find('kms.cop', [('code', '=', 'COP-CREDIT')])
cop_r = _find('kms.cop', [('code', '=', 'COP-RETAIL')])
cop_cy = _find('kms.cop', [('code', '=', 'COP-CYBER')])
cop_t = _find('kms.cop', [('code', '=', 'COP-TRADE')])

sess_data = [
    {
        'name': 'SME Masterclass: Trade Finance Letters of Credit Risk Mitigation',
        'cop': cop_t or cop_c, 'type': 'expert_interview', 'expert': emp_1, 'fac': emp_2,
        'summary': 'Captured tacit know-how regarding foreign exchange allocation prioritization and LC discrepancies.',
    },
    {
        'name': 'Executive Debrief: Credit Committee Underwriting in Turbulent Sectors',
        'cop': cop_c, 'type': 'exit_debrief', 'expert': emp_1, 'fac': emp_3,
        'summary': 'Key lessons on evaluating agricultural commodity exporters under volatile foreign market pricing.',
    },
    {
        'name': 'Branch Operations Brown-Bag: Vault Balancing & Discrepancy Escapes',
        'cop': cop_r or cop_c, 'type': 'brown_bag', 'expert': emp_2, 'fac': emp_1,
        'summary': 'Practical tips for end-of-day teller reconciliation and cash-in-transit security handoffs.',
    },
    {
        'name': 'Incident Post-Mortem: Core Banking High-Volume Batch Performance Tuning',
        'cop': cop_cy or cop_c, 'type': 'project_retro', 'expert': emp_3, 'fac': emp_4,
        'summary': 'Technical root cause breakdown and tuning parameters implemented to resolve connection pool exhaustion.',
    },
]

for s in sess_data:
    existing = _find('kms.knowledge.session', [('name', '=', s['name'])])
    if not existing and s['cop'] and s['expert']:
        env['kms.knowledge.session'].create({
            'name': s['name'],
            'cop_id': s['cop'].id,
            'session_type': s['type'],
            'expert_id': s['expert'].id,
            'facilitator_id': s['fac'].id if s['fac'] else False,
            'session_date': NOW - timedelta(days=10),
            'duration_hours': 1.5,
            'summary': '<p>%s</p>' % s['summary'],
            'key_takeaways': '<p>1. Rigorous pre-validation.<br/>2. Standardized escalation triggers.</p>',
            'state': 'completed',
        })
_log('Seeded Knowledge Capture Sessions (Total 4)')

# 6. Lessons Learned (4 items)
lessons_data = [
    {
        'name': 'Core Banking System Cutover: Database Transaction Timeout Mitigation',
        'cat': cat_cyber, 'dept': dept_it, 'author': emp_3, 'sev': 'high', 'votes': 18,
        'summary': 'During month-end high volume batch processing, connection pooling reached peak limits causing timeout.',
        'lesson': 'Always tune connection pool sizes to 3x peak estimated transaction volume during major upgrade deployments.',
        'mitigation': 'Configured automatic dynamic worker scaling in PostgreSQL backend.',
    },
    {
        'name': 'ATM Cash Replenishment Discrepancy Prevention in Outlying Branches',
        'cat': cat_retail, 'dept': dept_retail, 'author': emp_2, 'sev': 'medium', 'votes': 12,
        'summary': 'Physical cash count variance occurred due to delayed cassette audit logging during night-shift replenishment.',
        'lesson': 'Mandate dual-custody real-time barcode scanning of each cash cassette upon vault exit.',
        'mitigation': 'Updated branch standard operating checklist and handheld scanner enforcement.',
    },
    {
        'name': 'Export Loan Refinancing: Mitigating Export Proceeds Non-Repatriation',
        'cat': cat_credit, 'dept': dept_credit, 'author': emp_1, 'sev': 'critical', 'votes': 22,
        'summary': 'Borrower experienced export proceeds delays from foreign correspondent bank, threatening default.',
        'lesson': 'Require confirmed irrevocable letters of credit from tier-1 international banks for pre-shipment advances.',
        'mitigation': 'Integrated real-time SWIFT gpi tracking alerts in credit monitoring dashboard.',
    },
    {
        'name': 'Mobile App Surge Traffic During Civil Service Salary Disbursements',
        'cat': cat_digital, 'dept': dept_it, 'author': emp_4, 'sev': 'high', 'votes': 14,
        'summary': 'Simultaneous login attempts by 150,000 customers degraded API gateway response times.',
        'lesson': 'Implement Redis caching layer for account balance lookups and staggered push notification schedules.',
        'mitigation': 'Deployed read-replica database instances dedicated to mobile read queries.',
    },
]

for l in lessons_data:
    existing = _find('kms.lesson.learned', [('name', '=', l['name'])])
    if not existing and l['cat'] and l['author']:
        env['kms.lesson.learned'].create({
            'name': l['name'],
            'project_initiative': l['name'][:40],
            'category_id': l['cat'].id,
            'department_id': l['dept'].id if l['dept'] else False,
            'author_id': l['author'].id,
            'severity_impact': l['sev'],
            'event_summary': l['summary'],
            'root_cause': 'Configuration bottleneck identified during operational peak.',
            'key_lesson': '<p>%s</p>' % l['lesson'],
            'mitigation_recommendation': '<p>%s</p>' % l['mitigation'],
            'state': 'reviewed',
            'helpful_votes': l['votes'],
        })
_log('Seeded Lessons Learned (Total 4)')

# 7. Mentoring & Handover (4 items so "Mentoring & Handover" menu is populated!)
mentor_data = [
    {
        'title': 'Senior Underwriter to Junior Credit Analyst Mentoring Roadmap',
        'mentor': emp_1, 'mentee': emp_2, 'cadence': 'biweekly',
        'obj': 'Develop advanced competency in non-financial credit assessment, forensic balance sheet auditing, and cash flow modeling.',
        'state': 'in_progress',
    },
    {
        'title': 'Branch Manager Succession & Operational Custody Handover',
        'mentor': emp_2, 'mentee': emp_3, 'cadence': 'weekly',
        'obj': 'Comprehensive knowledge transfer covering vault combinations, branch security liaison, and district performance targets.',
        'state': 'completed',
    },
    {
        'title': 'Information Security Specialist Cyber Threat Hunting Apprenticeship',
        'mentor': emp_3, 'mentee': emp_4, 'cadence': 'weekly',
        'obj': 'Transfer expertise in SIEM log correlation, firewall rule validation, and internal penetration testing methodologies.',
        'state': 'in_progress',
    },
    {
        'title': 'Trade Finance Specialist Bilateral Knowledge Roadmap',
        'mentor': emp_1, 'mentee': emp_4, 'cadence': 'biweekly',
        'obj': 'Mastery of ICC UCP 600 rules, import permit regulations, and foreign exchange queue governance.',
        'state': 'in_progress',
    },
]

for m in mentor_data:
    existing = _find('kms.mentoring.track', [('name', '=', m['title'])])
    if not existing and m['mentor'] and m['mentee']:
        env['kms.mentoring.track'].create({
            'name': m['title'],
            'mentor_id': m['mentor'].id,
            'mentee_id': m['mentee'].id,
            'department_id': m['mentor'].department_id.id if m['mentor'].department_id else False,
            'start_date': TODAY - timedelta(days=60),
            'target_end_date': TODAY + timedelta(days=60),
            'transfer_focus': m['obj'],
            'state': m['state'],
        })
_log('Seeded Mentoring & Handover Records (Total 4)')

# 8. Expert Directory (4 profiles)
expert_domains = [
    (emp_1, 'credit', '14 years specializing in large commercial underwriting, syndication, and NBE single borrower compliance.', 'CFA, PRM', 14.0, 16),
    (emp_2, 'retail', '10 years leading branch network customer service, cash management, and queue optimization.', 'Certified Retail Banker (CRB)', 10.0, 12),
    (emp_3, 'it_security', '12 years in enterprise network defense, security incident response, and ISO 27001 implementation.', 'CISSP, CEH, CISM', 12.0, 20),
    (emp_4, 'trade_finance', '9 years in international banking, import/export trade documentary credits, and SWIFT governance.', 'CDCS, CITF', 9.0, 11),
]

for emp, dom, summ, cert, exp_yrs, endo in expert_domains:
    if emp:
        existing = _find('kms.expert', [('employee_id', '=', emp.id)])
        if not existing:
            env['kms.expert'].create({
                'employee_id': emp.id,
                'primary_domain': dom,
                'expertise_summary': '<p>%s</p>' % summ,
                'certifications_held': cert,
                'years_experience': exp_yrs,
                'availability_status': 'available',
                'endorsement_count': endo,
            })
_log('Seeded Expert Directory Profiles (Total 4)')

# 9. Q&A Forum Topics & Answers (4 topics with active answers!)
forum_data = [
    {
        'title': 'How to handle conflicting transport document dates under UCP 600 Article 14?',
        'cat': cat_trade, 'author': emp_4,
        'body': '<p>If an inland bill of lading shows an issuance date differing from the on-board notation, which date governs under UCP 600?</p>',
        'views': 42,
        'answers': [
            {'author': emp_1, 'body': '<p>Under UCP 600 Article 14(c) and Article 20, the date of the on-board notation is deemed to be the date of shipment regardless of the document issuance date.</p>', 'votes': 7, 'acc': True},
            {'author': emp_3, 'body': '<p>Ensure that the notation explicitly names the carrying vessel as per the documentary credit stipulations.</p>', 'votes': 3, 'acc': False},
        ],
    },
    {
        'title': 'Requirements for commercial mortgage loan restructuring under NBE directive',
        'cat': cat_credit, 'author': emp_2,
        'body': '<p>What minimum debt-service coverage ratio (DSCR) is acceptable for a 2-year loan tenure extension?</p>',
        'views': 58,
        'answers': [
            {'author': emp_1, 'body': '<p>NBE Asset Quality Directive requires a projected DSCR of at least 1.20x supported by audited financial statements and an updated collateral appraisal.</p>', 'votes': 9, 'acc': True},
        ],
    },
    {
        'title': 'Best practice for end-of-day ATM cash balancing discrepancies',
        'cat': cat_retail, 'author': emp_2,
        'body': '<p>When the electronic journal transaction total differs from the cassette physical count by under 500 ETB, what is the required audit protocol?</p>',
        'views': 36,
        'answers': [
            {'author': emp_3, 'body': '<p>Log the discrepancy immediately in the ATM suspense clearing ledger. Do not force balance. Perform dual-custody audit within 24 hours.</p>', 'votes': 6, 'acc': True},
        ],
    },
    {
        'title': 'Recommended timeouts for branch VPN tunnels during rainy season connectivity drops',
        'cat': cat_cyber, 'author': emp_3,
        'body': '<p>Are remote district branches allowed to use secondary cellular APN fallback automatically?</p>',
        'views': 29,
        'answers': [
            {'author': emp_4, 'body': '<p>Yes, SD-WAN failover is pre-authorized. Secondary cellular tunnels are fully encrypted with IPsec AES-256.</p>', 'votes': 5, 'acc': True},
        ],
    },
]

for ft in forum_data:
    existing = _find('kms.forum.topic', [('name', '=', ft['title'])])
    if not existing and ft['cat'] and ft['author']:
        topic = env['kms.forum.topic'].create({
            'name': ft['title'],
            'category_id': ft['cat'].id,
            'author_id': ft['author'].id,
            'content': ft['body'],
            'view_count': ft['views'],
            'state': 'solved' if any(a['acc'] for a in ft['answers']) else 'open',
            'is_solved': any(a['acc'] for a in ft['answers']),
        })
        for ans in ft['answers']:
            env['kms.forum.post'].create({
                'topic_id': topic.id,
                'author_id': ans['author'].id if ans['author'] else ft['author'].id,
                'content': ans['body'],
                'is_accepted': ans['acc'],
            })
_log('Seeded Q&A Forum Topics & Answers (Total 4)')

# 10. KMS Audit Logs (6 entries)
audit_samples = [
    ('download', 'document', 'Credit Risk Underwriting Policy', emp_1, 'Downloaded Credit Risk Underwriting Policy with watermark'),
    ('view', 'document', 'High-Value Cash Remittance SOP', emp_2, 'Viewed High-Value Cash Remittance SOP'),
    ('join', 'cop', 'Credit Risk Excellence CoP', emp_3, 'Joined Credit Risk Excellence CoP'),
    ('upload', 'lesson_learned', 'Core Banking System Cutover', emp_1, 'Published Lesson Learned: Core Banking Cutover'),
    ('upload', 'forum', 'Transport document dates under UCP 600', emp_1, 'Provided accepted answer on UCP 600 transport dates'),
    ('view', 'document', 'Strictly Confidential KYC Directive Policy', emp_3, 'Authorized view of Strictly Confidential KYC Directive Policy'),
]
admin_user = env['res.users'].browse(1)
for act, res_type, res_name, emp, desc in audit_samples:
    u = emp.user_id if (emp and emp.user_id) else admin_user
    env['kms.audit.log'].sudo().create({
        'user_id': u.id,
        'action': act,
        'resource_type': res_type,
        'resource_name': res_name,
        'employee_id': emp.id if emp else False,
        'department_id': emp.department_id.id if (emp and emp.department_id) else False,
        'details': desc,
    })
_log('Seeded KMS Compliance Audit Logs (Total 6)')
env.cr.commit()
_log('Committed Phase 2 (KMS) changes.')

# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: LMS SEEDING (Ensure >= 4 items per menu)
# ─────────────────────────────────────────────────────────────────────────────
_log('>>> Phase 3: Seeding LMS Data...')

lms_cat_comp = _find('lms.category', [('code', '=', 'LMS_COMP')])
lms_cat_credit = _find('lms.category', [('code', '=', 'LMS_CREDIT')])
lms_cat_ops = _find('lms.category', [('code', '=', 'LMS_OPS')])
lms_cat_digital = _find('lms.category', [('code', '=', 'LMS_DIGITAL')])
lms_cat_lead = _find('lms.category', [('code', '=', 'LMS_LEAD')])

# 1. LMS Published Courses (4 items)
courses_published = [
    {
        'name': 'Anti-Money Laundering (AML/CFT) & Regulatory Compliance Masterclass',
        'cat': lms_cat_comp, 'inst': emp_1, 'mand': True, 'hrs': 2.0, 'score': 80.0,
        'desc': 'Comprehensive regulatory training on AML/CFT directive compliance, suspicious transaction reporting (STR), and risk scoring.',
    },
    {
        'name': 'Commercial Lending & Corporate Financial Statement Analysis',
        'cat': lms_cat_credit, 'inst': emp_1, 'mand': True, 'hrs': 4.0, 'score': 75.0,
        'desc': 'Advanced analysis of balance sheets, income statements, working capital adequacy, and debt capacity evaluation.',
    },
    {
        'name': 'Frontline Branch Operations & Customer Service Excellence',
        'cat': lms_cat_ops, 'inst': emp_2, 'mand': False, 'hrs': 1.5, 'score': 70.0,
        'desc': 'Professional customer care standards, high-volume teller accuracy, conflict de-escalation, and complaint resolution.',
    },
    {
        'name': 'Cyber Security Hygiene & Social Engineering Defense 2026',
        'cat': lms_cat_digital, 'inst': emp_3, 'mand': True, 'hrs': 1.0, 'score': 80.0,
        'desc': 'Bank-wide threat defense covering spear phishing, credential stuffing, safe removable media handling, and password hygiene.',
    },
]

created_courses = []
for cp in courses_published:
    c_rec = _find('lms.course', [('name', '=', cp['name'])])
    if not c_rec and cp['cat'] and cp['inst']:
        c_rec = env['lms.course'].create({
            'name': cp['name'],
            'category_id': cp['cat'].id,
            'instructor_id': cp['inst'].id,
            'is_mandatory': cp['mand'],
            'estimated_duration_hours': cp['hrs'],
            'pass_score_percentage': cp['score'],
            'version': '1.0',
            'state': 'published',
            'description': '<p>%s</p>' % cp['desc'],
            'issue_certificate': True,
        })
        # Add basic section and lesson
        sec = env['lms.course.section'].create({
            'course_id': c_rec.id,
            'name': 'Core Module 1: Foundations',
            'sequence': 10,
        })
        env['lms.lesson'].create({
            'course_id': c_rec.id,
            'section_id': sec.id,
            'name': 'Lesson 1.1: Core Concepts & Regulatory Principles',
            'lesson_type': 'video',
            'video_source_type': 'file',
            'video_duration_seconds': 600,
            'sequence': 10,
            'is_mandatory': True,
        })
        env['lms.lesson'].create({
            'course_id': c_rec.id,
            'section_id': sec.id,
            'name': 'Lesson 1.2: Practical Banking Applications',
            'lesson_type': 'document',
            'document_file': dummy_pdf_b64,
            'document_filename': 'Reference_Guide.pdf',
            'sequence': 20,
            'is_mandatory': True,
        })
    if c_rec:
        created_courses.append(c_rec)
_log('Seeded Published LMS Courses (Total %d)' % len(created_courses))

# 2. LMS Courses Awaiting Approval (4 items so "Awaiting Approval" menu is never empty!)
courses_review = [
    {
        'name': 'Trade Finance: Letters of Credit & Bank Guarantees Mastery',
        'cat': lms_cat_credit, 'inst': emp_4, 'hrs': 3.0,
        'desc': 'Step-by-step masterclass on UCP 600 compliance, import LC amendments, and trade sanction checks.',
    },
    {
        'name': 'Digital Banking: Bunna Mobile App & POS Merchant Terminals',
        'cat': lms_cat_digital, 'inst': emp_3, 'hrs': 2.0,
        'desc': 'Merchant onboarding workflows, POS dispute handling, and mobile wallet reconciliation procedures.',
    },
    {
        'name': 'Internal Audit Standards & Branch Operational Risk Controls',
        'cat': lms_cat_comp, 'inst': emp_1, 'hrs': 2.5,
        'desc': 'Comprehensive audit readiness checklist for branch supervisors and operational risk inspectors.',
    },
    {
        'name': 'Supervisory Leadership & High-Performance Team Coaching',
        'cat': lms_cat_lead, 'inst': emp_2, 'hrs': 3.5,
        'desc': 'Leadership habits, operational delegating, employee retention, and constructive performance feedback.',
    },
]

for cr in courses_review:
    existing = _find('lms.course', [('name', '=', cr['name'])])
    if not existing and cr['cat'] and cr['inst']:
        env['lms.course'].create({
            'name': cr['name'],
            'category_id': cr['cat'].id,
            'instructor_id': cr['inst'].id,
            'estimated_duration_hours': cr['hrs'],
            'pass_score_percentage': 75.0,
            'version': '1.0',
            'state': 'review',
            'description': '<p>%s</p>' % cr['desc'],
        })
_log('Seeded Courses Awaiting Approval (Total 4)')

# 3. Learning Paths (4 paths)
path_data = [
    {
        'name': 'Branch Operations Leadership & Compliance Path',
        'code': 'PATH-BR-MGR', 'cat': lms_cat_comp,
        'desc': 'Mandatory progression path for branch managers and customer service supervisors.',
    },
    {
        'name': 'Credit Risk & Corporate Underwriting Pathway',
        'code': 'PATH-CREDIT-SPEC', 'cat': lms_cat_credit,
        'desc': 'Curriculum track for corporate underwriters, loan restructuring specialists, and credit analysts.',
    },
    {
        'name': 'Digital Transformation & Banking Technology Track',
        'code': 'PATH-DIGITAL-TECH', 'cat': lms_cat_digital,
        'desc': 'Comprehensive pathway covering cyber hygiene, mobile banking products, and digital channel risk.',
    },
    {
        'name': 'New Employee Banking Induction & Regulatory Foundation',
        'code': 'PATH-INDUCTION', 'cat': lms_cat_lead,
        'desc': 'Mandatory onboarding curriculum for all newly hired banking professionals across all operating units.',
    },
]

for p in path_data:
    existing = _find('lms.learning.path', [('code', '=', p['code'])])
    if not existing and p['cat']:
        path_rec = env['lms.learning.path'].create({
            'name': p['name'],
            'code': p['code'],
            'category_id': p['cat'].id,
            'description': '<p>%s</p>' % p['desc'],
        })
        # Add first published course to path
        if created_courses:
            env['lms.learning.path.course'].create({
                'path_id': path_rec.id,
                'course_id': created_courses[0].id,
                'sequence': 10,
                'is_optional_branch': False,
            })
            if len(created_courses) > 1:
                env['lms.learning.path.course'].create({
                    'path_id': path_rec.id,
                    'course_id': created_courses[1].id,
                    'sequence': 20,
                    'is_optional_branch': True,
                    'branch_group_code': 'ELECTIVE_STAGE',
                })
_log('Seeded Learning Paths (Total 4)')

# 4. Assignment Campaigns (4 campaigns)
assign_data = [
    {
        'name': 'Bank-wide Mandatory AML/CFT 2026 Annual Recertification',
        'course': created_courses[0] if created_courses else False,
        'dept': dept_risk, 'target': 'all',
    },
    {
        'name': 'Credit Underwriting & Risk Analysis Certification Drive',
        'course': created_courses[1] if len(created_courses) > 1 else False,
        'dept': dept_credit, 'target': 'department',
    },
    {
        'name': 'Frontline Branch Staff Customer Service Excellence Campaign',
        'course': created_courses[2] if len(created_courses) > 2 else False,
        'dept': dept_retail, 'target': 'department',
    },
    {
        'name': 'Q3 Information Security & Phishing Awareness Campaign',
        'course': created_courses[3] if len(created_courses) > 3 else False,
        'dept': dept_it, 'target': 'all',
    },
]

for a in assign_data:
    if a['course']:
        existing = _find('lms.course.assignment', [('name', '=', a['name'])])
        if not existing:
            env['lms.course.assignment'].create({
                'name': a['name'],
                'course_id': a['course'].id,
                'assignment_type': 'all_staff' if a['target'] == 'all' else 'department',
                'department_ids': [(6, 0, [a['dept'].id])] if a['dept'] else False,
                'due_date': DUE_DATE,
                'state': 'executed',
                'enrolled_count': 15,
            })
_log('Seeded Assignment Campaigns (Total 4)')

# 5. Question Pools & Bank (4 pools with multiple questions)
pool_data = [
    ('POOL-AML', 'AML/CFT Regulatory Examination Pool', 'Directives, KYC, STR, and CTR compliance'),
    ('POOL-CREDIT', 'Credit Underwriting & Financial Ratio Pool', 'DSCR, LTV, debt service, and appraisal principles'),
    ('POOL-OPS', 'Branch Operations & Teller Security Pool', 'Vault balancing, dual custody, and cash limits'),
    ('POOL-CYBER', 'Cyber Security & Phishing Defense Pool', 'Social engineering, credential safety, and incident reporting'),
]

created_pools = []
for code, name, desc in pool_data:
    p_rec = _find('lms.question.pool', [('code', '=', code)])
    if not p_rec:
        p_rec = env['lms.question.pool'].create({
            'name': name,
            'code': code,
            'description': desc,
        })
    created_pools.append(p_rec)

# Add Questions
sample_questions = [
    (created_pools[0], 'NBE Cash Transaction Report Threshold', 'single_choice',
     'Under NBE directives, what is the mandatory threshold for filing a Cash Transaction Report (CTR)?',
     [('100,000 ETB', False), ('300,000 ETB', True), ('500,000 ETB', False)]),
    (created_pools[0], 'Tipping-Off Prohibition in STR Cases', 'true_false',
     'It is strictly prohibited to inform a bank customer that an STR has been submitted to the Financial Intelligence Service.',
     [('True', True), ('False', False)]),
    (created_pools[1], 'Debt Service Coverage Ratio (DSCR) Formula', 'single_choice',
     'What is the formula for calculating Debt Service Coverage Ratio (DSCR)?',
     [('Net Operating Income / Total Debt Service', True), ('Total Revenue / Interest Expense', False), ('Total Assets / Total Liabilities', False)]),
    (created_pools[1], 'Collateral Haircut Requirement', 'true_false',
     'Under Bunna Bank policy, residential building collateral requires a mandatory haircut valuation discount.',
     [('True', True), ('False', False)]),
    (created_pools[2], 'Branch Vault Dual Custody Rule', 'true_false',
     'Opening the main branch currency vault requires two independent authorized key/combination holders simultaneously.',
     [('True', True), ('False', False)]),
    (created_pools[2], 'Maximum Teller Drawer Cash Limit', 'single_choice',
     'What action must a teller take immediately upon reaching maximum drawer cash threshold?',
     [('Transfer excess cash to vault custodian', True), ('Keep excess in desk drawer', False), ('Stop processing transactions', False)]),
    (created_pools[3], 'Recognizing Spear Phishing Emails', 'multiple_choice',
     'Which of the following are common indicators of a spear phishing email?',
     [('Mismatched sender domain', True), ('Urgent threats of account suspension', True), ('Official verified digital signature', False)]),
    (created_pools[3], 'Removable Media in Branch Workstations', 'true_false',
     'Plugging unauthorized personal USB flash drives into core banking teller terminals is permitted during lunch breaks.',
     [('True', False), ('False', True)]),
]

for pool, qname, qtype, qtext, ans_list in sample_questions:
    q_rec = _find('lms.question', [('name', '=', qname)])
    if not q_rec and pool:
        q_rec = env['lms.question'].create({
            'pool_id': pool.id,
            'name': qname,
            'question_type': qtype,
            'question_text': '<p>%s</p>' % qtext,
            'points': 2.0,
            'difficulty': 'medium',
        })
        seq = 10
        for atext, is_c in ans_list:
            env['lms.question.answer'].create({
                'question_id': q_rec.id,
                'answer_text': atext,
                'is_correct': is_c,
                'sequence': seq,
            })
            seq += 10
_log('Seeded Question Pools & Question Bank (Total 4 Pools, 8 Questions)')

# 6. Assessments (4 assessments)
assess_data = [
    ('AML/CFT Post-Course Final Certification Examination', created_courses[0] if created_courses else False, created_pools[0], 80.0, 20),
    ('Commercial Credit Underwriting Proficiency Exam', created_courses[1] if len(created_courses) > 1 else False, created_pools[1], 75.0, 30),
    ('Frontline Branch Customer Service Assessment', created_courses[2] if len(created_courses) > 2 else False, created_pools[2], 70.0, 15),
    ('Cyber Security Annual Defense Exam', created_courses[3] if len(created_courses) > 3 else False, created_pools[3], 80.0, 15),
]

created_exams = []
for aname, acourse, apool, ascore, adur in assess_data:
    if acourse and apool:
        exam = _find('lms.assessment', [('name', '=', aname)])
        if not exam:
            exam = env['lms.assessment'].create({
                'name': aname,
                'course_id': acourse.id,
                'assessment_type': 'post_course',
                'is_timed': True,
                'duration_minutes': adur,
                'pass_score_percentage': ascore,
                'instructions': '<p>Please answer all questions carefully before submitting.</p>',
                'max_attempts': 3,
                'cooldown_hours': 1.0,
                'use_random_pool': True,
                'pool_ids': [(4, apool.id)],
                'questions_per_session': 2,
            })
            acourse.write({'has_post_assessment': True, 'post_assessment_id': exam.id})
        created_exams.append(exam)
_log('Seeded Assessments (Total %d)' % len(created_exams))

# 7. Certificate Templates (4 templates so "Certificate Templates" menu has 4 options)
cert_tmpl_data = [
    ('Bunna Bank Standard Certificate of Achievement', 'CERTIFICATE OF ACHIEVEMENT', 'BUNNA BANK S.C. E-ACADEMY'),
    ('Executive Honors Diploma in Banking Excellence', 'EXECUTIVE HONORS DIPLOMA', 'BUNNA BANK SENIOR LEADERSHIP INSTITUTE'),
    ('National Regulatory Compliance Credential', 'COMPLIANCE CERTIFICATION', 'BUNNA BANK REGULATORY & RISK ACADEMY'),
    ('Bunna Bank Leadership Academy Certificate', 'LEADERSHIP ACADEMY DIPLOMA', 'BUNNA BANK TALENT DEVELOPMENT CENTER'),
]

for tname, head, sub in cert_tmpl_data:
    existing = _find('lms.certificate.template', [('name', '=', tname)])
    if not existing:
        env['lms.certificate.template'].create({
            'name': tname,
            'header_text': head,
            'subtitle_text': sub,
            'body_text': '<p>This certifies that <strong>${learner_name}</strong> has achieved excellence in <strong>${course_name}</strong>.</p>',
            'signatory_1_name': 'Chief Human Resources Officer',
            'signatory_1_title': 'People & Organizational Development',
            'signatory_2_name': 'Chief Executive Officer',
            'signatory_2_title': 'Bunna Bank S.C.',
        })
_log('Seeded Certificate Templates (Total 4)')

# 8. Enrollments, Candidate Exam Sessions & Issued Certificates (>= 4 records each)
enroll_records = []
target_admin_emp = admin_emp or emp_1
enroll_plan = [
    (target_admin_emp, created_courses[0], 'completed', 95.0, True),
    (target_admin_emp, created_courses[1] if len(created_courses) > 1 else created_courses[0], 'in_progress', 50.0, False),
    (emp_2, created_courses[0], 'completed', 88.0, True),
    (emp_3, created_courses[0], 'in_progress', 30.0, False),
    (emp_4, created_courses[0], 'enrolled', 0.0, False),
    (emp_2, created_courses[1] if len(created_courses) > 1 else created_courses[0], 'completed', 92.0, True),
    (emp_3, created_courses[2] if len(created_courses) > 2 else created_courses[0], 'completed', 85.0, True),
    (target_admin_emp, created_courses[3] if len(created_courses) > 3 else created_courses[0], 'in_progress', 40.0, False),
]

for emp, crs, st, score, pass_post in enroll_plan:
    if emp and crs:
        enr = _find('lms.enrollment', [('employee_id', '=', emp.id), ('course_id', '=', crs.id)])
        if not enr:
            enr = env['lms.enrollment'].create({
                'employee_id': emp.id,
                'course_id': crs.id,
                'is_mandatory': True,
                'due_date': DUE_DATE,
                'state': st,
                'enrollment_date': TODAY - timedelta(days=15),
                'completion_date': TODAY - timedelta(days=2) if st == 'completed' else False,
                'final_score_percentage': score if st == 'completed' else 0.0,
                'post_assessment_passed': pass_post,
            })
            for lp in enr.lesson_progress_ids:
                if st == 'completed':
                    lp.write({'state': 'completed', 'max_watched_seconds': 600})
                elif st == 'in_progress':
                    lp.write({'state': 'in_progress', 'max_watched_seconds': 300})
        enroll_records.append(enr)

_log('Seeded Enrollments across Employees (Total %d)' % len(enroll_records))

# Seed Candidate Exam Sessions (4 records so "Candidate Exam Sessions" is populated!)
if created_exams:
    exam_main = created_exams[0]
    session_plan = [
        (emp_1, exam_main, 95.0, True),
        (emp_2, exam_main, 88.0, True),
        (emp_3, exam_main, 60.0, False),
        (emp_4, exam_main, 100.0, True),
    ]
    for emp, ex, sc, p in session_plan:
        if emp and ex:
            sess_rec = _find('lms.exam.session', [('employee_id', '=', emp.id), ('assessment_id', '=', ex.id)])
            if not sess_rec:
                sess_rec = env['lms.exam.session'].create({
                    'employee_id': emp.id,
                    'assessment_id': ex.id,
                    'start_time': NOW - timedelta(days=3),
                    'end_time': NOW - timedelta(days=3, minutes=-15),
                    'score_percentage': sc,
                    'is_passed': p,
                    'state': 'passed' if p else 'failed',
                })
_log('Seeded Candidate Exam Sessions (Total 4)')

# Ensure Issued Certificates (At least 4 certificates so "Issued Certificates" menu has 4+ items!)
completed_enrs = env['lms.enrollment'].search([('state', '=', 'completed')], limit=6)
for enr in completed_enrs:
    if not enr.certificate_id:
        cert = env['lms.certificate'].issue_certificate(enr, enr.final_score_percentage or 90.0)
        enr.write({'certificate_id': cert.id})
_log('Verified/Issued Certificates (Total %d in DB)' % env['lms.certificate'].search_count([]))
env.cr.commit()
_log('Committed Phase 3 (LMS) changes.')

# ─────────────────────────────────────────────────────────────────────────────
# Phase 4: UNIFIED RECOGNITION & HONORS (Recognition Engine)
# ─────────────────────────────────────────────────────────────────────────────
_log('>>> Phase 4: Seeding Recognition & Gamification Data...')

months_back = [
    (TODAY.replace(day=1) - timedelta(days=90), 'kms', 'best_contributor', emp_1, 95, 'Authored Credit Risk Underwriting Policy and delivered SME Masterclass'),
    (TODAY.replace(day=1) - timedelta(days=60), 'lms', 'best_learner', emp_2, 92, 'Completed 3 mandatory banking pathways with average score of 92%'),
    (TODAY.replace(day=1) - timedelta(days=30), 'kms', 'best_contributor', emp_3, 88, 'Published high-impact Lessons Learned on Cyber Security Incident Response'),
    (TODAY.replace(day=1), 'lms', 'best_learner', emp_1, 98, 'Top scorer across bank-wide AML/CFT and Credit Analysis certifications'),
]

for pdate, src, atype, emp, pts, cit in months_back:
    if emp:
        # 1. Standalone Recognition Monthly Award
        m_start = pdate.replace(day=1)
        existing_award = _find('recognition.monthly.award', [('period_date', '=', m_start), ('award_type', '=', atype)])
        if not existing_award:
            env['recognition.monthly.award'].create({
                'period_date': m_start,
                'award_type': atype,
                'employee_id': emp.id,
                'points_total': pts,
                'average_score': float(pts) if atype == 'best_learner' else 0.0,
                'courses_completed': 2 if atype == 'best_learner' else 0,
                'badge': 'gold',
                'citation': cit,
            })

        # 2. Legacy Module awards
        if src == 'kms':
            ex_kms = _find('kms.monthly.recognition', [('period_date', '=', m_start)])
            if not ex_kms:
                env['kms.monthly.recognition'].create({
                    'period_date': m_start,
                    'employee_id': emp.id,
                    'points_total': pts,
                    'badge': 'gold',
                    'citation': cit,
                })
        else:
            ex_lms = _find('lms.monthly.scorer', [('period_date', '=', m_start)])
            if not ex_lms:
                env['lms.monthly.scorer'].create({
                    'period_date': m_start,
                    'employee_id': emp.id,
                    'average_score': float(pts),
                    'courses_completed': 2,
                    'badge': 'gold',
                    'citation': cit,
                })

_log('Seeded Monthly Recognition Champions (Total 4)')

# Polymorphic Points Ledger (8 items)
pt_data = [
    (emp_1, 'kms', 'document_publish', 'kms.document', 1, 20, 'Published Credit Risk Underwriting Policy'),
    (emp_1, 'kms', 'session_delivery', 'kms.knowledge.session', 1, 25, 'Conducted SME Masterclass on Trade Finance LC'),
    (emp_2, 'kms', 'lesson_learned', 'kms.lesson.learned', 2, 15, 'Contributed Lesson Learned on ATM Vault Balancing'),
    (emp_3, 'kms', 'accepted_answer', 'kms.forum.post', 1, 10, 'Provided accepted answer on UCP 600 transport dates'),
    (emp_1, 'lms', 'course_complete', 'lms.course', 1, 30, 'Completed AML/CFT Masterclass with 95% score'),
    (emp_2, 'lms', 'course_complete', 'lms.course', 1, 25, 'Completed AML/CFT Masterclass with 88% score'),
    (emp_3, 'lms', 'course_complete', 'lms.course', 3, 20, 'Completed Frontline Customer Service course'),
    (emp_4, 'lms', 'perfect_score', 'lms.assessment', 1, 35, 'Achieved 100% on Candidate Exam Session'),
]

admin_user = env['res.users'].browse(1)
for emp, src, act, mod, rid, pts, desc in pt_data:
    if emp:
        u = emp.user_id if emp.user_id else admin_user
        env['recognition.point'].sudo().create({
            'user_id': u.id,
            'source_module': src,
            'source_action': act,
            'source_model': mod,
            'source_res_id': rid,
            'points': pts,
            'description': desc,
            'date_earned': TODAY - timedelta(days=10),
        })
_log('Seeded Recognition Points Ledger (Total 8)')
env.cr.commit()
_log('Committed Phase 4 (Recognition) changes.')

# ─────────────────────────────────────────────────────────────────────────────
# Phase 5: KMS/LMS BRIDGE LINKAGE
# ─────────────────────────────────────────────────────────────────────────────
_log('>>> Phase 5: Linking Course Knowledge Bridge...')

c_aml = created_courses[0] if created_courses else False
lib_b3 = _find('kms.digital.library', [('name', 'ilike', 'Basel III')])
lib_nbe = _find('kms.digital.library', [('name', 'ilike', 'National Bank of Ethiopia')])
ll_cutover = _find('kms.lesson.learned', [('name', 'ilike', 'Core Banking System Cutover')])
ll_export = _find('kms.lesson.learned', [('name', 'ilike', 'Export Loan Refinancing')])

if c_aml:
    rel_lib_ids = []
    if lib_b3:
        rel_lib_ids.append(lib_b3.id)
    if lib_nbe:
        rel_lib_ids.append(lib_nbe.id)
    rel_ll_ids = []
    if ll_cutover:
        rel_ll_ids.append(ll_cutover.id)
    if ll_export:
        rel_ll_ids.append(ll_export.id)

    c_aml.write({
        'library_resource_ids': [(6, 0, rel_lib_ids)],
        'lesson_learned_ids': [(6, 0, rel_ll_ids)],
    })
    _log('Linked Course [%s] to %d Digital Library resources and %d Lessons Learned!' % (
        c_aml.name, len(rel_lib_ids), len(rel_ll_ids)
    ))
env.cr.commit()
_log('Committed Phase 5 (Bridge) changes.')

_log('========================================================================')
_log('ALL KMS & LMS DEMO DATA SEEDING COMPLETE WITH >= 4 ITEMS PER VIEW!')
_log('========================================================================')
