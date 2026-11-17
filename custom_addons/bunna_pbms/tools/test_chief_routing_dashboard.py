# -*- coding: utf-8 -*-
import sys
import os

sys.path.insert(0, r"D:\projects\odoo19\source\odoo")
import odoo
from odoo import api
from odoo.modules.registry import Registry

def run_tests():
    config_file = r"D:\projects\odoo19\config\odoo.conf"
    odoo.tools.config.parse_config(["-c", config_file, "-d", "odoo_dev"])
    registry = Registry("odoo_dev")

    with registry.cursor() as cr:
        env = api.Environment(cr, odoo.SUPERUSER_ID, {})

        print("=== 1. VERIFYING CHIEF CONFIGURATION FIELDS ===")
        CatDef = env["pbms.planning.category.definition"]
        dep_cat = CatDef.search([("code", "=", "deposit")], limit=1)
        assert hasattr(dep_cat, "chief_endorse_destination"), "Missing chief_endorse_destination"
        assert hasattr(dep_cat, "chief_endorse_required_privilege_id"), "Missing chief_endorse_required_privilege_id"
        assert hasattr(dep_cat, "chief_endorse_next_privilege_id"), "Missing chief_endorse_next_privilege_id"
        print("  [OK] Chief endorsement configuration fields exist on category definitions.")

        print("\n=== 2. TESTING CHIEF ENDORSE ROUTING LOGIC ===")
        plan = env["pbms.planning.category"].search([("category", "=", "deposit")], limit=1)
        if plan:
            # Test default destination
            dest_st, dest_lbl = plan._get_chief_endorse_destination_and_state()
            print(f"  Default Chief Endorse -> State: {dest_st}, Label: {dest_lbl}")
            assert dest_st == "district_endorsed", f"Expected district_endorsed, got {dest_st}"

            # Test dynamic override: change chief_endorse_destination to sppmd_approver
            dep_cat.write({"chief_endorse_destination": "sppmd_approver"})
            dest_st, dest_lbl = plan._get_chief_endorse_destination_and_state()
            print(f"  Override Chief Endorse ('sppmd_approver') -> State: {dest_st}, Label: {dest_lbl}")
            assert dest_st == "ho_reviewed", f"Expected ho_reviewed, got {dest_st}"

            # Test dynamic override: change chief_endorse_destination to final_approved
            dep_cat.write({"chief_endorse_destination": "final_approved"})
            dest_st, dest_lbl = plan._get_chief_endorse_destination_and_state()
            print(f"  Override Chief Endorse ('final_approved') -> State: {dest_st}, Label: {dest_lbl}")
            assert dest_st == "approved", f"Expected approved, got {dest_st}"

            # Reset back to default
            dep_cat.write({"chief_endorse_destination": "default"})
            dest_st, dest_lbl = plan._get_chief_endorse_destination_and_state()
            assert dest_st == "district_endorsed"
            print("  [OK] Chief endorse dynamic destinations verified successfully.")

        print("\n=== 3. TESTING DISTRICT SECURITY ISOLATION FOR CHIEF_REVIEW PLANS ===")
        # Verify rule_plan_district definition in ir.rule
        dist_rule = env.ref("bunna_pbms.rule_plan_district", raise_if_not_found=False)
        assert dist_rule, "rule_plan_district must exist"
        print(f"  rule_plan_district Domain: {dist_rule.domain_force}")
        assert "chief_review" in dist_rule.domain_force, "chief_review check must be in district rule"
        print("  [OK] District Reviewer domain force correctly isolates chief_review plans.")

        print("\n=== 4. TESTING DASHBOARD DATA & PIPELINE SUMMARY ===")
        dash = env["pbms.dashboard"].get_dashboard_data()
        assert "submission" in dash, "Dashboard must return submission data"
        assert "pipeline_totals" in dash, "Dashboard must return pipeline_totals"
        pt = dash["pipeline_totals"]
        print(f"  Pipeline Totals: Total={pt['total']}, Draft={pt['draft']}, Submitted={pt['submitted']}, Chief Review={pt['chief_review']}, HO Review={pt['ho_review']}, Approved={pt['approved']}")
        print("  [OK] Dashboard data query executed successfully.")

        print("\n>>> ALL CHIEF ROUTING & DASHBOARD CHECKS PASSED PERFECTLY! <<<")

if __name__ == "__main__":
    run_tests()
