# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install', 'eds', 'b1')
class TestEdsCourse(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['eds.course'].create({
            'name': 'AML & Compliance Certification',
            'category': 'technical_compliance',
        })
        # Try to find or create competency
        cls.competency = cls.env['competency.competency'].search([], limit=1)
        if not cls.competency:
            cls.competency = cls.env['competency.competency'].create({
                'name': 'Regulatory Compliance Knowledge',
                'code': 'COMP_REG_001',
            })

    def test_b1_duplicate_competency_mapping_raises_validation_error(self):
        """B1: Verify that mapping the same competency to a course twice raises ValidationError."""
        self.env['eds.course.competency.line'].create({
            'course_id': self.course.id,
            'competency_id': self.competency.id,
            'required_level': '3',
            'weight_pct': 100.0,
        })

        with self.assertRaises(ValidationError):
            self.env['eds.course.competency.line'].create({
                'course_id': self.course.id,
                'competency_id': self.competency.id,
                'required_level': '4',
                'weight_pct': 50.0,
            })
