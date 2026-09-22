# -*- coding: utf-8 -*-
import base64
from odoo.tests.common import TransactionCase


class TestLmsPhase4Certificate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LmsCategory = cls.env['lms.category']
        cls.LmsCourse = cls.env['lms.course']
        cls.LmsEnrollment = cls.env['lms.enrollment']
        cls.LmsCertificate = cls.env['lms.certificate']

        cls.user = cls.env['res.users'].create({
            'name': 'Cert Learner',
            'login': 'cert_learner@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_learner').id])],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Cert Learner Employee',
            'user_id': cls.user.id,
        })

        cls.category = cls.LmsCategory.create({'name': 'Banking Compliance', 'code': 'COMP'})
        cls.course = cls.LmsCourse.create({
            'name': 'Certified AML Officer Course',
            'category_id': cls.category.id,
            'description': '<p>Course Syllabus and Overview</p>',
            'instructor_id': cls.employee.id,
            'pass_score_percentage': 80.0,
            'certificate_validity_months': 12,
        })
        cls.enrollment = cls.LmsEnrollment.create({
            'employee_id': cls.employee.id,
            'course_id': cls.course.id,
            'state': 'in_progress',
        })

    def test_13_certificate_pdf_generation_on_issuance(self):
        # Issue certificate for enrollment with passing score
        cert = self.LmsCertificate.issue_certificate(self.enrollment, 92.5)

        self.assertTrue(cert, 'Certificate must be created')
        self.assertEqual(cert.state, 'valid')
        self.assertEqual(cert.score_percentage, 92.5)
        self.assertTrue(cert.verification_code, 'Verification hash must be generated')

        # FR-LMS-014, NFR-LMS-004: certificate_pdf must be pre-rendered and populated
        self.assertTrue(cert.certificate_pdf, 'certificate_pdf must be populated upon issuance')
        raw_pdf = base64.b64decode(cert.certificate_pdf)
        self.assertTrue(len(raw_pdf) > 100, 'Certificate PDF must contain rendered bytes')
        self.assertTrue(raw_pdf.startswith(b'%PDF') or raw_pdf.startswith(b'<!DOCTYPE html>'),
                        'Rendered content must be a valid PDF format or rendered QWeb HTML document')
