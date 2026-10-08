import logging
_logger = logging.getLogger(__name__)


def assign_resl_groups(env):
    """
    Post-install hook: ensure every hr.employee-linked user is in the
    base employee group so they can access their own loan records.
    Extend this function to assign additional groups as needed.
    """
    try:
        employee_group = env.ref('resl.group_resl_employee', raise_if_not_found=False)
        if not employee_group:
            _logger.warning('assign_resl_groups: group_resl_employee not found, skipping.')
            return
        # Add all users that have an employee record to the base group
        employees = env['hr.employee'].sudo().search([('user_id', '!=', False)])
        for emp in employees:
            if emp.user_id and employee_group not in emp.user_id.group_ids:
                emp.user_id.sudo().write({'group_ids': [(4, employee_group.id)]})
        _logger.info('assign_resl_groups: assigned group_resl_employee to %d users.', len(employees))
    except Exception:
        _logger.exception('assign_resl_groups: failed to assign groups.')