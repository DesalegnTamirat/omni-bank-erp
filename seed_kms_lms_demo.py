# -*- coding: utf-8 -*-
"""
Omni-Bank ERP — KMS & LMS Demo Data Seed Script
==============================================
Usage inside Odoo Docker container:
    docker exec -i odoo19-app odoo shell -d ERP --no-http < omni-bank-erp/seed_kms_lms_demo.py

Populates:
  1. KMS Taxonomies, Governed Documents (Policies, SOPs) with PDF attachments
  2. KMS Digital Library assets (E-books, Whitepapers, External links)
  3. KMS Communities of Practice (CoPs), Capture Sessions, Lessons Learned, Mentoring
  4. KMS Subject Matter Experts (linked to competency.competency)
  5. LMS Course Categories, Courses, Sections, Lessons (Videos, Docs, Quizzes)
  6. LMS Learning Paths with branched/optional stages
  7. LMS Question Pools, Questions, and Assessments
  8. LMS Assignment Campaigns and Learner Enrollments
  9. LMS Issued Certificates (bridged to hr.training.history and hr.employee.document)
 10. KMS & LMS Monthly Gamification Recognitions
"""

import base64
import logging
from datetime import date, datetime, timedelta

_logger = logging.getLogger('seed_kms_lms_demo')
TODAY = date.today()
DUE_DATE = TODAY + timedelta(days=30)


def _log(msg):
    print('[SEED-KMS-LMS] %s' % msg)


def _find(model, domain):
    return env[model].search(domain, limit=1)


_log('Starting KMS and LMS Demo Data Seeding...')

# ─────────────────────────────────────────────────────────────────────────────
# 1. RETRIEVE EXISTING BASE DATA (EMPLOYEES, UNITS, COMPETENCIES)
# ─────────────────────────────────────────────────────────────────────────────
emp_1 = _find('hr.employee', [('name', 'ilike', 'Abebe')]) or _find('hr.employee', [('id', '>', 0)])
emp_2 = _find('hr.employee', [('name', 'ilike', 'Almaz')]) or _find('hr.employee', [('id', '!=', emp_1.id)])
emp_3 = _find('hr.employee', [('name', 'ilike', 'Biruk')]) or _find('hr.employee', [('id', 'not in', [emp_1.id, emp_2.id])])

dept_credit = _find('hr.department', [('name', 'ilike', 'Credit')]) or _find('hr.department', [])
ou_main = _find('operating.unit', [('name', 'ilike', 'Head Office')]) or _find('operating.unit', [])
comp_credit = _find('competency.competency', [('name', 'ilike', 'Credit')]) or _find('competency.competency', [])

_log('Found Base Master Data: Employees (%s, %s, %s)' % (emp_1.name if emp_1 else 'None', emp_2.name if emp_2 else 'None', emp_3.name if emp_3 else 'None'))

# ─────────────────────────────────────────────────────────────────────────────
# 2. KMS: GOVERNED DOCUMENTS (POLICIES & SOPS)
# ─────────────────────────────────────────────────────────────────────────────
cat_credit = _find('kms.category', [('code', '=', 'CAT_CREDIT')])
cat_risk = _find('kms.category', [('code', '=', 'CAT_RISK')])
cat_retail = _find('kms.category', [('code', '=', 'CAT_RETAIL')])

type_policy = _find('kms.document.type', [('code', '=', 'POL')])
type_sop = _find('kms.document.type', [('code', '=', 'SOP')])

class_conf = _find('kms.classification', [('code', '=', 'CONF')])
class_int = _find('kms.classification', [('code', '=', 'INT')])
class_sconf = _find('kms.classification', [('code', '=', 'SCONF')])

dummy_pdf_content = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R/Resources<<>>>>endobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n185\n%%EOF"
dummy_pdf_b64 = base64.b64encode(dummy_pdf_content)

