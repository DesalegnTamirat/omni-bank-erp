# -*- coding: utf-8 -*-
from datetime import date
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install', 'eds')
class TestEdsTnaExclusion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.department = cls.env['hr.department'].create({'name': 'Test Branch Operations'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Dawit Lemma',
            'department_id': cls.department.id,
        })
        cls.cycle = cls.env['eds.tna.cycle'].create({
            'name': 'TNA Cycle 2026/2027 Test Exclusion',
            'year': '2026',
            'state': 'collecting',
        })
        cls.entry = cls.env['eds.tna.entry'].create({
            'cycle_id': cls.cycle.id,
            'employee_id': cls.employee.id,
            'proposed_program': 'Core Banking System Printer Troubleshooting',
            'justification': 'Printer jams frequently in branch hall.',
            'urgency': 'medium',
            'delivery_mode': 'classroom',
            'state': 'submitted',
        })

    def test_action_exclude_opens_wizard_when_reason_empty(self):
        """Calling action_exclude on an entry without reason returns the wizard action."""
        action = self.entry.action_exclude()
        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        self.assertEqual(action.get('res_model'), 'eds.tna.exclude.wizard')
        self.assertEqual(action.get('context', {}).get('default_entry_id'), self.entry.id)

    def test_wizard_exclusion_success(self):
        """Confirming the wizard marks entry as excluded with category and reason."""
        wizard = self.env['eds.tna.exclude.wizard'].create({
            'entry_id': self.entry.id,
            'exclusion_type': 'system',
            'excluded_reason': 'Hardware/printer maintenance is an IT Helpdesk task, not a training need.',
        })
        wizard.action_confirm_exclusion()
        self.assertEqual(self.entry.state, 'excluded')
        self.assertEqual(self.entry.exclusion_type, 'system')
        self.assertIn('IT Helpdesk task', self.entry.excluded_reason)

    def test_wizard_requires_justification(self):
        """Wizard rejects blank justification."""
        wizard = self.env['eds.tna.exclude.wizard'].create({
            'entry_id': self.entry.id,
            'exclusion_type': 'process',
            'excluded_reason': '   ',
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_exclusion()

    def test_action_restore_from_exclusion(self):
        """Restoring an excluded need brings it back to submitted/validated and resets exclusion metadata."""
        self.entry.write({
            'state': 'excluded',
            'exclusion_type': 'system',
            'excluded_reason': 'System issue',
            'is_duplicate': True,
        })
        self.entry.action_restore_from_exclusion()
        self.assertEqual(self.entry.state, 'submitted')
        self.assertFalse(self.entry.exclusion_type)
        self.assertFalse(self.entry.excluded_reason)
        self.assertFalse(self.entry.is_duplicate)

    def test_action_clear_screening_flags(self):
        """Clearing screening flags keeps the entry active and unsets duplicate/exclusion flags."""
        self.entry.write({
            'is_duplicate': True,
            'exclusion_type': 'process',
        })
        self.entry.action_clear_screening_flags()
        self.assertFalse(self.entry.is_duplicate)
        self.assertFalse(self.entry.exclusion_type)

    def test_consolidation_unified_flagged_entries(self):
        """Consolidation aggregates flagged duplicates, non-training, and excluded items into flagged_entry_ids without duplication."""
        consolidation = self.env['eds.tna.consolidation'].create({
            'cycle_id': self.cycle.id,
        })
        self.entry.write({'consolidation_id': consolidation.id, 'is_duplicate': True, 'exclusion_type': 'duplicate'})

        emp2 = self.env['hr.employee'].create({'name': 'Tadesse Bekele', 'department_id': self.department.id})
        emp3 = self.env['hr.employee'].create({'name': 'Sara Yohannes', 'department_id': self.department.id})

        second_entry = self.env['eds.tna.entry'].create({
            'cycle_id': self.cycle.id,
            'employee_id': emp2.id,
            'proposed_program': 'Process Improvement',
            'justification': 'Operational workflow review needed.',
            'urgency': 'high',
            'delivery_mode': 'classroom',
            'state': 'excluded',
            'exclusion_type': 'process',
            'excluded_reason': 'Operational policy change.',
            'consolidation_id': consolidation.id,
        })

        third_entry = self.env['eds.tna.entry'].create({
            'cycle_id': self.cycle.id,
            'employee_id': emp3.id,
            'proposed_program': 'Valid Excel Training',
            'justification': 'Needed for quarterly financial reports.',
            'urgency': 'medium',
            'delivery_mode': 'classroom',
            'state': 'submitted',
            'consolidation_id': consolidation.id,
        })

        consolidation._compute_counts()
        consolidation._compute_review_subsets()

        self.assertEqual(consolidation.entry_count, 3)
        self.assertEqual(consolidation.flagged_count, 2)
        self.assertEqual(len(consolidation.flagged_entry_ids), 2)
        self.assertIn(self.entry, consolidation.flagged_entry_ids)
        self.assertIn(second_entry, consolidation.flagged_entry_ids)
        self.assertNotIn(third_entry, consolidation.flagged_entry_ids)

        # Test stat actions
        action_all = consolidation.action_view_all_entries()
        self.assertEqual(action_all['res_model'], 'eds.tna.entry')
        action_flagged = consolidation.action_view_flagged_entries()
        self.assertEqual(action_flagged['res_model'], 'eds.tna.entry')

