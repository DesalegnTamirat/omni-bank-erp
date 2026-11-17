# -*- coding: utf-8 -*-
import sys
import os

# Initialize Odoo environment
sys.path.insert(0, r"D:\projects\odoo19\source\odoo")
import odoo
from odoo import api

config_file = r"D:\projects\odoo19\config\odoo.conf"
odoo.tools.config.parse_config(["-c", config_file, "-d", "odoo_dev"])

def run_tests():
    from odoo.modules.registry import Registry
    registry = Registry("odoo_dev")
    with registry.cursor() as cr:
        env = api.Environment(cr, odoo.SUPERUSER_ID, {})

        print("=== 1. VERIFYING PLANNING CATEGORIES ===")
        CatDef = env["pbms.planning.category.definition"]
        categories = CatDef.search([])
        print(f"Total Configured Planning Categories: {len(categories)}")
        expected_cats = [
            "deposit", "customer_base", "fx", "digital_banking",
            "general_expense", "manpower", "fixed_asset",
            "loan_disbursement_collection", "loan_outstanding",
            "credit_portfolio", "initiative_budget",
        ]
        cat_codes = categories.mapped("code")
        for exp in expected_cats:
            assert exp in cat_codes, f"Missing category: {exp}"
            cat_rec = CatDef.search([("code", "=", exp)], limit=1)
            print(f"  [OK] Category: {cat_rec.name} ({cat_rec.code}), Measurement: {cat_rec.measurement_type}, Workflow: {cat_rec.workflow_id.name if cat_rec.workflow_id else 'None'}")

        print("\n=== 2. VERIFYING PRIVILEGES ===")
        Priv = env["pbms.privilege"]
        privileges = Priv.search([])
        print(f"Total Privileges: {len(privileges)}")
        assert len(privileges) >= 18, f"Expected at least 18 privileges, found {len(privileges)}"
        for p in privileges:
            print(f"  [OK] Privilege: {p.name} ({p.code}) -> Action: {p.action_type}")

        print("\n=== 3. VERIFYING ROLES ===")
        Role = env["pbms.role.definition"]
        roles = Role.search([])
        print(f"Total Roles: {len(roles)}")
        assert len(roles) >= 10, f"Expected at least 10 roles, found {len(roles)}"
        for r in roles:
            print(f"  [OK] Role: {r.name} ({r.code}), Org Level: {r.org_level}, Privileges: {len(r.privilege_ids)}")

        print("\n=== 4. VERIFYING WORKFLOW DEFINITIONS ===")
        Wf = env["pbms.workflow.definition"]
        workflows = Wf.search([])
        print(f"Total Workflows: {len(workflows)}")
        assert len(workflows) >= 4, f"Expected at least 4 workflows, found {len(workflows)}"
        for wf in workflows:
            print(f"  Workflow: {wf.name} ({wf.code}) - Steps: {len(wf.step_ids)}")
            for step in wf.step_ids:
                print(f"    - Step: {step.sequence}. {step.name} [State: {step.state}, Editable: {step.can_edit_content}, Transitions: {len(step.transition_ids)}]")

        print("\n=== 5. VERIFYING DYNAMIC WORKFLOW ENGINE MIXIN ===")
        # Test on a dummy plan or existing plan
        Plan = env["pbms.planning.category"]
        test_plan = Plan.search([("category", "=", "deposit")], limit=1)
        if not test_plan:
            test_plan = Plan.search([], limit=1)
        if test_plan:
            wf = test_plan._get_active_workflow()
            print(f"  Plan: {test_plan.display_name} (Category: {test_plan.category})")
            print(f"  Active Workflow: {wf.name if wf else 'None'}")
            step = test_plan._get_current_workflow_step()
            print(f"  Current Step: {step.name if step else 'None'} [State: {test_plan.state}]")
            dyn_submit = test_plan._check_dynamic_privilege("submit")
            print(f"  Dynamic Submit Privilege: {dyn_submit}")

        print("\n=== 6. VERIFYING DYNAMIC EXTENSIBILITY (CREATE NEW CATEGORY VIA CONFIG) ===")
        test_cat_code = "strategic_investment"
        existing = CatDef.search([("code", "=", test_cat_code)])
        if existing:
            existing.unlink()

        # Admin creates new category dynamically
        new_cat = CatDef.create({
            "name": "Strategic Investment",
            "code": test_cat_code,
            "measurement_type": "monetary",
            "icon": "fa-line-chart",
            "is_consolidable": True,
            "workflow_id": env.ref("bunna_pbms.wf_resources").id,
        })
        print(f"  [OK] Dynamically Created Category: {new_cat.name} ({new_cat.code}) with Workflow: {new_cat.workflow_id.name}")
        retrieved = CatDef.get_category_by_code(test_cat_code)
        assert retrieved.id == new_cat.id, "Category retrieval by code failed"

        # Clean up test category
        new_cat.unlink()
        print("  [OK] Cleaned up test dynamic category successfully.")

        print("\n=== 7. VERIFYING MENUS REGISTERED ===")
        Menu = env["ir.ui.menu"]
        menu_items = [
            "bunna_pbms.menu_pbms_config_categories",
            "bunna_pbms.menu_pbms_config_privileges",
            "bunna_pbms.menu_pbms_config_roles",
            "bunna_pbms.menu_pbms_config_workflows",
            "bunna_pbms.menu_pbms_config_category_workflow_map",
            "bunna_pbms.menu_pbms_config_workflow_steps",
            "bunna_pbms.menu_pbms_config_privilege_assignments",
        ]
        for m_xmlid in menu_items:
            m = env.ref(m_xmlid, raise_if_not_found=False)
            assert m, f"Missing menu: {m_xmlid}"
            print(f"  [OK] Menu Item: {m.name} -> Action: {m.action.name if m.action else 'None'}")

        print("\n>>> ALL 7 TEST SUITES PASSED PERFECTLY! <<<")

if __name__ == "__main__":
    run_tests()