doc_credit_pol = _find('kms.document', [('name', '=', 'Bunna Bank Credit Risk Assessment & Underwriting Policy')])
if not doc_credit_pol and cat_credit and type_policy and class_conf:
    doc_credit_pol = env['kms.document'].create({
        'name': 'Bunna Bank Credit Risk Assessment & Underwriting Policy',
        'category_id': cat_credit.id,
        'doc_type_id': type_policy.id,
        'classification_id': class_conf.id,
        'department_id': dept_credit.id if dept_credit else False,
        'operating_unit_id': ou_main.id if ou_main else False,
        'owner_id': emp_1.id if emp_1 else False,
        'version': '1.0',
        'state': 'approved',
        'effective_date': TODAY,
        'summary': 'Establishes institutional credit risk tolerances, Single Borrower Limits (SBL), collateral haircuts, and lending governance principles.',
        'content_text': 'Credit Underwriting Policy Bunna Bank Collateral Debt Service Coverage Ratio DSCR Loan-to-Value LTV Credit Committee Approvals',
        'require_watermark': True,
        'is_view_only': False,
        'file_data': dummy_pdf_b64,
        'file_name': 'Bunna_Credit_Underwriting_Policy_v1.0.pdf',
        'view_count': 42,
        'download_count': 15,
    })
    _log('Created KMS Governed Document: Credit Risk Underwriting Policy')

doc_remittance_sop = _find('kms.document', [('name', '=', 'Standard Operating Procedure for High-Value Cash Remittance')])
if not doc_remittance_sop and cat_retail and type_sop and class_int:
    doc_remittance_sop = env['kms.document'].create({
        'name': 'Standard Operating Procedure for High-Value Cash Remittance',
        'category_id': cat_retail.id,
        'doc_type_id': type_sop.id,
        'classification_id': class_int.id,
        'owner_id': emp_2.id if emp_2 else False,
        'version': '1.2',
        'state': 'approved',
        'effective_date': TODAY,
        'summary': 'Standardized protocol for vault balancing, cash-in-transit (CIT) handoffs, and dual-custody authorization.',
        'content_text': 'Cash Remittance Dual Custody Vault Security Armored Transport Branch Operations Teller Limits',
        'require_watermark': True,
        'file_data': dummy_pdf_b64,
        'file_name': 'SOP_Cash_Remittance_v1.2.pdf',
        'view_count': 78,
        'download_count': 23,
    })
    _log('Created KMS Governed SOP: High-Value Cash Remittance')

# ─────────────────────────────────────────────────────────────────────────────
# 3. KMS: DIGITAL LIBRARY ASSETS
# ─────────────────────────────────────────────────────────────────────────────
lib_ebook = _find('kms.digital.library', [('name', '=', 'Basel III Capital Accord and Credit Risk Stress Testing Guide')])
if not lib_ebook and cat_risk:
    lib_ebook = env['kms.digital.library'].create({
        'name': 'Basel III Capital Accord and Credit Risk Stress Testing Guide',
        'author': 'Bank for International Settlements (BIS) / NBE Advisory',
        'resource_type': 'ebook',
        'category_id': cat_risk.id,
        'publication_year': '2024',
        'is_recommended': True,
        'curator_notes': 'Essential foundational reading for all credit analysts and risk officers.',
        'file_data': dummy_pdf_b64,
        'file_name': 'Basel_III_Stress_Testing_Guide.pdf',
        'summary': 'Comprehensive textbook on risk-weighted assets (RWA), liquidity coverage ratios (LCR), and countercyclical capital buffers.',
        'view_count': 65,
        'download_count': 28,
        'rating_average': 5.0,
    })
    _log('Created KMS Digital Library Asset: Basel III Guide')

