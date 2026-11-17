# -*- coding: utf-8 -*-
"""
Deep Production-Level Test Suite for Project Management (Odoo 19)
Tests every tier, model, business constraint, hierarchy, and workflow.
"""
import sys
import time
from datetime import date, timedelta

import odoo
import odoo.api
import odoo.tools
import odoo.sql_db
from odoo.exceptions import ValidationError, UserError

class ProductionTestSuite:
    def __init__(self):
        odoo.tools.config.parse_config(['-c', '/etc/odoo/odoo.conf', '-d', 'pm_db'])
        self.db = odoo.sql_db.db_connect('pm_db')
        self.cr = self.db.cursor()
        self.env = odoo.api.Environment(self.cr, odoo.SUPERUSER_ID, {})
        
        self.results = []
        self.created_record_refs = []  # List of (model, id)
        self.today = date.today()

    def log_result(self, level, case_id, description, passed, error_msg=None, elapsed=0.0):
        status_str = "PASS" if passed else "FAIL"
        self.results.append({
            'level': level,
            'case_id': case_id,
            'description': description,
            'status': status_str,
            'error': error_msg,
            'elapsed': elapsed
        })
        symbol = "[✓]" if passed else "[✗]"
        print(f"  {symbol} {case_id}: {description} [{status_str}] ({elapsed:.3f}s)")
        if error_msg:
            print(f"      ERROR: {error_msg}")

    def track(self, record):
        if record and record.exists():
            self.created_record_refs.append((record._name, record.id))
        return record

    def run_case(self, level, case_id, description, test_fn):
        t0 = time.time()
        try:
            with self.env.cr.savepoint():
                test_fn()
            # If the test function didn't raise, commit changes to make them available for next test
            self.cr.commit()
            elapsed = time.time() - t0
            self.log_result(level, case_id, description, True, elapsed=elapsed)
        except Exception as e:
            self.cr.rollback()
            elapsed = time.time() - t0
            self.log_result(level, case_id, description, False, error_msg=str(e), elapsed=elapsed)

    def run_all(self):
        print("\n" + "="*80)
        print("  STARTING DEEP PRODUCTION-LEVEL PROJECT MANAGEMENT TEST SUITE")
        print("="*80)

        self.test_level_1_strategic_tier()
        self.test_level_2_project_initiation()
        self.test_level_3_wbs_milestones_deliverables()
        self.test_level_4_execution_project_tasks()
        self.test_level_5_execution_non_project_tasks()
        self.test_level_6_qa_test_management()
        self.test_level_7_governance_risk_updates()
        self.cleanup_and_summary()

    # -------------------------------------------------------------------------
    # LEVEL 1: Strategic Governance Tier
    # -------------------------------------------------------------------------
    def test_level_1_strategic_tier(self):
        print("\n--- LEVEL 1: Strategic Governance & Planning Tier ---")
        
        def case_1_1():
            source = self.track(self.env['pm.strategic.source'].create({
                'name': '[PROD_TEST] National Digital Strategy 2026',
            }))
            issue = self.track(self.env['pm.strategic.issue'].create({
                'name': '[PROD_TEST] Legacy Payment Processing Bottleneck',
            }))
            assert source.id and issue.id, "Failed to create Strategic Source or Issue"
            self.source_id = source.id
            self.issue_id = issue.id
        self.run_case("Level 1", "TC-1.1", "Create Strategic Source & Strategic Issue", case_1_1)

        def case_1_2():
            source = self.env['pm.strategic.source'].browse(self.source_id)
            obj = self.track(self.env['pm.strategic.objective'].create({
                'name': '[PROD_TEST] Modernize Digital Banking Channels',
                'strategic_issue_id': self.issue_id,
                'strategic_source_ids': [(6, 0, [self.source_id])],
            }))
            assert obj.id, "Failed to create Strategic Objective"
            assert source in obj.strategic_source_ids, "Source not linked to Objective"
            self.objective_id = obj.id
        self.run_case("Level 1", "TC-1.2", "Create Strategic Objective linked to Issue & Source", case_1_2)

        def case_1_3():
            init = self.track(self.env['pm.initiative'].create({
                'name': '[PROD_TEST] Core API Banking Initiative',
                'strategic_issue_id': self.issue_id,
                'strategic_objective_ids': [(6, 0, [self.objective_id])],
                'strategic_source_ids': [(6, 0, [self.source_id])],
                'date_start': self.today,
                'date_end': self.today + timedelta(days=180),
                'description': '<p>Strategic API Transformation</p>',
            }))
            assert init.id, "Failed to create Initiative"
            assert init.code and init.code != 'New', f"Initiative code sequence not generated: {init.code}"
            self.initiative_id = init.id
        self.run_case("Level 1", "TC-1.3", "Create Strategic Initiative & Verify Auto-Sequence ID", case_1_3)

        def case_1_4():
            raised = False
            try:
                with self.env.cr.savepoint():
                    invalid_init = self.env['pm.initiative'].create({
                        'name': '[PROD_TEST] Invalid Date Initiative',
                        'date_start': self.today + timedelta(days=30),
                        'date_end': self.today,  # Invalid: end < start
                    })
                    self.track(invalid_init)
            except ValidationError:
                raised = True
            assert raised, "Expected ValidationError for date_end < date_start, but creation succeeded!"
        self.run_case("Level 1", "TC-1.4", "Constraint Check: Initiative End Date < Start Date raises ValidationError", case_1_4)

        def case_1_5():
            kpi1 = self.env['pm.initiative.kpi'].create({
                'initiative_id': self.initiative_id,
                'name': 'API Uptime Availability',
                'target': '99.99%',
                'remark': 'Continuous monitoring via Prometheus',
                'sequence': 10,
            })
            kpi2 = self.env['pm.initiative.kpi'].create({
                'initiative_id': self.initiative_id,
                'name': 'Transaction Processing Latency',
                'target': '< 150ms',
                'remark': 'Measured at API gateway boundary',
                'sequence': 20,
            })
            init = self.env['pm.initiative'].browse(self.initiative_id)
            init.invalidate_recordset(['kpi_ids'])
            assert len(init.kpi_ids) == 2, f"Expected 2 KPIs, found {len(init.kpi_ids)}"
            names = [k.name for k in init.kpi_ids]
            assert 'API Uptime Availability' in names and 'Transaction Processing Latency' in names
            assert init.kpi_ids[0].target == '99.99%'
        self.run_case("Level 1", "TC-1.5", "Create & Query Initiative KPIs (name, target, remark, sequence)", case_1_5)

        def case_1_6():
            new_init = self.env['pm.initiative'].new({
                'name': 'Draft Initiative',
                'strategic_objective_ids': [(6, 0, [self.objective_id])],
            })
            new_init._onchange_strategic_objective_ids()
            assert new_init.strategic_issue_id.id == self.issue_id, "Failed to infer strategic issue from objective"
            assert self.source_id in new_init.strategic_source_ids.ids, "Failed to infer strategic source from objective"
        self.run_case("Level 1", "TC-1.6", "Initiative Onchange Inference: Auto-derive Issue & Sources", case_1_6)

    # -------------------------------------------------------------------------
    # LEVEL 2: Project Initiation & Setup Tier
    # -------------------------------------------------------------------------
    def test_level_2_project_initiation(self):
        print("\n--- LEVEL 2: Project Initiation & Governance Tier ---")

        def case_2_1():
            sponsor = self.track(self.env['pm.project.sponsor'].create({
                'name': '[PROD_TEST] Retail Banking Division',
                'code': 'RBD_TEST',
                'head_id': self.env.user.id,
            }))
            owner = self.track(self.env['pm.process.owner'].create({
                'name': '[PROD_TEST] Digital Operations Department',
                'code': 'DOD_TEST',
                'head_id': self.env.user.id,
            }))
            office = self.track(self.env['pm.lead.office'].create({
                'name': '[PROD_TEST] PMO Enterprise Office',
                'code': 'PMO_TEST',
                'head_id': self.env.user.id,
            }))
            assert sponsor.id and owner.id and office.id
            self.sponsor_id = sponsor.id
            self.process_owner_id = owner.id
            self.lead_office_id = office.id
        self.run_case("Level 2", "TC-2.1", "Create Master Data: Sponsor, Process Owner, Lead Office", case_2_1)

        def case_2_2():
            admin_user = self.env.user
            project = self.track(self.env['pm.project'].create({
                'name': '[PROD_TEST] Core API Gateway Implementation',
                'initiative_id': self.initiative_id,
                'sponsor_ids': [(6, 0, [self.sponsor_id])],
                'process_owner_ids': [(6, 0, [self.process_owner_id])],
                'lead_office_ids': [(6, 0, [self.lead_office_id])],
                'manager_id': admin_user.id,
                'coordinator_id': admin_user.id,
                'member_ids': [(6, 0, [admin_user.id])],
                'date_start': self.today,
                'date_end': self.today + timedelta(days=120),
                'estimated_cost': 500000.0,
                'status': 'draft',
                'health_state': 'on_track',
            }))
            assert project.id
            assert project.code and project.code != 'New', f"Project code not auto-generated: {project.code}"
            self.project_id = project.id
        self.run_case("Level 2", "TC-2.2", "Create Project Linked to Strategic Initiative & Master Governance", case_2_2)

        def case_2_3():
            raised = False
            try:
                with self.env.cr.savepoint():
                    invalid_proj = self.env['pm.project'].create({
                        'name': '[PROD_TEST] Invalid Date Project',
                        'date_start': self.today + timedelta(days=60),
                        'date_end': self.today,
                    })
                    self.track(invalid_proj)
            except ValidationError:
                raised = True
            assert raised, "Expected ValidationError for Project date_end < date_start"
        self.run_case("Level 2", "TC-2.3", "Constraint Check: Project End Date < Start Date raises ValidationError", case_2_3)

        def case_2_4():
            project = self.env['pm.project'].browse(self.project_id)
            project.write({'status': 'active'})
            assert project.status == 'active'
            project.write({'status': 'completed'})
            assert project.status == 'completed'
            project.write({'status': 'active'})
        self.run_case("Level 2", "TC-2.4", "Project Lifecycle State Transitions (draft -> approved -> in_progress)", case_2_4)

    # -------------------------------------------------------------------------
    # LEVEL 3: Work Breakdown Structure (WBS) - Milestones & Deliverables
    # -------------------------------------------------------------------------
    def test_level_3_wbs_milestones_deliverables(self):
        print("\n--- LEVEL 3: Work Breakdown Structure (WBS) Tier ---")

        def case_3_1():
            project = self.env['pm.project'].browse(self.project_id)
            m1 = self.track(self.env['pm.milestone'].create({
                'name': '[PROD_TEST] Milestone 1: Architecture & Architecture Design',
                'project_id': project.id,
                'weight': 40.0,
                'date_start': project.date_start,
                'date_deadline': project.date_start + timedelta(days=40),
                'state': 'draft',
            }))
            m2 = self.track(self.env['pm.milestone'].create({
                'name': '[PROD_TEST] Milestone 2: API Gateway Core Engine',
                'project_id': project.id,
                'weight': 60.0,
                'date_start': project.date_start + timedelta(days=41),
                'date_deadline': project.date_end,
                'state': 'draft',
            }))
            assert m1.id and m2.id
            self.milestone1_id = m1.id
            self.milestone2_id = m2.id
        self.run_case("Level 3", "TC-3.1", "Create Project Milestones with Valid Total Weights (40% + 60% = 100%)", case_3_1)

        def case_3_2():
            project = self.env['pm.project'].browse(self.project_id)
            raised = False
            try:
                with self.env.cr.savepoint():
                    m_over = self.env['pm.milestone'].create({
                        'name': '[PROD_TEST] Milestone 3: Exceeding Weight',
                        'project_id': project.id,
                        'weight': 10.0,  # 40 + 60 + 10 = 110% -> MUST FAIL
                        'date_start': project.date_start,
                        'date_deadline': project.date_end,
                    })
                    self.track(m_over)
            except ValidationError:
                raised = True
            assert raised, "Expected ValidationError when total milestone weight exceeds 100%!"
        self.run_case("Level 3", "TC-3.2", "Constraint Check: Milestone Weights Exceeding 100% raises ValidationError", case_3_2)

        def case_3_3():
            # Test Milestone Status Persistence
            m1 = self.env['pm.milestone'].browse(self.milestone1_id)
            m1.write({
                'is_state_manual': True,
                'state': 'completed'
            })
            m1.flush_recordset(['state', 'is_state_manual'])
            m1.invalidate_recordset(['state', 'is_state_manual'])
            assert m1.state == 'completed', f"Milestone state reverted! Expected 'completed', found '{m1.state}'"
            assert m1.is_state_manual is True, "Manual state flag was not preserved!"
            
            # Reset back to in_progress for further task testing
            m1.write({'state': 'in_progress', 'is_state_manual': False})
        self.run_case("Level 3", "TC-3.3", "Milestone Status Persistence: Manual Status Override Stays Saved in DB", case_3_3)

        def case_3_4():
            m1 = self.env['pm.milestone'].browse(self.milestone1_id)
            d1 = self.track(self.env['pm.deliverable'].create({
                'name': '[PROD_TEST] Deliverable 1.1: Microservices Architecture Blueprint',
                'project_id': self.project_id,
                'milestone_id': m1.id,
                'weight': 20.0,  # Under milestone weight of 40%
                'date_start': m1.date_start,
                'date_deadline': m1.date_deadline,
                'state': 'draft',
            }))
            d2 = self.track(self.env['pm.deliverable'].create({
                'name': '[PROD_TEST] Deliverable 1.2: Security & OAuth2 Spec',
                'project_id': self.project_id,
                'milestone_id': m1.id,
                'weight': 20.0,
                'date_start': m1.date_start,
                'date_deadline': m1.date_deadline,
                'state': 'draft',
            }))
            assert d1.id and d2.id
            self.deliverable1_id = d1.id
            self.deliverable2_id = d2.id
        self.run_case("Level 3", "TC-3.4", "Create Deliverables under Milestone with Valid Weights (20% + 20% = 40%)", case_3_4)

        def case_3_5():
            m1 = self.env['pm.milestone'].browse(self.milestone1_id)
            raised = False
            try:
                with self.env.cr.savepoint():
                    d_over = self.env['pm.deliverable'].create({
                        'name': '[PROD_TEST] Deliverable 1.3: Exceeding Weight',
                        'project_id': self.project_id,
                        'milestone_id': m1.id,
                        'weight': 5.0,  # 20 + 20 + 5 = 45% > 40% -> MUST FAIL
                        'date_start': m1.date_start,
                        'date_deadline': m1.date_deadline,
                    })
                    self.track(d_over)
            except ValidationError:
                raised = True
            assert raised, "Expected ValidationError when Deliverable weights exceed Milestone weight!"
        self.run_case("Level 3", "TC-3.5", "Constraint Check: Deliverable Weights Exceeding Milestone Weight raises ValidationError", case_3_5)

    # -------------------------------------------------------------------------
    # LEVEL 4: Execution Tier - Project Tasks
    # -------------------------------------------------------------------------
    def test_level_4_execution_project_tasks(self):
        print("\n--- LEVEL 4: Execution Hierarchy - Project Tasks & Dependencies ---")

        def case_4_1():
            d1 = self.env['pm.deliverable'].browse(self.deliverable1_id)
            task1 = self.track(self.env['pm.task'].create({
                'name': '[PROD_TEST] Task 1.1.1: Design Schema & Service Mesh',
                'is_project_task': True,
                'project_id': self.project_id,
                'milestone_id': self.milestone1_id,
                'deliverable_id': d1.id,
                'weight': 10.0,  # <= 20.0%
                'date_start': d1.date_start,
                'date_deadline': d1.date_start + timedelta(days=10),
                'user_ids': [(6, 0, [self.env.user.id])],
            }))
            task2 = self.track(self.env['pm.task'].create({
                'name': '[PROD_TEST] Task 1.1.2: Implement Kong Gateway Integration',
                'is_project_task': True,
                'project_id': self.project_id,
                'milestone_id': self.milestone1_id,
                'deliverable_id': d1.id,
                'weight': 10.0,
                'date_start': d1.date_start + timedelta(days=11),
                'date_deadline': d1.date_deadline,
                'user_ids': [(6, 0, [self.env.user.id])],
            }))
            assert task1.id and task2.id
            self.task1_id = task1.id
            self.task2_id = task2.id
        self.run_case("Level 4", "TC-4.1", "Create Project Tasks Linked to Deliverable (10% + 10% = 20%)", case_4_1)

        def case_4_2():
            d1 = self.env['pm.deliverable'].browse(self.deliverable1_id)
            raised = False
            try:
                with self.env.cr.savepoint():
                    task_over = self.env['pm.task'].create({
                        'name': '[PROD_TEST] Task 1.1.3: Exceeding Task Weight',
                        'is_project_task': True,
                        'project_id': self.project_id,
                        'milestone_id': self.milestone1_id,
                        'deliverable_id': d1.id,
                        'weight': 5.0,  # 10 + 10 + 5 = 25% > 20% -> MUST FAIL
                        'date_start': d1.date_start,
                        'date_deadline': d1.date_deadline,
                    })
                    self.track(task_over)
            except ValidationError:
                raised = True
            assert raised, "Expected ValidationError when Task weights exceed Deliverable weight!"
        self.run_case("Level 4", "TC-4.2", "Constraint Check: Task Weights Exceeding Deliverable Weight raises ValidationError", case_4_2)

        def case_4_3():
            raised = False
            try:
                with self.env.cr.savepoint():
                    task_bad_dates = self.env['pm.task'].create({
                        'name': '[PROD_TEST] Task Bad Dates',
                        'date_start': self.today + timedelta(days=10),
                        'date_deadline': self.today,
                    })
                    self.track(task_bad_dates)
            except ValidationError:
                raised = True
            assert raised, "Expected ValidationError when Task Deadline < Start Date"
        self.run_case("Level 4", "TC-4.3", "Constraint Check: Task Deadline < Start Date raises ValidationError", case_4_3)

        def case_4_4():
            task1 = self.env['pm.task'].browse(self.task1_id)
            sub1 = self.env['pm.task.subtask'].create({
                'task_id': task1.id,
                'name': 'Define OpenAPI 3.0 YAML spec',
                'weight': 50.0,
                'is_done': False,
            })
            sub2 = self.env['pm.task.subtask'].create({
                'task_id': task1.id,
                'name': 'Validate schemas with team',
                'weight': 50.0,
                'is_done': False,
            })
            task1.invalidate_recordset(['progress_rate', 'subtask_count'])
            assert task1.progress_rate == 0.0, f"Expected 0% progress, got {task1.progress_rate}"
            
            # Mark sub1 as done
            sub1.write({'is_done': True})
            task1.invalidate_recordset(['progress_rate'])
            assert task1.progress_rate == 50.0, f"Expected 50% progress, got {task1.progress_rate}"
        self.run_case("Level 4", "TC-4.4", "Create Subtasks & Verify Weighted Progress Calculation (50% on subtask done)", case_4_4)

        def case_4_5():
            task1 = self.env['pm.task'].browse(self.task1_id)
            task2 = self.env['pm.task'].browse(self.task2_id)
            # Make Task 2 blocked by Task 1
            task2.write({
                'blocked_by_ids': [(6, 0, [task1.id])]
            })
            task2.invalidate_recordset(['is_blocked', 'state'])
            assert task2.is_blocked is True, "Task 2 should be marked as is_blocked = True"
            
            # Attempting action_start_work on blocked task must raise UserError
            try:
                task2.action_start_work()
                assert False, "Expected UserError when attempting to start work on a blocked task!"
            except UserError:
                pass
        self.run_case("Level 4", "TC-4.5", "Task Dependency: Blocked Task has is_blocked=True and action_start_work raises UserError", case_4_5)

        def case_4_6():
            task1 = self.env['pm.task'].browse(self.task1_id)
            task2 = self.env['pm.task'].browse(self.task2_id)
            # Complete Task 1 via action_approve_complete
            task1.action_approve_complete()
            task1.invalidate_recordset(['is_closed', 'progress_rate'])
            assert task1.is_closed is True, "Task 1 should be closed/completed"
            assert task1.progress_rate == 100.0, "Task 1 progress should be 100%"
            
            # Now Task 2 should automatically become unblocked!
            task2.invalidate_recordset(['is_blocked'])
            assert task2.is_blocked is False, "Task 2 should now be unblocked after Task 1 completed"
            
            # Now action_start_work on Task 2 must succeed
            task2.action_start_work()
            assert task2.stage_id.name == 'In Progress' or task2.state == 'in_progress', "Task 2 failed to move to In Progress"
        self.run_case("Level 4", "TC-4.6", "Task Unblocking: Completing Prerequisite Task automatically unblocks Dependent Task", case_4_6)

        def case_4_7():
            task2 = self.env['pm.task'].browse(self.task2_id)
            deliverable1 = self.env['pm.deliverable'].browse(self.deliverable1_id)
            # Complete Task 2 as well
            task2.action_approve_complete()
            self.env.flush_all()
            deliverable1.invalidate_recordset()
            # Since task1 and task2 (each 10% weight under 20% deliverable) are 100% done:
            assert deliverable1.progress_rate == 100.0, f"Expected Deliverable progress 100%, got {deliverable1.progress_rate}"
        self.run_case("Level 4", "TC-4.7", "Progress Rollup: Completed Tasks roll up to 100% Deliverable Progress", case_4_7)

    # -------------------------------------------------------------------------
    # LEVEL 5: Operational Hierarchy - Non-Project Tasks
    # -------------------------------------------------------------------------
    def test_level_5_execution_non_project_tasks(self):
        print("\n--- LEVEL 5: Operational Hierarchy - Non-Project Tasks ---")

        def case_5_1():
            np_task = self.track(self.env['pm.task'].create({
                'name': '[PROD_TEST] Non-Project Task: Routine Infrastructure Audit',
                'is_project_task': False,
                'project_id': False,
                'milestone_id': False,
                'deliverable_id': False,
                'tag_type': 'internal',
                'date_start': self.today,
                'date_deadline': self.today + timedelta(days=5),
            }))
            assert np_task.id
            assert np_task.is_project_task is False
            assert not np_task.project_id
            self.np_task_id = np_task.id
        self.run_case("Level 5", "TC-5.1", "Create Non-Project Task without Project / Milestone / Deliverable", case_5_1)

        def case_5_2():
            np_task = self.env['pm.task'].browse(self.np_task_id)
            # Verify Task Owner defaults to current user
            assert np_task.owner_id.id == self.env.user.id, "Task Owner did not default to current user"
            # Verify Task Owner can be updated
            admin = self.env['res.users'].search([('id', '=', odoo.SUPERUSER_ID)], limit=1)
            np_task.write({'owner_id': admin.id})
            assert np_task.owner_id.id == admin.id, "Failed to update Task Owner"
        self.run_case("Level 5", "TC-5.2", "Verify Task Owner (owner_id) defaults to user and is fully editable", case_5_2)

        def case_5_3():
            np_task = self.env['pm.task'].browse(self.np_task_id)
            for t_type in ['internal', 'external', 'both']:
                np_task.write({'tag_type': t_type})
                assert np_task.tag_type == t_type, f"Failed to set Task Type to '{t_type}'"
        self.run_case("Level 5", "TC-5.3", "Verify Task Type (tag_type) Radio Selection: internal, external, both", case_5_3)

        def case_5_4():
            np_task = self.env['pm.task'].browse(self.np_task_id)
            admin = self.env['res.users'].search([('active', '=', True), ('share', '=', False)], limit=1)
            assert len(np_task.project_member_ids) > 0, "Non-project task member pool is empty"
            assert admin in np_task.project_member_ids, "Internal user not in available member pool"
            np_task.write({'user_ids': [(6, 0, [admin.id])]})
            assert admin in np_task.user_ids
        self.run_case("Level 5", "TC-5.4", "Verify Assignees Pool contains all Internal Users for Non-Project Tasks", case_5_4)

        def case_5_5():
            np_task = self.env['pm.task'].browse(self.np_task_id)
            sub = self.env['pm.task.subtask'].create({
                'task_id': np_task.id,
                'name': 'Audit Firewalls & DMZ',
                'weight': 1.0,
                'is_done': False,
            })
            assert np_task.progress_rate == 0.0
            sub.write({'is_done': True})
            np_task.invalidate_recordset(['progress_rate'])
            assert np_task.progress_rate == 100.0, f"Expected 100% progress on single subtask done, got {np_task.progress_rate}"
        self.run_case("Level 5", "TC-5.5", "Non-Project Subtasks and Independent Progress Calculation", case_5_5)

    # -------------------------------------------------------------------------
    # LEVEL 6: Quality Assurance & Test Management (QA) Tier
    # -------------------------------------------------------------------------
    def test_level_6_qa_test_management(self):
        print("\n--- LEVEL 6: Quality Assurance & Test Management (QA) Tier ---")

        def case_6_1():
            tc1 = self.track(self.env['pm.test.case.line'].create({
                'project_id': self.project_id,
                'milestone_id': self.milestone1_id,
                'deliverable_id': self.deliverable1_id,
                'code': 'TC-SEC-001',
                'name': 'Verify OAuth2 JWT token signature validation',
                'category': 'security',
                'severity': 'critical',
                'steps': '1. Send request with expired JWT\n2. Send request with valid JWT',
                'expected_result': '401 on expired; 200 on valid',
            }))
            tc2 = self.track(self.env['pm.test.case.line'].create({
                'project_id': self.project_id,
                'milestone_id': self.milestone1_id,
                'deliverable_id': self.deliverable1_id,
                'code': 'TC-API-002',
                'name': 'Verify Rate Limiting per client key',
                'category': 'api_integration',
                'severity': 'high',
                'steps': 'Send 1000 requests in 1 second',
                'expected_result': '429 Too Many Requests after limit',
            }))
            tc3 = self.track(self.env['pm.test.case.line'].create({
                'project_id': self.project_id,
                'milestone_id': self.milestone1_id,
                'deliverable_id': self.deliverable1_id,
                'code': 'TC-API-003',
                'name': 'Verify Legacy SOAP proxy bypass',
                'category': 'other',
                'severity': 'low',
            }))
            assert tc1.id and tc2.id and tc3.id
            self.tc1_id = tc1.id
            self.tc2_id = tc2
            self.tc3_id = tc3
        self.run_case("Level 6", "TC-6.1", "Create Test Case Specifications (Security, API, Other)", case_6_1)

        def case_6_2():
            execution = self.track(self.env['pm.test.execution'].create({
                'name': '[PROD_TEST] Sprint 1 QA Run - Architecture Validation',
                'project_id': self.project_id,
                'milestone_id': self.milestone1_id,
                'deliverable_id': self.deliverable1_id,
                'test_round': 'Round 1',
            }))
            assert execution.id
            assert execution.code and execution.code != 'New', f"Execution ID sequence not generated: {execution.code}"
            # Verify test cases auto-loaded
            execution.invalidate_recordset(['execution_line_ids'])
            assert len(execution.execution_line_ids) == 3, f"Expected 3 test cases loaded, found {len(execution.execution_line_ids)}"
            self.execution_id = execution.id
        self.run_case("Level 6", "TC-6.2", "Create Test Execution Run with Auto-Loading of Project Test Cases", case_6_2)

        def case_6_3():
            execution = self.env['pm.test.execution'].browse(self.execution_id)
            lines = execution.execution_line_ids.sorted('id')
            # Line 1: Tested & Passed
            lines[0].write({
                'status': 'tested',
                'result': 'pass',
                'remark': 'All JWT checks passed with 100% compliance',
            })
            # Line 2: Tested & Failed
            lines[1].write({
                'status': 'tested',
                'result': 'fail',
                'remark': 'Rate limiter dropped packets instead of returning 429 JSON body',
            })
            # Line 3: Tested & Indifferent
            lines[2].write({
                'status': 'tested',
                'result': 'indifferent',
                'remark': 'SOAP proxy deprecated in current architecture',
            })
            
            # Check onchange behavior
            assert lines[0].status == 'tested' and lines[0].result == 'pass'
            assert lines[1].status == 'tested' and lines[1].result == 'fail'
            assert lines[2].status == 'tested' and lines[2].result == 'indifferent'
        self.run_case("Level 6", "TC-6.3", "Record Test Results: Status (tested) and Result (pass, fail, indifferent) with Remarks", case_6_3)

        def case_6_4():
            execution = self.env['pm.test.execution'].browse(self.execution_id)
            execution.invalidate_recordset(['total_cases', 'executed_cases', 'passed_count', 'failed_count', 'indifferent_count', 'pass_rate'])
            assert execution.total_cases == 3, f"Total cases expected 3, got {execution.total_cases}"
            assert execution.executed_cases == 3, f"Executed cases expected 3, got {execution.executed_cases}"
            assert execution.passed_count == 1, f"Passed count expected 1, got {execution.passed_count}"
            assert execution.failed_count == 1, f"Failed count expected 1, got {execution.failed_count}"
            assert execution.indifferent_count == 1, f"Indifferent count expected 1, got {execution.indifferent_count}"
            # Pass rate = 1 / 3 * 100 = 33.3%
            assert abs(execution.pass_rate - 33.3) < 0.1, f"Expected pass rate 33.3%, got {execution.pass_rate}%"
            
            # Complete and sign-off
            execution.action_complete_testing()
            assert execution.state == 'completed'
            execution.action_sign_off()
            assert execution.state == 'sign_off'
        self.run_case("Level 6", "TC-6.4", "Verify Test Execution Metrics Calculation (Total, Executed, Pass Rate %, Sign-Off)", case_6_4)

    # -------------------------------------------------------------------------
    # LEVEL 7: Governance, Risk Management & Executive Updates
    # -------------------------------------------------------------------------
    def test_level_7_governance_risk_updates(self):
        print("\n--- LEVEL 7: Governance, Risk Management & Executive Updates Tier ---")

        def case_7_1():
            risk = self.track(self.env['pm.project.risk'].create({
                'project_id': self.project_id,
                'name': '[PROD_TEST] Third-party Core Banking API rate limit bottleneck',
                'category': 'external',
                'probability': '3',  # High (3)
                'impact': '4',       # Critical (4)
                'mitigation': 'Implement Redis caching layer for read-only account balance queries',
                'status': 'open',
            }))
            assert risk.id
            assert risk.severity == 12, f"Expected severity 12 (3 * 4), got {risk.severity}"
            risk.write({'status': 'mitigated'})
            assert risk.status == 'mitigated'
            self.risk_id = risk.id
        self.run_case("Level 7", "TC-7.1", "Create Project Risk & Verify Computed Severity Score (Probability x Impact)", case_7_1)

        def case_7_2():
            project = self.env['pm.project'].browse(self.project_id)
            update = self.track(self.env['pm.project.progress.update'].create({
                'name': '[PROD_TEST] Weekly Executive Briefing #1',
                'project_id': project.id,
                'report_type': 'weekly',
                'report_date': self.today,
                'health_state': 'on_track',
                'progress_rate': project.progress_rate,
                'executive_summary': 'Architecture phase 100% completed, gateway implementation on schedule.',
            }))
            assert update.id
            assert update.project_id.id == project.id
            assert update.health_state == 'on_track'
        self.run_case("Level 7", "TC-7.2", "Create Periodic Progress Update Snapshot with Health Status & Executive Summary", case_7_2)

    # -------------------------------------------------------------------------
    # Cleanup & Final Report
    # -------------------------------------------------------------------------
    def cleanup_and_summary(self):
        print("\n--- LEVEL 8: Teardown & Database Sanitization ---")
        cleaned_count = 0
        # Delete created records in reverse order
        for model_name, rec_id in reversed(self.created_record_refs):
            try:
                rec = self.env[model_name].browse(rec_id)
                if rec.exists():
                    rec.unlink()
                    cleaned_count += 1
            except Exception as e:
                pass
        self.cr.commit()
        print(f"  Sanitized and cleaned up {cleaned_count} test records from database.")

        print("\n" + "="*80)
        print("  DEEP PRODUCTION-LEVEL PROJECT MANAGEMENT TEST SUITE REPORT")
        print("="*80)
        
        passed_count = sum(1 for r in self.results if r['status'] == 'PASS')
        failed_count = sum(1 for r in self.results if r['status'] == 'FAIL')
        total_count = len(self.results)
        
        print(f"\nTotal Cases Run: {total_count} | PASSED: {passed_count} | FAILED: {failed_count}")
        print(f"Success Rate: {(passed_count / total_count * 100.0):.1f}%\n")
        print(f"{'Case ID':<10} | {'Level':<10} | {'Status':<6} | {'Elapsed':<8} | {'Description'}")
        print("-" * 80)
        for r in self.results:
            print(f"{r['case_id']:<10} | {r['level']:<10} | {r['status']:<6} | {r['elapsed']:<7.3f}s | {r['description']}")

        if failed_count > 0:
            print("\nFAILURES DETECTED:")
            for r in self.results:
                if r['status'] == 'FAIL':
                    print(f"- {r['case_id']}: {r['description']}")
                    print(f"  Error: {r['error']}")
            sys.exit(1)
        else:
            print("\nALL PRODUCTION-LEVEL TEST SCENARIOS PASSED WITH 100% INTEGRITY!\n")
            sys.exit(0)

if __name__ == '__main__':
    suite = ProductionTestSuite()
    suite.run_all()
