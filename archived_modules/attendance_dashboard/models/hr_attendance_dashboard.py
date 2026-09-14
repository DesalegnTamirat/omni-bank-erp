# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import api, models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    # ------------------------------------------------------------------
    # Public entry point (called by the OWL client action)
    # ------------------------------------------------------------------
    @api.model
    def get_attendance_dashboard(self, filter_type='today'):
        """Aggregate KPI/chart data for the Attendance Dashboard client action.

        Kept as a handful of small, parameterized raw-SQL aggregate queries
        (rather than ORM search/read_group) on purpose: this is called on
        every dashboard load and every filter change, and only ever needs
        plain counts and group-bys, never full records, so going straight
        to SQL avoids building/unpacking recordsets for data we'd never
        read as records anyway.
        """
        today = date.today()
        start_date, end_date = self._dashboard_date_range(filter_type, today)

        cr = self.env.cr

        total = self._dashboard_total_employees(cr)
        present, late = self._dashboard_present_and_late(cr, start_date, end_date)
        leave = self._dashboard_on_leave(cr, start_date, end_date)
        absent = max(0, total - present - leave)

        return {
            'today': today.strftime('%A, %B %d, %Y'),
            'kpi': {
                'total': total,
                'present': present,
                'late': late,
                'leave': leave,
                'absent': absent,
            },
            'progress': self._dashboard_progress(cr, filter_type, start_date, end_date),
            'workunit': self._dashboard_workunit_breakdown(cr, start_date, end_date),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _dashboard_date_range(self, filter_type, today):
        if filter_type == 'yesterday':
            yesterday = today - timedelta(days=1)
            return yesterday, yesterday
        if filter_type == 'this_week':
            return today - timedelta(days=today.weekday()), today
        if filter_type == 'this_month':
            return today.replace(day=1), today
        if filter_type == 'this_year':
            return today.replace(month=1, day=1), today
        # 'today' and any unknown value both fall back to today only.
        return today, today

    def _dashboard_total_employees(self, cr):
        cr.execute("""
            SELECT COUNT(*)
            FROM hr_employee he
            JOIN hr_contract hc ON he.id = hc.employee_id
            WHERE hc.active = true
        """)
        return cr.fetchone()[0] or 0

    def _dashboard_present_and_late(self, cr, start_date, end_date):
        # One pass over hr_attendance instead of two separate full scans.
        cr.execute("""
            SELECT
                COUNT(DISTINCT employee_id),
                COUNT(DISTINCT employee_id) FILTER (WHERE check_in_status = 'Late')
            FROM hr_attendance
            WHERE check_in::date BETWEEN %s AND %s
        """, (start_date, end_date))
        present, late = cr.fetchone()
        return present or 0, late or 0

    def _dashboard_on_leave(self, cr, start_date, end_date):
        cr.execute("""
            SELECT COUNT(DISTINCT employee_id)
            FROM hr_leave
            WHERE state = 'validate'
              AND date_from::date <= %s
              AND date_to::date >= %s
        """, (end_date, start_date))
        return cr.fetchone()[0] or 0

    def _dashboard_progress(self, cr, filter_type, start_date, end_date):
        if filter_type in ('today', 'yesterday'):
            cr.execute("""
                SELECT TO_CHAR(check_in, 'HH24:00'), COUNT(DISTINCT employee_id)
                FROM hr_attendance
                WHERE check_in::date = %s
                GROUP BY 1
                ORDER BY 1
            """, (start_date,))
        else:
            cr.execute("""
                SELECT TO_CHAR(check_in, 'Mon DD'), COUNT(DISTINCT employee_id)
                FROM hr_attendance
                WHERE check_in::date BETWEEN %s AND %s
                GROUP BY check_in::date, 1
                ORDER BY MIN(check_in)
            """, (start_date, end_date))
        return [{'label': label, 'count': count} for label, count in cr.fetchall()]

    def _dashboard_workunit_breakdown(self, cr, start_date, end_date):
        cr.execute("""
            SELECT
                CASE
                    WHEN ou.work_unit_type = 'head_office' THEN ou.work_unit_type
                    WHEN ou.work_unit_type IN ('area_office', 'district_office') THEN ou.name
                    WHEN ou.work_unit_type = 'branch' THEN pou.name
                    ELSE 'Other'
                END AS unit,
                COUNT(DISTINCT a.employee_id)
            FROM hr_attendance a
            JOIN hr_employee e ON a.employee_id = e.id
            JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
            LEFT JOIN operating_unit pou ON ou.parent_unit = pou.id
            WHERE a.check_in::date BETWEEN %s AND %s
            GROUP BY unit
            ORDER BY 2 DESC
        """, (start_date, end_date))
        return [{'unit': unit, 'count': count} for unit, count in cr.fetchall()]
