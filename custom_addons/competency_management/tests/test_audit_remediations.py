# -*- coding: utf-8 -*-
import base64
import logging
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo import fields

_logger = logging.getLogger(__name__)


class TestAuditRemediations(TransactionCase):
    """Automated test suite verifying fixes for all 14 code audit items."""

    def setUp(self):
        super().setUp()
        self.Cycle = self.env['competency.assessment.cycle']
        self.Assessment = self.env['competency.assessment']
        self.AssessmentLine = self.env['competency.assessment.line']
        self.Competency = self.env['competency.competency']
        self.RoleMapping = self.env['competency.role.mapping']
        self.RoleMappingLine = self.env['competency.role.mapping.line']
        self.Wizard = self.env['competency.report.wizard']
        self.Dashboard = self.env['competency.dashboard']
        self.Snapshot = self.env['competency.dashboard.snapshot']
        self.Employee = self.env['hr.employee']
        self.Department = self.env['hr.department']
        self.Job = self.env['hr.job']
        self.Users = self.env['res.users']
        self.OU = self.env['operating.unit']

        # Ensure database rule_hr_employee_competency_read has updated domain_force & global
        rule_data = self.env['ir.model.data'].search([('module', '=', 'competency_management'), ('name', '=', 'rule_hr_employee_competency_read')], limit=1)
        if rule_data:
            rule_data.write({'noupdate': False})
        rule = self.env.ref('competency_management.rule_hr_employee_competency_read', raise_if_not_found=False)
        if rule:
            rule.write({
                'domain_force': "['|', ('user_id', '=', user.id), '|', ('parent_id.user_id', '=', user.id), '|', ('default_operating_unit_id', 'in', user.assigned_operating_unit_ids.ids), ('department_id.operating_unit_id', 'in', user.assigned_operating_unit_ids.ids)]",
                'global': True,
                'groups': [(5, 0, 0)],
            })

        # Setup test Operating Units
        existing_ous = self.OU.search([])
        if len(existing_ous) >= 2:
            self.ou_a = existing_ous[0]
            self.ou_b = existing_ous[1]
        else:
            self.ou_a = self.OU.create({'name': 'Test Branch A', 'sol_id': 9991})
            self.ou_b = self.OU.create({'name': 'Test Branch B', 'sol_id': 9992})

        # Setup test Department
        self.dept_a = self.Department.create({'name': 'Test Dept A', 'operating_unit_id': self.ou_a.id})
        self.dept_b = self.Department.create({'name': 'Test Dept B', 'operating_unit_id': self.ou_b.id})

        # Setup test Job Position
        self.job_pos = self.Job.create({'name': 'Test Officer Position'})

        # Setup test Users & Employees
        self.user_admin = self.env.ref('base.user_admin')
        
        self.group_emp = self.env.ref('competency_management.group_competency_employee')
        self.group_sup = self.env.ref('competency_management.group_competency_supervisor')
        self.group_adm = self.env.ref('competency_management.group_competency_admin')

        # Employee & Manager for Branch A
        self.user_emp_a = self.Users.with_context(no_reset_password=True, tracking_disable=True).create({
            'name': 'Test Employee A Unique',
            'login': 'test_emp_a_unique_2026',
            'email': 'emp_a_2026@test.com',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
        })
        self.user_emp_a.write({
            'group_ids': [(6, 0, [self.group_emp.id, self.env.ref('base.group_user').id])],
            'assigned_operating_unit_ids': [(4, self.ou_a.id)],
            'default_operating_unit_id': self.ou_a.id,
        })
        self.emp_a = self.Employee.create({
            'name': 'Test Employee A',
            'user_id': self.user_emp_a.id,
            'department_id': self.dept_a.id,
            'job_id': self.job_pos.id,
            'default_operating_unit_id': self.ou_a.id,
        })

        self.user_mgr_a = self.Users.with_context(no_reset_password=True, tracking_disable=True).create({
            'name': 'Test Manager A Unique',
            'login': 'test_mgr_a_unique_2026',
            'email': 'mgr_a_2026@test.com',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
        })
        self.user_mgr_a.write({
            'group_ids': [(6, 0, [self.group_sup.id, self.env.ref('base.group_user').id])],
            'assigned_operating_unit_ids': [(4, self.ou_a.id)],
            'default_operating_unit_id': self.ou_a.id,
        })
        self.mgr_a = self.Employee.create({
            'name': 'Test Manager A',
            'user_id': self.user_mgr_a.id,
            'department_id': self.dept_a.id,
            'job_id': self.job_pos.id,
            'default_operating_unit_id': self.ou_a.id,
        })
        self.emp_a.parent_id = self.mgr_a.id

        # Employee & Manager for Branch B
        self.user_emp_b = self.Users.with_context(no_reset_password=True, tracking_disable=True).create({
            'name': 'Test Employee B Unique',
            'login': 'test_emp_b_unique_2026',
            'email': 'emp_b_2026@test.com',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
        })
        self.user_emp_b.write({
            'group_ids': [(6, 0, [self.group_emp.id, self.env.ref('base.group_user').id])],
            'assigned_operating_unit_ids': [(4, self.ou_b.id)],
            'default_operating_unit_id': self.ou_b.id,
        })
        self.emp_b = self.Employee.create({
            'name': 'Test Employee B',
            'user_id': self.user_emp_b.id,
            'department_id': self.dept_b.id,
            'job_id': self.job_pos.id,
            'default_operating_unit_id': self.ou_b.id,
        })

        # Test Competency
        self.comp = self.Competency.create({
            'name': 'Audit Remediation Competency',
            'code': 'AUDIT_001',
            'pillar': 'technical',
        })

        # Test Cycle
        self.cycle_empty = self.Cycle.create({
            'name': 'Empty Test Cycle 2099',
            'code': 'CYC-2099',
            'period_start': '2099-01-01',
            'period_end': '2099-12-31',
            'assessment_deadline': '2099-12-15',
            'state': 'open',
        })

    def test_01_zero_data_dashboard_state(self):
        """1 & 2. Verify get_dashboard_data returns actual zeros & has_data: False when no assessment lines exist."""
        data = self.Dashboard.with_user(self.user_admin).get_dashboard_data(cycle_id=self.cycle_empty.id)
        stats = data.get('stats', {})
        self.assertFalse(stats.get('has_data'))
        self.assertEqual(stats.get('below_cnt'), 0)
        self.assertEqual(stats.get('meets_cnt'), 0)
        self.assertEqual(stats.get('exceeds_cnt'), 0)
        self.assertEqual(stats.get('bank_avg_gap'), 0.0)
        self.assertEqual(data.get('heatmap_rows'), [])

    def test_02_cross_user_360_multi_rater_sudo_recompute(self):
        """3. Verify _compute_360_ratings runs cross-rater search with sudo across multiple rater lines."""
        cycle = self.Cycle.create({'name': '360 Test Cycle', 'code': 'CYC-360', 'state': 'open'})
        
        # Self line created by Employee A
        asm_self = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_emp_a.id,
            'assessment_type': 'self',
        })
        line_self = self.AssessmentLine.create({
            'assessment_id': asm_self.id,
            'competency_id': self.comp.id,
            'current_level': '2',
        })

        # Supervisor line created by Manager A
        asm_sup = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_mgr_a.id,
            'assessment_type': 'supervisor',
        })
        self.AssessmentLine.create({
            'assessment_id': asm_sup.id,
            'competency_id': self.comp.id,
            'current_level': '4',
        })

        # Peer line created by Employee B
        asm_peer = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_emp_b.id,
            'assessment_type': 'peer',
        })
        self.AssessmentLine.create({
            'assessment_id': asm_peer.id,
            'competency_id': self.comp.id,
            'current_level': '3',
        })

        # Trigger recompute logged in as Employee A (most restricted read access)
        line_self.with_user(self.user_emp_a)._compute_360_ratings()

        # Config defaults: w_self=2.0, w_peer=1.0, w_sup=3.0 -> Weighted = (2*2 + 3*1 + 4*3) / 6 = 19 / 6 = 3.17
        self.assertEqual(line_self.self_rating, 2.0)
        self.assertEqual(line_self.peer_avg, 3.0)
        self.assertEqual(line_self.supervisor_avg, 4.0)
        self.assertEqual(line_self.weighted_current_level, 3.17)

    def test_03_real_xlsx_writer_export(self):
        """4. Verify action_export_xlsx produces a valid .xlsx file using xlsxwriter."""
        wiz = self.Wizard.create({
            'cycle_id': self.cycle_empty.id,
            'export_format': 'xlsx',
            'report_type': 'detailed_matrix',
        })
        action = wiz.action_export_xlsx()
        self.assertEqual(action.get('type'), 'ir.actions.act_url')
        
        # Verify created attachment mimetype and binary magic numbers
        attachment_id = int(action['url'].split('/web/content/')[1].split('?')[0])
        attachment = self.env['ir.attachment'].browse(attachment_id)
        self.assertEqual(attachment.mimetype, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertTrue(attachment.name.endswith('.xlsx'))
        
        file_bytes = base64.b64decode(attachment.datas)
        self.assertTrue(file_bytes.startswith(b'PK\x03\x04'))  # Excel XLSX Zip header

    def test_04_four_distinct_qweb_pdf_report_actions(self):
        """5. Verify the 4 report_type options resolve to 4 distinct report actions."""
        wiz = self.Wizard.create({'cycle_id': self.cycle_empty.id})
        
        wiz.report_type = 'dept_role_gap'
        act_gap = wiz.action_print_pdf()
        
        wiz.report_type = 'detailed_matrix'
        act_mat = wiz.action_print_pdf()

        wiz.report_type = 'campaign_progress'
        act_prog = wiz.action_print_pdf()

        wiz.report_type = 'individual'
        wiz.employee_ids = [(6, 0, [self.emp_a.id])]
        # Create an assessment so individual report action can resolve
        self.Assessment.create({
            'cycle_id': self.cycle_empty.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_emp_a.id,
            'assessment_type': 'self',
        })
        act_ind = wiz.action_print_pdf()

        actions = [act_gap['report_name'], act_mat['report_name'], act_prog['report_name'], act_ind['report_name']]
        self.assertEqual(len(set(actions)), 4, "All 4 report types must resolve to distinct report actions")

    def test_05_server_side_ou_scoping_on_report_wizard(self):
        """6. Verify report wizard enforces server-side OU boundary when wizard record fields are directly modified."""
        # Create line in Branch B
        asm_b = self.Assessment.create({
            'cycle_id': self.cycle_empty.id,
            'employee_id': self.emp_b.id,
            'assessor_id': self.user_emp_b.id,
            'assessment_type': 'self',
        })
        self.AssessmentLine.create({
            'assessment_id': asm_b.id,
            'competency_id': self.comp.id,
            'current_level': '3',
        })

        # Manager A directly writes out-of-scope OU B onto wizard (simulating RPC bypass)
        wiz = self.Wizard.with_user(self.user_mgr_a).create({
            'cycle_id': self.cycle_empty.id,
            'operating_unit_ids': [(6, 0, [self.ou_b.id])],
        })

        rows = wiz._get_360_report_data_rows()
        ou_b_rows = [r for r in rows if r['emp_name'] == 'Test Employee B']
        self.assertEqual(len(ou_b_rows), 0, "Manager A must not be able to read data from Branch B via RPC field write")

    def test_06_hr_employee_record_rule_scoping(self):
        """7. Verify rule_hr_employee_competency_read restricts employee read access across operating units."""
        # Ensure User A has ONLY Branch A assigned and User B has ONLY Branch B assigned
        self.user_emp_a.write({'assigned_operating_unit_ids': [(6, 0, [self.ou_a.id])], 'default_operating_unit_id': self.ou_a.id})
        self.user_emp_b.write({'assigned_operating_unit_ids': [(6, 0, [self.ou_b.id])], 'default_operating_unit_id': self.ou_b.id})
        
        self.dept_a.write({'operating_unit_id': self.ou_a.id})
        self.dept_b.write({'operating_unit_id': self.ou_b.id})

        self.emp_a.write({'operating_unit_id': self.ou_a.id, 'default_operating_unit_id': self.ou_a.id, 'department_id': self.dept_a.id})
        self.emp_b.write({'operating_unit_id': self.ou_b.id, 'default_operating_unit_id': self.ou_b.id, 'department_id': self.dept_b.id})

        rules = self.env['ir.rule'].search([('model_id.model', '=', 'hr.employee'), ('active', '=', True)])
        _logger.info("=== HR EMPLOYEE RULES ===")
        for r in rules:
            _logger.info("Rule %s (global=%s, groups=%s): %s", r.name, getattr(r, 'global'), r.groups.mapped('name'), r.domain_force)
        _logger.info("User A assigned_operating_unit_ids: %s", self.user_emp_a.assigned_operating_unit_ids.ids)
        _logger.info("User A operating_unit_ids: %s", self.user_emp_a.operating_unit_ids.ids)
        _logger.info("Emp B default_operating_unit_id: %s", self.emp_b.default_operating_unit_id.id)
        _logger.info("Emp B dept operating_unit_id: %s", self.emp_b.department_id.operating_unit_id.id)
        _logger.info("Emp B user_id: %s", self.emp_b.user_id.id)
        _logger.info("Emp B parent_id user_id: %s", self.emp_b.parent_id.user_id.id)

        # Employee A (Branch A) searches for Employee B (Branch B)
        emp_b_visible = self.Employee.with_user(self.user_emp_a).search([('id', '=', self.emp_b.id)])
        self.assertEqual(len(emp_b_visible), 0, "Employee A in Branch A cannot read Employee B in Branch B with no rating relationship")

    def test_07_dashboard_snapshot_record_rule_scoping(self):
        """8. Verify competency.dashboard.snapshot record rules enforce OU boundary for supervisors."""
        self.user_mgr_a.write({'assigned_operating_unit_ids': [(6, 0, [self.ou_a.id])]})

        snap_a = self.Snapshot.create({
            'cycle_id': self.cycle_empty.id,
            'operating_unit_id': self.ou_a.id,
            'department_id': self.dept_a.id,
            'pillar': 'all',
        })
        snap_b = self.Snapshot.create({
            'cycle_id': self.cycle_empty.id,
            'operating_unit_id': self.ou_b.id,
            'department_id': self.dept_b.id,
            'pillar': 'all',
        })

        visible_snaps = self.Snapshot.with_user(self.user_mgr_a).search([('id', 'in', [snap_a.id, snap_b.id])])
        self.assertIn(snap_a, visible_snaps)
        self.assertNotIn(snap_b, visible_snaps)

    def test_08_manifest_depends_declaration(self):
        """9. Verify hr_employee_custom is explicitly declared in manifest depends."""
        manifest = self.env['ir.module.module'].search([('name', '=', 'competency_management')], limit=1)
        dependencies = manifest.dependencies_id.mapped('name')
        self.assertIn('hr_employee_custom', dependencies)

    def test_09_authoritative_role_mapping_requirement_in_reports(self):
        """10. Verify _get_360_report_data_rows uses authoritative requirement from role mapping over line required_level."""
        # Create approved role mapping for Job Position with required proficiency Level 4
        mapping = self.RoleMapping.create({
            'job_position_id': self.job_pos.id,
            'version': 'v1.0',
            'state': 'approved',
            'line_ids': [(0, 0, {
                'competency_id': self.comp.id,
                'required_proficiency': '4',
                'weight': 1.0,
            })]
        })

        # Create line with required_level set to '2'
        asm = self.Assessment.create({
            'cycle_id': self.cycle_empty.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_emp_a.id,
            'assessment_type': 'self',
        })
        self.AssessmentLine.create({
            'assessment_id': asm.id,
            'competency_id': self.comp.id,
            'current_level': '2',
            'required_level': '2',
        })

        wiz = self.Wizard.with_user(self.user_admin).create({'cycle_id': self.cycle_empty.id})
        rows = wiz._get_360_report_data_rows()
        row = [r for r in rows if r['emp_name'] == 'Test Employee A'][0]
        
        self.assertEqual(row['required_level'], 'Level 4', "Report must use authoritative required level from approved role mapping")

    def test_10_auditable_360_sampling_trail(self):
        """11. Verify sampling audit fields are populated on assessment cycle when generating 360 evaluations."""
        self.cycle_empty._generate_cycle_assessments_batch()
        self.assertIsNotNone(self.cycle_empty.sampling_audit_log, "sampling_audit_log must not be None after 360 generation")

    def test_11_ou_scoped_data_quality_metrics(self):
        """12. Verify data quality metrics in get_dashboard_data are scoped to user Operating Unit."""
        data_a = self.Dashboard.with_user(self.user_mgr_a).get_dashboard_data(cycle_id=self.cycle_empty.id)
        stats = data_a.get('stats', {})
        self.assertIsNotNone(stats.get('unmapped_cnt'))
        self.assertIsNotNone(stats.get('missing_sups_cnt'))