# ─────────────────────────────────────────────────────────────────────────────
# 4. KMS: COMMUNITIES OF PRACTICE (CoP) & TACIT SESSIONS
# ─────────────────────────────────────────────────────────────────────────────
cop_credit = _find('kms.cop', [('code', '=', 'COP-CREDIT')])
if not cop_credit and cat_credit and emp_1:
    cop_credit = env['kms.cop'].create({
        'name': 'Credit Risk & Lending Excellence Community of Practice',
        'code': 'COP-CREDIT',
        'category_id': cat_credit.id,
        'lead_id': emp_1.id,
        'member_ids': [(6, 0, [emp_1.id, emp_2.id, emp_3.id])] if emp_3 else [(6, 0, [emp_1.id, emp_2.id])],
        'description': '<p>Collaborative domain space for underwriters, credit analysts, and relationship managers across all districts to exchange lending insights.</p>',
        'meeting_cadence': 'monthly',
        'meeting_guidelines': 'Active participation required. Open discussions on complex credit proposals and market sector trends.',
    })
    _log('Created KMS Community of Practice: Credit Risk CoP')

# Tacit Capture Session
sess = _find('kms.knowledge.session', [('name', '=', 'SME Masterclass: Trade Finance Letters of Credit Risk Mitigation')])
if not sess and cop_credit and emp_1:
    sess = env['kms.knowledge.session'].create({
        'name': 'SME Masterclass: Trade Finance Letters of Credit Risk Mitigation',
        'cop_id': cop_credit.id,
        'session_type': 'expert_interview',
        'expert_id': emp_1.id,
        'facilitator_id': emp_2.id if emp_2 else False,
        'session_date': datetime.now() - timedelta(days=5),
        'duration_hours': 1.5,
        'summary': '<p>Captured tacit know-how regarding foreign exchange allocation prioritization and LC discrepancies.</p>',
        'key_takeaways': '<p>1. Always verify shipping bill of lading against maritime registry.<br/>2. Flag non-standard inland transport documents early.</p>',
        'state': 'completed',
    })
    _log('Created KMS Knowledge Capture Session')

# Lessons Learned
ll = _find('kms.lesson.learned', [('name', '=', 'Core Banking System Cutover: Database Transaction Timeout Mitigation')])
if not ll and cat_risk and emp_1:
    ll = env['kms.lesson.learned'].create({
        'name': 'Core Banking System Cutover: Database Transaction Timeout Mitigation',
        'category_id': cat_risk.id,
        'project_initiative': 'Core Banking Upgrade 2025/2026',
        'department_id': dept_credit.id if dept_credit else False,
        'author_id': emp_1.id,
        'severity_impact': 'high',
        'event_summary': 'During month-end high volume batch processing, connection pooling reached peak limits causing timeout.',
        'root_cause': 'Default connection pool size was configured for 100 concurrent threads instead of 500 required for branch burst traffic.',
        'key_lesson': '<p>Always tune connection pool sizes to 3x peak estimated transaction volume during major upgrade deployments.</p>',
        'mitigation_recommendation': '<p>Configured automatic dynamic worker scaling in PostgreSQL backend.</p>',
        'state': 'reviewed',
        'helpful_votes': 18,
    })
    _log('Created KMS Lesson Learned')

# Subject Matter Expert Profile
expert_1 = _find('kms.expert', [('employee_id', '=', emp_1.id)]) if emp_1 else None
if not expert_1 and emp_1:
    expert_1 = env['kms.expert'].create({
        'employee_id': emp_1.id,
        'primary_domain': 'credit',
        'expertise_summary': '<p>Over 12 years of specialized corporate underwriting, syndication, and collateral appraisal in Ethiopian banking sector.</p>',
        'certifications_held': 'CFA Charterholder, Professional Risk Manager (PRM)',
        'years_experience': 12.5,
        'availability_status': 'available',
        'competency_ids': [(4, comp_credit.id)] if comp_credit else False,
        'endorsement_count': 14,
    })
    _log('Created KMS SME Profile for %s' % emp_1.name)

