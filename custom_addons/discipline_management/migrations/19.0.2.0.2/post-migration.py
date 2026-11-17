# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    """
    Ensure base.group_user (Internal User) implies group_discipline_user
    and backfill User / Employee baseline to all internal bank users.
    """
    _logger.info("Migrating discipline_management to %s: auto-granting User / Employee baseline to internal users", version)
    
    # 1. Ensure implied relationship exists in res_groups_implied_rel
    cr.execute("""
        INSERT INTO res_groups_implied_rel (gid, hid)
        SELECT b.res_id, d.res_id
        FROM ir_model_data b, ir_model_data d
        WHERE b.module = 'base' AND b.name = 'group_user'
          AND d.module = 'discipline_management' AND d.name = 'group_discipline_user'
        ON CONFLICT DO NOTHING;
    """)
    
    # 2. Backfill group_discipline_user to all existing internal users
    cr.execute("""
        INSERT INTO res_groups_users_rel (gid, uid)
        SELECT d.res_id, r.uid
        FROM ir_model_data d
        JOIN res_groups_users_rel r ON r.gid = (
            SELECT res_id FROM ir_model_data WHERE module = 'base' AND name = 'group_user' LIMIT 1
        )
        WHERE d.module = 'discipline_management' AND d.name = 'group_discipline_user'
          AND NOT EXISTS (
              SELECT 1 FROM res_groups_users_rel x 
              WHERE x.gid = d.res_id AND x.uid = r.uid
          );
    """)
    _logger.info("discipline_management post-migration complete: %d internal users updated.", cr.rowcount)
