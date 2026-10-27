from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds', 'budget_basis')
class TestBudgetBasis(TransactionCase):

    def test_single_switch_updates_saved_total(self):
        plan = self.env['eds.annual.plan'].sudo().create({})
        course = self.env['eds.course'].sudo().create({'name': 'Budget Basis Test Course'})
        program = self.env['eds.annual.plan.line'].sudo().create({
            'plan_id': plan.id,
            'course_id': course.id,
            'planned_participants': 4,
        })
        expense = self.env['eds.annual.plan.budget.line'].sudo().create({
            'plan_line_id': program.id,
            'name': 'Hotel',
            'unit_price': 7000,
            'is_per_employee': True,
        })
        self.assertFalse(expense.is_general)
        self.assertEqual(expense.total_amount, 28000)
        self.assertEqual(program.budget_allocated, 28000)

        expense.write({'is_per_employee': False})
        self.assertTrue(expense.is_general)
        self.assertEqual(expense.total_amount, 7000)
        self.assertEqual(program.budget_allocated, 7000)

        with self.assertRaises(ValidationError):
            expense.write({'is_per_employee': True, 'is_general': True})

    def test_unsaved_row_previews_current_participant_count(self):
        expense = self.env['eds.annual.plan.budget.line'].with_context(
            budget_planned_participants=4).new({
                'name': 'Hotel', 'unit_price': 7000,
                'is_per_employee': True, 'is_general': False,
            })
        self.assertEqual(expense.total_amount, 28000)
        expense.is_per_employee = False
        expense._onchange_is_per_employee()
        self.assertTrue(expense.is_general)
        self.assertEqual(expense.total_amount, 7000)