# ─────────────────────────────────────────────────────────────────────────────
# 5. LMS: CATEGORIES, COURSES, SECTIONS, LESSONS
# ─────────────────────────────────────────────────────────────────────────────
lms_cat_comp = _find('lms.category', [('code', '=', 'LMS_COMP')])
lms_cat_credit = _find('lms.category', [('code', '=', 'LMS_CREDIT')])
tmpl_cert = _find('lms.certificate.template', [])

course_aml = _find('lms.course', [('name', '=', 'Anti-Money Laundering (AML/CFT) & Regulatory Compliance Masterclass')])
if not course_aml and lms_cat_comp and emp_1:
    course_aml = env['lms.course'].create({
        'name': 'Anti-Money Laundering (AML/CFT) & Regulatory Compliance Masterclass',
        'category_id': lms_cat_comp.id,
        'instructor_id': emp_1.id,
        'is_mandatory': True,
        'estimated_duration_hours': 2.0,
        'pass_score_percentage': 80.0,
        'version': '1.0',
        'state': 'published',
        'description': '<p>Comprehensive regulatory training on AML/CFT directive compliance, suspicious transaction reporting (STR), cash transaction limits (CTR), and risk scoring.</p>',
        'learning_objectives': '<p>1. Identify red-flag transactions.<br/>2. Comply with NBE directives.<br/>3. Execute KYC customer onboarding.</p>',
        'issue_certificate': True,
        'certificate_template_id': tmpl_cert.id if tmpl_cert else False,
        'certificate_validity_months': 12,
    })

    # Add Sections
    sec_1 = env['lms.course.section'].create({
        'course_id': course_aml.id,
        'name': 'Module 1: Legal Framework & Regulatory Directives',
        'sequence': 10,
    })
    sec_2 = env['lms.course.section'].create({
        'course_id': course_aml.id,
        'name': 'Module 2: Transaction Monitoring & Red Flags',
        'sequence': 20,
    })

    # Add Lessons
    env['lms.lesson'].create({
        'course_id': course_aml.id,
        'section_id': sec_1.id,
        'name': '1.1 Overview of Ethiopian AML/CFT Proclamation & Directives',
        'lesson_type': 'video',
        'video_source_type': 'file',
        'video_duration_seconds': 600,
        'min_watch_percentage': 90.0,
        'prevent_fast_forward': True,
        'sequence': 10,
        'is_mandatory': True,
        'duration_minutes': 10.0,
    })
    env['lms.lesson'].create({
        'course_id': course_aml.id,
        'section_id': sec_1.id,
        'name': '1.2 Customer Due Diligence (CDD) & Enhanced KYC Procedures',
        'lesson_type': 'document',
        'document_file': dummy_pdf_b64,
        'document_filename': 'CDD_KYC_Checklist.pdf',
        'sequence': 20,
        'is_mandatory': True,
        'duration_minutes': 15.0,
    })
    env['lms.lesson'].create({
        'course_id': course_aml.id,
        'section_id': sec_2.id,
        'name': '2.1 Detecting Suspicious Transaction Patterns & Typologies',
        'lesson_type': 'video',
        'video_source_type': 'file',
        'video_duration_seconds': 900,
        'min_watch_percentage': 90.0,
        'prevent_fast_forward': True,
        'sequence': 30,
        'is_mandatory': True,
        'duration_minutes': 15.0,
    })
    _log('Created LMS Mandatory Course: AML/CFT Masterclass with 3 Lessons')

