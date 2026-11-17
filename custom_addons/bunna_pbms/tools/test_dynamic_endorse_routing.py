import os
import sys

sys.path.insert(0, r"d:\projects\odoo19\source\odoo")
import odoo
from odoo import api, SUPERUSER_ID

def main():
    config_file = r"d:\projects\odoo19\config\odoo.conf"
    odoo.tools.config.parse_config(["-c", config_file, "-d", "odoo_dev"])

    from odoo.modules.registry import Registry
    registry = Registry("odoo_dev")
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        print("--- 1. Testing Category Definition Routing Fields ---")
        deposit_cat = env["pbms.planning.category.definition"].search([("code", "=", "deposit")], limit=1)
        assert deposit_cat, "Deposit category definition must exist"
        print(f"Deposit Category: {deposit_cat.name}")
        print(f"  Branch Submit Dest: {deposit_cat.branch_submission_destination}")
        print(f"  District Endorse Dest: {deposit_cat.district_endorse_destination}")
        print(f"  District Approve Dest: {deposit_cat.district_approve_destination}")
        print(f"  HO Approve Dest: {deposit_cat.ho_approve_destination}")

        # Check default values
        assert deposit_cat.district_endorse_destination == "default"
        assert deposit_cat.district_approve_destination == "default"
        assert deposit_cat.ho_approve_destination == "default"

        print("--- 2. Testing Dynamic District Endorse & Approve Routing Methods ---")
        # Find a test district plan
        dist_plan = env["pbms.planning.category"].search([("is_district_unit", "=", True), ("category", "=", "deposit")], limit=1)
        if not dist_plan:
            dist_plan = env["pbms.planning.category"].search([("category", "=", "deposit")], limit=1)

        if dist_plan:
            # Default endorse destination
            dest_state, dest_label = dist_plan._get_district_endorse_destination_and_state()
            print(f"Default District Endorse -> State: {dest_state}, Label: {dest_label}")
            assert dest_state == "district_endorsed", f"Expected district_endorsed, got {dest_state}"

            # Test dynamic override: change district_endorse_destination to respective_chief
            deposit_cat.write({"district_endorse_destination": "respective_chief"})
            dest_state, dest_label = dist_plan._get_district_endorse_destination_and_state()
            print(f"Override District Endorse ('respective_chief') -> State: {dest_state}, Label: {dest_label}")
            assert dest_state == "chief_review", f"Expected chief_review, got {dest_state}"

            # Test dynamic override: change district_endorse_destination to sppmd_approver
            deposit_cat.write({"district_endorse_destination": "sppmd_approver"})
            dest_state, dest_label = dist_plan._get_district_endorse_destination_and_state()
            print(f"Override District Endorse ('sppmd_approver') -> State: {dest_state}, Label: {dest_label}")
            assert dest_state == "ho_reviewed", f"Expected ho_reviewed, got {dest_state}"

            # Reset back to default
            deposit_cat.write({"district_endorse_destination": "default"})
            dest_state, dest_label = dist_plan._get_district_endorse_destination_and_state()
            assert dest_state == "district_endorsed", f"Expected district_endorsed after reset, got {dest_state}"
            print("Reset to default verified successfully.")

        print("--- 3. Testing Dynamic Privilege Checks on res.users ---")
        admin_user = env.ref("base.user_admin")
        assert admin_user._pbms_has_dynamic_privilege("district_endorse") == True
        assert admin_user._pbms_has_dynamic_privilege("ho_approve") == True
        print("Admin user dynamic privilege verified.")

        # Test with a non-admin user
        test_user = env["res.users"].search([("id", "!=", SUPERUSER_ID), ("active", "=", True)], limit=1)
        if test_user:
            # Check dynamic role or privilege assignment
            role_ho = env.ref("bunna_pbms.role_ho_reviewer", raise_if_not_found=False)
            priv_end = env.ref("bunna_pbms.priv_district_endorse", raise_if_not_found=False)
            print(f"Test user: {test_user.login}")
            print(f"Role HO exists: {bool(role_ho)}, Priv Endorse exists: {bool(priv_end)}")

        print("--- ALL DYNAMIC ENDORSEMENT & APPROVAL ROUTING CHECKS PASSED ---")

if __name__ == "__main__":
    main()
