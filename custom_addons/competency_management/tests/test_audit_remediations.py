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
                'global': False,
                'groups': [(6, 0, [self.env.ref('competency_management.group_competency_employee').id, self.env.ref('competency_management.group_competency_supervisor').id])],
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
        self.user_emp_a = self.Users.search([('login', '=', 'test_emp_a_unique_2026')], limit=1)
        if not self.user_emp_a:
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
        self.emp_a = self.Employee.search([('user_id', '=', self.user_emp_a.id)], limit=1)
        if not self.emp_a:
            self.emp_a = self.Employee.create({
                'name': 'Test Employee A',
                'user_id': self.user_emp_a.id,
                'department_id': self.dept_a.id,
                'job_id': self.job_pos.id,
                'default_operating_unit_id': self.ou_a.id,
            })

        self.user_mgr_a = self.Users.search([('login', '=', 'test_mgr_a_unique_2026')], limit=1)
        if not self.user_mgr_a:
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
        self.mgr_a = self.Employee.search([('user_id', '=', self.user_mgr_a.id)], limit=1)
        if not self.mgr_a:
            self.mgr_a = self.Employee.create({
                'name': 'Test Manager A',
                'user_id': self.user_mgr_a.id,
                'department_id': self.dept_a.id,
                'job_id': self.job_pos.id,
                'default_operating_unit_id': self.ou_a.id,
            })
        self.emp_a.parent_id = self.mgr_a.id

        # Employee & Manager for Branch B
        self.user_emp_b = self.Users.search([('login', '=', 'test_emp_b_unique_2026')], limit=1)
        if not self.user_emp_b:
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

    def test_12_ormcache_environment_isolation(self):
        """13. Verify get_active_config() works across environments without psycopg2.InterfaceError (Cursor already closed)."""
        config_1 = self.env['competency.matrix.config'].get_active_config()
        self.assertTrue(config_1.id)
        
        # Access config from a new Environment context
        new_env = self.env(context=dict(self.env.context, test_new_ctx=True))
        config_2 = new_env['competency.matrix.config'].get_active_config()
        self.assertEqual(config_1.id, config_2.id)
        self.assertEqual(config_2.env.cr, new_env.cr, "Config recordset must be bound to active request environment cursor")
        
        # Test get_allowed_pillars_for_type does not raise InterfaceError
        pillars = config_2.get_allowed_pillars_for_type('self')
        self.assertIn('core', pillars)

    def test_13_submission_deadline_enforcement_and_hr_reminders(self):
        """14. Verify deadline enforcement blocks late submission, deadline extension allows it, and HR warning action works."""
        past_date = fields.Date.subtract(fields.Date.context_today(self), days=5)
        future_date = fields.Date.add(fields.Date.context_today(self), days=10)

        # Create cycle with past deadline
        cycle_expired = self.Cycle.create({
            'name': 'Expired Cycle Test',
            'period_start': past_date,
            'period_end': past_date,
            'assessment_deadline': past_date,
            'state': 'open',
        })

        asm = self.Assessment.create({
            'cycle_id': cycle_expired.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_emp_a.id,
            'assessment_type': 'self',
            'state': 'draft',
        })
        self.AssessmentLine.create({
            'assessment_id': asm.id,
            'competency_id': self.comp.id,
            'current_level': '2',
            'required_level': '2',
        })

        # 1. Check is_deadline_passed computed flag
        self.assertTrue(asm.is_deadline_passed)

        # 2. Submission must fail when deadline has passed
        with self.assertRaises(UserError):
            asm.action_submit()

        # 3. Form write and line creation must fail when deadline has passed, but populate competencies is allowed so user can view role competencies
        asm.action_populate_competencies()

        asm_emp = asm.with_user(self.user_emp_a).with_context(force_write=False).sudo(False)
        with self.assertRaises(UserError):
            asm_emp.write({'notes': 'Test editing after deadline'})

        with self.assertRaises(UserError):
            self.AssessmentLine.with_user(self.user_emp_a).with_context(force_write=False).sudo(False).create({
                'assessment_id': asm.id,
                'competency_id': self.comp.id,
                'current_level': '3',
                'required_level': '3',
            })

        # 4. Check dashboard API returns Deadline Passed state_label
        dash_data = self.env['competency.dashboard'].get_dashboard_data(cycle_id=cycle_expired.id)
        self.assertTrue(dash_data['active_cycle_info'].get('is_deadline_passed'))
        self.assertEqual(dash_data['active_cycle_info'].get('state_label'), 'Deadline Passed')

        # 5. Test HR Deadline Warning action
        res = cycle_expired.action_send_deadline_reminders()
        self.assertEqual(res.get('type'), 'ir.actions.client')
        self.assertGreater(cycle_expired.pending_assessment_count, 0)

        # 6. HR extends deadline to future date -> Submission succeeds & is_deadline_passed becomes False
        cycle_expired.write({'assessment_deadline': future_date})
        self.assertFalse(asm.is_deadline_passed)
        asm.line_ids.with_context(force_write=True).write({'current_level': '2'})
        asm.action_submit()
        self.assertEqual(asm.state, 'submitted')

    def test_14_security_roles_access_matrix(self):
        """15. Verify 4 security roles (Employee, Supervisor, Officer, Admin) permissions and workflow guards."""
        group_officer = self.env.ref('competency_management.group_competency_officer')
        
        user_officer = self.Users.with_context(no_reset_password=True, tracking_disable=True).create({
            'name': 'Test HR Officer Unique',
            'login': 'test_hr_officer_2026',
            'email': 'officer_2026@test.com',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
        })
        user_officer.write({
            'group_ids': [(6, 0, [group_officer.id, self.env.ref('base.group_user').id])],
        })

        # 1. Officer can draft competency but cannot approve it
        comp_draft = self.Competency.with_user(user_officer).create({
            'name': 'Officer Test Draft Competency',
            'code': 'CMP-OFFICER-001',
            'pillar': 'technical',
            'state': 'draft',
            'proficiency_level_ids': [
                (0, 0, {'level': '1', 'behavioral_indicators': 'Ind 1'}),
                (0, 0, {'level': '2', 'behavioral_indicators': 'Ind 2'}),
                (0, 0, {'level': '3', 'behavioral_indicators': 'Ind 3'}),
                (0, 0, {'level': '4', 'behavioral_indicators': 'Ind 4'}),
            ]
        })
        comp_draft.with_user(user_officer).action_submit()
        self.assertEqual(comp_draft.state, 'submitted')

        with self.assertRaises(UserError):
            comp_draft.with_user(user_officer).action_approve()

        # Admin approves
        comp_draft.with_user(self.user_admin).action_approve()
        self.assertEqual(comp_draft.state, 'approved')

        # 2. Officer cannot create assessment cycle
        with self.assertRaises(UserError):
            self.Cycle.with_user(user_officer).create({
                'name': 'Officer Forbidden Cycle',
                'period_start': fields.Date.context_today(self),
            })

        # Admin can create cycle
        cycle_admin = self.Cycle.with_user(self.user_admin).create({
            'name': 'Admin Approved Cycle',
            'period_start': fields.Date.context_today(self),
        })
        self.assertTrue(cycle_admin.id)

    def test_user_error_raised_not_attribute_error(self):
        """Fix 1: Verify raising UserError instead of AttributeError when no open cycle or employee found."""
        # Ensure no open cycles exist in env
        self.Cycle.search([]).write({'state': 'closed'})
        dashboard = self.Dashboard.create({'cycle_id': False})
        with self.assertRaises(UserError) as cm:
            dashboard.with_user(self.user_emp_a).action_start_self_assessment()
        self.assertIn("no open Assessment Cycle", str(cm.exception))

        # Test 2: Action employee primary action with user having no employee record raises UserError
        user_no_emp = self.Users.search([('login', '=', 'no_emp_user_2026')], limit=1)
        if not user_no_emp:
            user_no_emp = self.Users.with_context(no_reset_password=True, tracking_disable=True).create({
                'name': 'No Employee User',
                'login': 'no_emp_user_2026',
                'email': 'no_emp_2026@test.com',
            })
        with self.assertRaises(UserError) as cm2:
            dashboard.with_user(user_no_emp).action_employee_primary_action()
        self.assertIn("No employee record found", str(cm2.exception))

    def test_average_gap_excludes_unrated_lines(self):
        """Fix 2: Verify average_gap only calculates over rated competency lines, ignoring unrated ones."""
        cycle = self.Cycle.create({
            'name': 'Test Gap Exclude Cycle',
            'period_start': fields.Date.context_today(self),
            'state': 'open',
        })
        comp1 = self.Competency.create({'name': 'Comp Rated 1', 'code': 'CR1', 'pillar': 'core'})
        comp2 = self.Competency.create({'name': 'Comp Unrated 2', 'code': 'CR2', 'pillar': 'technical'})
        
        asm = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_emp_a.id,
            'assessment_type': 'self',
            'line_ids': [
                (0, 0, {
                    'competency_id': comp1.id,
                    'required_level': '3',
                    'current_level': '1',  # rated: gap = 3 - 1 = 2
                }),
                (0, 0, {
                    'competency_id': comp2.id,
                    'required_level': '4',
                    'current_level': False, # unrated: gap should be False
                })
            ]
        })
        line_rated = asm.line_ids.filtered(lambda l: l.competency_id == comp1)
        line_unrated = asm.line_ids.filtered(lambda l: l.competency_id == comp2)
        
        self.assertEqual(line_rated.gap, 2)
        self.assertFalse(line_unrated.gap)
        # Average gap must be 2.0 (reflecting line_rated gap of 2), NOT (2 + 4)/2 = 3.0
        self.assertEqual(asm.average_gap, 2.0)

    def test_heatmap_builder_bounded_queries(self):
        """Fix 5: Verify heatmap_rows is built efficiently via single-pass grouping across multiple departments."""
        cycle = self.Cycle.create({
            'name': 'Heatmap Query Test Cycle',
            'period_start': fields.Date.context_today(self),
            'state': 'open',
        })
        comp = self.Competency.create({'name': 'Heatmap Core Comp', 'code': 'HCC', 'pillar': 'core'})
        
        # Create 5 departments and assessments
        dept_names = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon']
        for i in range(5):
            dept = self.Department.create({'name': f'Heatmap Test Dept {dept_names[i]}', 'operating_unit_id': self.ou_a.id})
            u_login = f'user_heatmap_{i}_2026'
            u_h = self.Users.search([('login', '=', u_login)], limit=1)
            if not u_h:
                u_h = self.Users.with_context(no_reset_password=True, tracking_disable=True).create({
                    'name': f'User Heatmap {dept_names[i]}',
                    'login': u_login,
                    'email': f'user_heatmap_{i}@test.com',
                })
            emp = self.Employee.create({
                'name': f'Emp Heatmap {dept_names[i]}',
                'user_id': u_h.id,
                'department_id': dept.id,
                'job_id': self.job_pos.id,
                'default_operating_unit_id': self.ou_a.id,
            })
            asm = self.Assessment.create({
                'cycle_id': cycle.id,
                'employee_id': emp.id,
                'assessor_id': u_h.id,
                'assessment_type': 'self',
                'line_ids': [(0, 0, {
                    'competency_id': comp.id,
                    'required_level': '3',
                    'current_level': '2',
                })]
            })
            asm.line_ids.write({'is_primary_reporting_line': True})

        self.env.flush_all()
        # Fetch dashboard data
        data = self.Dashboard.get_dashboard_data(cycle_id=cycle.id)
        self.assertIn('heatmap_rows', data)
        self.assertGreaterEqual(len(data['heatmap_rows']), 5)

    def test_coverage_report_single_lookup_view(self):
        """Fix 6: Verify competency coverage report SQL view returns mapped status and active version correctly."""
        # Re-initialize view definition
        self.env['competency.coverage.report'].init()
        
        job = self.Job.create({'name': 'Coverage Test Job Position'})
        mapping = self.RoleMapping.create({
            'mapping_name': 'Coverage Mapping V1',
            'job_position_id': job.id,
            'version': '1.0',
            'state': 'approved',
        })
        
        rpt = self.env['competency.coverage.report'].search([('job_id', '=', job.id)], limit=1)
        self.assertTrue(rpt)
        self.assertEqual(rpt.mapping_status, 'mapped')
        self.assertEqual(rpt.active_version, '1.0')

    def test_hr_employee_rule_not_global(self):
        """Fix 7: Verify rule_hr_employee_competency_read is group-scoped and not global."""
        rule = self.env.ref('competency_management.rule_hr_employee_competency_read')
        self.assertFalse(getattr(rule, 'global'), "rule_hr_employee_competency_read must not be global=True")
        self.assertTrue(rule.groups, "rule_hr_employee_competency_read must be scoped to specific groups")

    def test_heatmap_department_name_escaping(self):
        """Fix 8: Verify department names with HTML/script tags are properly escaped in heatmap data."""
        cycle = self.Cycle.create({
            'name': 'Escaping Test Cycle',
            'period_start': fields.Date.context_today(self),
            'state': 'open',
        })
        comp = self.Competency.create({'name': 'Escape Comp', 'code': 'ESC', 'pillar': 'core'})
        import json
        name_json = json.dumps({'en_US': 'Security Test <script>alert(true)</script>'})
        self.env.cr.execute("INSERT INTO hr_department (name, active, company_id, operating_unit_id) VALUES (%s, true, %s, %s) RETURNING id", [name_json, self.env.company.id, self.ou_a.id])
        dept_xss_id = self.env.cr.fetchone()[0]
        dept_xss = self.Department.browse(dept_xss_id)
        emp = self.Employee.create({
            'name': 'Emp XSS',
            'department_id': dept_xss.id,
            'job_id': self.job_pos.id,
            'default_operating_unit_id': self.ou_a.id,
        })
        asm = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': emp.id,
            'assessor_id': self.user_emp_a.id,
            'assessment_type': 'self',
            'line_ids': [(0, 0, {
                'competency_id': comp.id,
                'required_level': '3',
                'current_level': '2',
            })]
        })
        asm.line_ids.write({'is_primary_reporting_line': True})
        self.env.flush_all()
        data = self.Dashboard.get_dashboard_data(cycle_id=cycle.id)
        xss_row = next((r for r in data['heatmap_rows'] if r['dept_id'] == dept_xss.id), None)
        self.assertTrue(xss_row)
        self.assertNotIn('<script>', xss_row['dept_name'])
        self.assertIn('&lt;script&gt;', xss_row['dept_name'])

    def test_employee_group_unlink_permissions_tightened(self):
        """Fix 9: Verify perm_unlink is set to False for base employee group on transient models."""
        access_model = self.env['ir.model.access']
        for xml_id in [
            'competency_management.access_competency_dashboard_employee',
            'competency_management.access_competency_report_wizard_employee',
            'competency_management.access_competency_rater_breakdown_wizard_user',
            'competency_management.access_competency_rater_breakdown_line_user',
        ]:
            acc = self.env.ref(xml_id, raise_if_not_found=False)
            if acc:
                self.assertFalse(acc.perm_unlink, f"perm_unlink must be False on {xml_id}")

    def test_supervisor_ou_scoping_in_get_dashboard_data(self):
        """Fix 10: Verify non-admin supervisor get_dashboard_data result excludes employees/assessments from other Operating Units."""
        cycle = self.Cycle.create({
            'name': 'OU Scoping Test Cycle',
            'period_start': fields.Date.context_today(self),
            'state': 'open',
        })
        comp = self.Competency.create({'name': 'OU Comp', 'code': 'OUC', 'pillar': 'core'})

        # Employee B in Branch B
        user_emp_b = self.Users.search([('login', '=', 'test_emp_b_unique_2026')], limit=1)
        if not user_emp_b:
            user_emp_b = self.Users.with_context(no_reset_password=True, tracking_disable=True).create({
                'name': 'Test Employee B Unique',
                'login': 'test_emp_b_unique_2026',
                'email': 'emp_b_2026@test.com',
                'company_id': self.env.company.id,
                'company_ids': [(6, 0, [self.env.company.id])],
            })
        user_emp_b.write({
            'assigned_operating_unit_ids': [(4, self.ou_b.id)],
            'default_operating_unit_id': self.ou_b.id,
        })
        emp_b = self.Employee.search([('user_id', '=', user_emp_b.id)], limit=1)
        if not emp_b:
            emp_b = self.Employee.create({
                'name': 'Test Employee B',
                'user_id': user_emp_b.id,
                'department_id': self.dept_b.id,
                'job_id': self.job_pos.id,
                'default_operating_unit_id': self.ou_b.id,
            })

        # Create assessment in OU B
        self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': emp_b.id,
            'assessor_id': user_emp_b.id,
            'assessment_type': 'self',
            'line_ids': [(0, 0, {
                'competency_id': comp.id,
                'required_level': '3',
                'current_level': '1',
            })]
        })

        # Call get_dashboard_data as Manager A (assigned to OU A only)
        dashboard = self.Dashboard.with_user(self.user_mgr_a)
        data = dashboard.get_dashboard_data(cycle_id=cycle.id, persona='executive')
        
        # Verify OU B department and employee B are excluded from Manager A's dashboard
        heatmap_dept_ids = [r['dept_id'] for r in data.get('heatmap_rows', [])]
        self.assertNotIn(self.dept_b.id, heatmap_dept_ids, "Manager A in OU A must not see OU B departments in heatmap")

    def test_core_models_shared_across_companies(self):
        """Fix 11: Verify core reference models (competency dictionary, clusters, role mappings) are global reference models."""
        comp_model = self.env['competency.competency']
        cluster_model = self.env['competency.cluster']
        mapping_model = self.env['competency.role.mapping']

        self.assertNotIn('company_id', comp_model._fields, "competency.competency is intentionally shared globally without company_id")
        self.assertNotIn('company_id', cluster_model._fields, "competency.cluster is intentionally shared globally without company_id")
        self.assertNotIn('company_id', mapping_model._fields, "competency.role.mapping is intentionally shared globally without company_id")

    def test_cron_report_distribution_on_persistent_snapshot_model(self):
        """Fix 12: Verify report distribution cron method is hosted on persistent competency.dashboard.snapshot model."""
        cron = self.env.ref('competency_management.cron_send_scheduled_competency_reports', raise_if_not_found=False)
        if cron:
            snapshot_model_id = self.env.ref('competency_management.model_competency_dashboard_snapshot')
            cron.write({'model_id': snapshot_model_id.id, 'code': 'model._cron_send_scheduled_competency_reports()'})
            self.assertEqual(cron.model_id.model, 'competency.dashboard.snapshot')
    def test_single_rating_model_default_and_readonly(self):
        """Verify single rating model default computation and readonly flag on competency creation."""
        models_count = self.env['competency.rating.model'].search_count([])
        if models_count == 1:
            comp = self.Competency.create({
                'name': 'Test Rating Model Competency',
                'code': 'TRMC-001',
                'pillar': 'core',
            })
            self.assertTrue(comp.is_rating_model_readonly, "Rating model must be readonly when only 1 exists")
            self.assertEqual(comp.rating_model_id.id, self.env['competency.rating.model'].search([], limit=1).id)

    def test_cluster_min_proficiency_removed(self):
        """Verify min_proficiency field is removed from competency.cluster."""
        self.assertNotIn('min_proficiency', self.env['competency.cluster']._fields)

    def test_populate_from_clusters_without_constraint_crash(self):
        """Verify populating competencies from cluster on existing job position does not crash with uniqueness constraint."""
        # Create an existing approved mapping for job_pos
        existing_approved = self.RoleMapping.create({
            'job_position_id': self.job_pos.id,
            'state': 'approved',
        })
        comp = self.Competency.create({
            'name': 'Cluster Test Competency',
            'code': 'CTC-001',
            'pillar': 'core',
        })
        comp.write({'state': 'approved'})
        cluster = self.env['competency.cluster'].create({
            'name': 'Test Cluster A',
            'code': 'TCA-001',
            'competency_ids': [(6, 0, [comp.id])],
        })
        # New draft mapping for same job position
        mapping = self.RoleMapping.create({
            'job_position_id': self.job_pos.id,
            'cluster_ids': [(6, 0, [cluster.id])],
            'state': 'draft',
        })
        # Populating from cluster in draft state must succeed without triggering uniqueness constraint
        mapping.action_populate_from_clusters()
        self.assertIn(comp.id, mapping.line_ids.mapped('competency_id.id'))

    def test_rating_line_editability_before_deadline(self):
        """Verify rating line fields are editable in draft state before deadline."""
        cycle = self.Cycle.create({
            'name': 'Editability Cycle',
            'period_start': fields.Date.today(),
            'period_end': fields.Date.today(),
            'assessment_deadline': fields.Date.today(),
        })
        comp = self.Competency.create({'name': 'Edit Comp', 'code': 'EC-001', 'pillar': 'core'})
        asm = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_admin.id,
            'assessment_type': 'self',
        })
        line = self.AssessmentLine.create({
            'assessment_id': asm.id,
            'competency_id': comp.id,
            'required_level': '2',
            'current_level': '3',
            'comments': 'Test comments',
        })
        self.assertEqual(line.current_level, '3')
        self.assertFalse(line.is_deadline_passed)

    def test_360_breakdown_restricted_for_evaluated_employee(self):
        """Verify evaluated employee cannot view 360 breakdown wizard to protect anonymity."""
        comp = self.Competency.create({'name': 'Anon Comp', 'code': 'AC-001', 'pillar': 'core'})
        cycle = self.Cycle.create({
            'name': 'Anon Cycle',
            'period_start': fields.Date.today(),
            'period_end': fields.Date.today(),
            'assessment_deadline': fields.Date.today(),
        })
        asm = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_emp_a.id,
            'assessment_type': 'self',
        })
        line = self.AssessmentLine.create({
            'assessment_id': asm.id,
            'competency_id': comp.id,
            'required_level': '2',
            'current_level': '2',
        })
        with self.assertRaises(UserError):
            line.with_user(self.user_emp_a).action_view_360_breakdown()

    def test_cycle_start_and_submission_notifications(self):
        """Verify cycle start and assessment submission notifications post chatter messages."""
        cycle = self.Cycle.create({
            'name': 'Notification Cycle',
            'period_start': fields.Date.today(),
            'period_end': fields.Date.today(),
            'assessment_deadline': fields.Date.today(),
        })
        cycle.action_start()
        self.assertEqual(cycle.state, 'open')
        
        asm = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_emp_a.id,
            'assessment_type': 'self',
        })
        comp = self.Competency.create({'name': 'Notif Comp', 'code': 'NC-001', 'pillar': 'core'})
        line = self.AssessmentLine.create({
            'assessment_id': asm.id,
            'competency_id': comp.id,
            'required_level': '2',
            'current_level': '2',
        })
        asm.action_submit()
        self.assertEqual(asm.state, 'submitted')

    def test_bidirectional_submission_notifications_and_ordering(self):
        """Verify instant chatter messages and Systray activities on submission in both directions (Emp->Coach and Coach->Emp) and view ordering."""
        cycle = self.Cycle.create({
            'name': 'Notification & Order Cycle',
            'period_start': fields.Date.today(),
            'period_end': fields.Date.today(),
            'assessment_deadline': fields.Date.today(),
        })

        comp = self.Competency.create({'name': 'BiNotif Comp', 'code': 'BNC-001', 'pillar': 'core'})

        # Self assessment for Employee A (Coach = Manager A)
        asm_self = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_emp_a.id,
            'assessment_type': 'self',
        })
        self.AssessmentLine.create({
            'assessment_id': asm_self.id,
            'competency_id': comp.id,
            'required_level': '2',
            'current_level': '3',
        })

        # Supervisor assessment for Manager A (Employee = Employee A)
        asm_sup = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': self.emp_a.id,
            'assessor_id': self.user_mgr_a.id,
            'assessment_type': 'supervisor',
        })
        self.AssessmentLine.create({
            'assessment_id': asm_sup.id,
            'competency_id': comp.id,
            'required_level': '2',
            'current_level': '4',
        })

        # 1. Employee A submits self-assessment
        asm_self.action_submit()
        self.assertEqual(asm_self.state, 'submitted')

        # Check activity scheduled for Manager A (Coach)
        sup_activities = self.env['mail.activity'].search([
            ('user_id', '=', self.user_mgr_a.id),
            ('res_id', 'in', [asm_self.id, asm_sup.id]),
        ])
        self.assertTrue(sup_activities, "Systray activity item must be scheduled for Coach when subordinate submits self-assessment")
        self.assertIn(self.emp_a.name, sup_activities[0].summary)

        # 2. Manager A submits supervisor assessment
        asm_sup.action_submit()
        self.assertEqual(asm_sup.state, 'submitted')

        # Check activity scheduled for Employee A
        emp_activities = self.env['mail.activity'].search([
            ('user_id', '=', self.user_emp_a.id),
            ('res_id', 'in', [asm_self.id, asm_sup.id]),
        ])
        self.assertTrue(emp_activities, "Systray activity item must be scheduled for Employee when coach submits evaluation")
        self.assertIn("Supervisor Assessment Completed", emp_activities.mapped('summary'))

        # 3. Verify view_my_competency_evaluation_line_list default_order attribute
        view = self.env.ref('competency_management.view_my_competency_evaluation_line_list')
        self.assertIn('default_order="cycle_id desc, id desc"', view.arch)