# ─────────────────────────────────────────────────────────────────────────────
# 6. LMS: QUESTION POOLS, QUESTIONS, AND ASSESSMENTS
# ─────────────────────────────────────────────────────────────────────────────
pool_aml = _find('lms.question.pool', [('code', '=', 'POOL-AML')])
if not pool_aml:
    pool_aml = env['lms.question.pool'].create({
        'name': 'AML/CFT Examination Pool',
        'code': 'POOL-AML',
        'description': 'Questions covering regulatory directives and red flag recognition.',
    })

    # Question 1
    q1 = env['lms.question'].create({
        'pool_id': pool_aml.id,
        'name': 'Cash Transaction Reporting (CTR) Threshold',
        'question_type': 'single_choice',
        'question_text': '<p>Under National Bank of Ethiopia directives, what is the mandatory threshold for filing a Cash Transaction Report (CTR)?</p>',
        'points': 2.0,
        'difficulty': 'medium',
        'explanation': '<p>NBE mandates reporting for all cash transactions equal to or exceeding 300,000 ETB for individuals.</p>',
    })
    env['lms.question.answer'].create({'question_id': q1.id, 'answer_text': '100,000 ETB', 'is_correct': False, 'sequence': 10})
    env['lms.question.answer'].create({'question_id': q1.id, 'answer_text': '300,000 ETB', 'is_correct': True, 'sequence': 20})
    env['lms.question.answer'].create({'question_id': q1.id, 'answer_text': '500,000 ETB', 'is_correct': False, 'sequence': 30})
    env['lms.question.answer'].create({'question_id': q1.id, 'answer_text': '1,000,000 ETB', 'is_correct': False, 'sequence': 40})

    # Question 2
    q2 = env['lms.question'].create({
        'pool_id': pool_aml.id,
        'name': 'Tipping Off Prohibition',
        'question_type': 'true_false',
        'question_text': '<p>It is legally prohibited to inform a bank customer that a Suspicious Transaction Report (STR) has been filed regarding their account.</p>',
        'points': 2.0,
        'difficulty': 'easy',
        'explanation': '<p>Tipping off is a criminal offense under financial intelligence anti-money laundering laws.</p>',
    })
    env['lms.question.answer'].create({'question_id': q2.id, 'answer_text': 'True', 'is_correct': True, 'sequence': 10})
    env['lms.question.answer'].create({'question_id': q2.id, 'answer_text': 'False', 'is_correct': False, 'sequence': 20})
    _log('Created LMS Question Bank for AML/CFT')

# Create Assessment
exam_aml = _find('lms.assessment', [('name', '=', 'AML/CFT Post-Course Final Certification Examination')])
if not exam_aml and course_aml and pool_aml:
    exam_aml = env['lms.assessment'].create({
        'name': 'AML/CFT Post-Course Final Certification Examination',
        'course_id': course_aml.id,
        'assessment_type': 'post_course',
        'is_timed': True,
        'duration_minutes': 20,
        'pass_score_percentage': 80.0,
        'max_attempts': 3,
        'cooldown_hours': 1.0,
        'use_random_pool': True,
        'pool_ids': [(4, pool_aml.id)],
        'questions_per_session': 2,
        'instructions': '<p>You have 20 minutes to complete this examination. A score of at least 80% is required to earn your certification.</p>',
    })
    course_aml.write({
        'has_post_assessment': True,
        'post_assessment_id': exam_aml.id,
    })
    _log('Created LMS Assessment and linked to AML/CFT Course')

# ─────────────────────────────────────────────────────────────────────────────
# 7. LMS: LEARNING PATHS (WITH BRANCHED / OPTIONAL STAGES)
# ─────────────────────────────────────────────────────────────────────────────
path_branch_mgr = _find('lms.learning.path', [('code', '=', 'PATH-BR-MGR')])
if not path_branch_mgr and course_aml:
    path_branch_mgr = env['lms.learning.path'].create({
        'name': 'Branch Operations Leadership & Compliance Path',
        'code': 'PATH-BR-MGR',
        'category_id': lms_cat_comp.id if lms_cat_comp else False,
        'description': '<p>Mandatory professional pathway for all incoming and acting branch managers and customer service managers.</p>',
    })
    # Stage 1: Mandatory AML/CFT
    env['lms.learning.path.course'].create({
        'path_id': path_branch_mgr.id,
        'sequence': 10,
        'course_id': course_aml.id,
        'is_optional_branch': False,
        'stage_notes': 'Stage 1: Core regulatory prerequisite for all branch staff.',
    })
    _log('Created LMS Learning Path with Stages')

# ─────────────────────────────────────────────────────────────────────────────
# 8. LMS: ENROLLMENTS & ISSUED CERTIFICATES
# ─────────────────────────────────────────────────────────────────────────────
enroll_1 = _find('lms.enrollment', [('employee_id', '=', emp_1.id), ('course_id', '=', course_aml.id)]) if (emp_1 and course_aml) else None
if not enroll_1 and emp_1 and course_aml:
    enroll_1 = env['lms.enrollment'].create({
        'employee_id': emp_1.id,
        'course_id': course_aml.id,
        'is_mandatory': True,
        'due_date': DUE_DATE,
        'state': 'completed',
        'enrollment_date': TODAY - timedelta(days=7),
        'completion_date': TODAY,
        'final_score_percentage': 95.0,
        'post_assessment_passed': True,
    })
    # Mark lessons completed
    for lp in enroll_1.lesson_progress_ids:
        lp.write({'state': 'completed', 'max_watched_seconds': 900})

    # Issue Certificate (FR-LMS-018 to FR-LMS-022)
    cert_1 = env['lms.certificate'].issue_certificate(enroll_1, 95.0)
    enroll_1.write({'certificate_id': cert_1.id})
    _log('Created LMS Completed Enrollment & Issued Certificate for %s' % emp_1.name)

# In-progress learner 2
enroll_2 = _find('lms.enrollment', [('employee_id', '=', emp_2.id), ('course_id', '=', course_aml.id)]) if (emp_2 and course_aml) else None
if not enroll_2 and emp_2 and course_aml:
    enroll_2 = env['lms.enrollment'].create({
        'employee_id': emp_2.id,
        'course_id': course_aml.id,
        'is_mandatory': True,
        'due_date': DUE_DATE,
        'state': 'in_progress',
        'enrollment_date': TODAY - timedelta(days=2),
    })
    # Update progress on first lesson
    if enroll_2.lesson_progress_ids:
        enroll_2.lesson_progress_ids[0].write({'state': 'completed', 'max_watched_seconds': 600})
    _log('Created LMS In-Progress Enrollment for %s' % emp_2.name)

# ─────────────────────────────────────────────────────────────────────────────
# 9. MONTHLY GAMIFICATION & RECOGNITION AWARDS
# ─────────────────────────────────────────────────────────────────────────────
# Best Contributor of the Month (KMS)
rec_kms = _find('kms.monthly.recognition', [('employee_id', '=', emp_1.id)]) if emp_1 else None
if not rec_kms and emp_1:
    env['kms.monthly.recognition'].create({
        'period_date': TODAY.replace(day=1),
        'employee_id': emp_1.id,
        'points_total': 85,
        'badge': 'gold',
        'citation': 'Recognized as Bunna Bank Best Contributor of the Month for authoring the Credit Underwriting Policy and delivering high-impact masterclasses.',
    })
    _log('Created KMS Best Contributor of the Month recognition')

# Best Scorer of the Month (LMS)
rec_lms = _find('lms.monthly.scorer', [('employee_id', '=', emp_1.id)]) if emp_1 else None
if not rec_lms and emp_1:
    env['lms.monthly.scorer'].create({
        'period_date': TODAY.replace(day=1),
        'employee_id': emp_1.id,
        'average_score': 95.0,
        'courses_completed': 1,
        'badge': 'gold',
        'citation': 'Awarded LMS Best Scorer of the Month for achieving 95% on the AML/CFT masterclass exam on first attempt.',
    })
    _log('Created LMS Best Scorer of the Month recognition')

_log('KMS & LMS Demo Data Seeding Completed Successfully!')
