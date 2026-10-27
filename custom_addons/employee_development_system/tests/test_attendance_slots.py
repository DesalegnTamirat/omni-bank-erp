# -*- coding: utf-8 -*-
import base64
import io

from openpyxl import load_workbook
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds_attendance_slots')
class TestAttendanceSlots(TransactionCase):

    def test_accepted_roster_and_same_clock_multiday_export(self):
        calendar = self.env.company.resource_calendar_id
        if calendar:
            calendar.tz = 'UTC'
        self.env.user.tz = 'UTC'
        course = self.env['eds.course'].create({'name': 'Draft split roster course'})
        included, excluded = self.env['hr.employee'].create([
            {'name': 'Included draft employee'}, {'name': 'Excluded draft employee'},
        ])
        session = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2098-05-01 10:00:00',
            'date_end': '2098-05-02 10:00:00',
            'start_time': 8.5, 'duration_hours': 8.0,
            'attendance_mode': 'split',
        })
        self.env['eds.enrollment'].create([
            {'session_id': session.id, 'employee_id': included.id,
             'state': 'enrolled', 'selected': True},
            {'session_id': session.id, 'employee_id': excluded.id,
             'state': 'suggested', 'selected': False},
        ])
        self.assertEqual([(day.isoformat(), slot) for day, slot, _hours
                          in session._attendance_slots()], [
                              ('2098-05-01', 'morning'), ('2098-05-01', 'afternoon'),
                              ('2098-05-02', 'morning'), ('2098-05-02', 'afternoon'),
                          ])
        action = session.action_export_attendance_xlsx()
        attachment_id = int(action['url'].split('/')[3].split('?')[0])
        workbook = load_workbook(io.BytesIO(base64.b64decode(
            self.env['ir.attachment'].browse(attachment_id).datas)))
        sheet = workbook.active
        self.assertEqual(sheet['B6'].value, 'Morning and Afternoon')
        self.assertEqual([sheet.cell(6, column).value for column in range(6, 10)],
                         ['Morning', 'Afternoon', 'Morning', 'Afternoon'])
        self.assertEqual(sheet['B8'].value, included.name)
        self.assertIsNone(sheet['B9'].value)
        sheet['F8'] = 'Present'
        output = io.BytesIO()
        workbook.save(output)
        wizard = self.env['eds.attendance.import'].create({
            'session_id': session.id,
            'csv_file': base64.b64encode(output.getvalue()),
            'filename': 'draft_split_roster.xlsx',
        })
        wizard.action_import_attendance()
        self.assertEqual(self.env['eds.session.attendance'].search_count([
            ('session_id', '=', session.id), ('employee_id', '=', included.id),
            ('attendance_slot', '=', 'morning'), ('attended', '=', True),
        ]), 1)

    def test_multiday_schedule_excludes_overnight_hours(self):
        calendar = self.env.company.resource_calendar_id
        if calendar:
            calendar.tz = 'UTC'
        self.env.user.tz = 'UTC'
        course = self.env['eds.course'].create({'name': 'Partial day course'})
        session = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2098-05-01 09:00:00',
            'date_end': '2098-05-02 17:00:00',
            'attendance_mode': 'split',
        })
        self.assertEqual(session._attendance_slots(), [
            (session.date_start.date(), 'morning', 3.0),
            (session.date_start.date(), 'afternoon', 5.0),
            (session.date_end.date(), 'morning', 3.0),
            (session.date_end.date(), 'afternoon', 5.0),
        ])

    def test_date_only_plan_schedule_uses_daily_duration(self):
        calendar = self.env.company.resource_calendar_id
        if calendar:
            calendar.tz = 'UTC'
        self.env.user.tz = 'UTC'
        course = self.env['eds.course'].create({'name': 'Date only planned course'})
        session = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2098-05-01 00:00:00',
            'date_end': '2098-05-02 00:00:00',
            'start_time': 8.5, 'duration_hours': 16.0,
            'attendance_mode': 'split',
        })
        self.assertEqual([(slot, hours) for _day, slot, hours in session._attendance_slots()], [
            ('morning', 3.5), ('afternoon', 4.5),
            ('morning', 3.5), ('afternoon', 4.5),
        ])
        one_day = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2098-05-03 00:00:00',
            'date_end': '2098-05-03 00:00:00',
            'start_time': 8.5, 'duration_hours': 8.0,
            'attendance_mode': 'split',
        })
        self.assertEqual([slot for _day, slot, _hours in one_day._attendance_slots()],
                         ['morning', 'afternoon'])

    def test_csv_import_keeps_same_date_periods_separate(self):
        calendar = self.env.company.resource_calendar_id
        if calendar:
            calendar.tz = 'UTC'
        self.env.user.tz = 'UTC'
        course = self.env['eds.course'].create({'name': 'CSV split course'})
        employee = self.env['hr.employee'].create({
            'name': 'CSV split participant', 'identification_id': 'CSV-SPLIT-001',
        })
        session = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2098-05-01 09:00:00',
            'date_end': '2098-05-01 17:00:00',
            'attendance_mode': 'split',
        })
        self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': employee.id, 'state': 'enrolled',
        })
        csv_text = (
            'session_ref,employee_badge,attendance_date,attendance_slot,attended,notes\n'
            f'{session.name},CSV-SPLIT-001,2098-05-01,morning,Present,\n'
            f'{session.name},CSV-SPLIT-001,2098-05-01,afternoon,Absent,\n'
        )
        wizard = self.env['eds.attendance.import'].create({
            'session_id': session.id,
            'csv_file': base64.b64encode(csv_text.encode()),
            'filename': 'split.csv',
        })
        wizard.action_import_attendance()
        marks = self.env['eds.session.attendance'].search([
            ('session_id', '=', session.id), ('employee_id', '=', employee.id),
        ])
        self.assertEqual(len(marks), 2)
        self.assertEqual(set(marks.mapped('attendance_slot')), {'morning', 'afternoon'})
        self.assertEqual(len(marks.filtered('attended')), 1)
        self.assertEqual(set(marks.mapped('attendance_percentage')), {50.0})

    def test_split_day_export_import_and_same_day_other_session(self):
        calendar = self.env.company.resource_calendar_id
        if calendar:
            calendar.tz = 'UTC'
        self.env.user.tz = 'UTC'
        course = self.env['eds.course'].create({'name': 'Split day attendance course'})
        employees = self.env['hr.employee'].create([
            {'name': 'Morning participant'}, {'name': 'Afternoon participant'},
        ])
        session = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2098-05-01 09:00:00',
            'date_end': '2098-05-01 17:00:00',
            'attendance_mode': 'split',
        })
        for employee in employees:
            self.env['eds.enrollment'].create({
                'session_id': session.id, 'employee_id': employee.id,
                'state': 'enrolled',
            })
        self.assertEqual([(day.isoformat(), slot) for day, slot, _hours
                          in session._attendance_slots()], [
                              ('2098-05-01', 'morning'),
                              ('2098-05-01', 'afternoon'),
                          ])
        action = session.action_export_attendance_xlsx()
        attachment_id = int(action['url'].split('/')[3].split('?')[0])
        workbook = load_workbook(io.BytesIO(base64.b64decode(
            self.env['ir.attachment'].browse(attachment_id).datas)))
        sheet = workbook.active
        self.assertEqual([sheet['F6'].value, sheet['G6'].value],
                         ['Morning', 'Afternoon'])
        self.assertEqual(len(sheet.data_validations.dataValidation), 2)
        rows = {sheet.cell(row, 1).value: row for row in (8, 9)}
        self.assertEqual(set(rows), set(employees.ids))
        self.assertFalse(sheet.cell(rows[employees[0].id], 6).protection.locked)
        for employee in employees:
            row = rows[employee.id]
            sheet.cell(row, 6, 'Present')
            sheet.cell(row, 7, 'Absent' if employee == employees[0] else 'Present')
        output = io.BytesIO()
        workbook.save(output)
        wizard = self.env['eds.attendance.import'].create({
            'session_id': session.id,
            'csv_file': base64.b64encode(output.getvalue()),
            'filename': 'split_attendance.xlsx',
        })
        wizard.action_import_attendance()
        records = self.env['eds.session.attendance'].search([
            ('session_id', '=', session.id),
        ])
        self.assertEqual(len(records), 4)
        first = records.filtered(lambda row: row.employee_id == employees[0])
        self.assertEqual(set(first.mapped('attendance_slot')), {'morning', 'afternoon'})
        self.assertEqual(first.filtered('attended').hours_attended, 3.0)
        self.assertEqual(first.filtered(lambda row: not row.attended).hours_attended, 0.0)
        self.assertEqual(first[0].attendance_percentage, 50.0)
        with self.assertRaises(UserError):
            session.attendance_mode = 'daily'

        other = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2098-05-01 09:00:00',
            'date_end': '2098-05-01 11:00:00',
        })
        self.env['eds.enrollment'].create({
            'session_id': other.id, 'employee_id': employees[0].id,
            'state': 'enrolled',
        })
        self.env['eds.session.attendance'].create({
            'session_id': other.id, 'employee_id': employees[0].id,
            'attendance_date': '2098-05-01', 'attendance_slot': 'day',
            'attended': True,
        })
        self.assertEqual(self.env['eds.session.attendance'].search_count([
            ('employee_id', '=', employees[0].id),
            ('attendance_date', '=', '2098-05-01'),
        ]), 3)
        self.assertEqual(set(first.mapped('attendance_percentage')), {50.0})
        with self.assertRaises(ValidationError):
            self.env['eds.session.attendance'].create({
                'session_id': session.id, 'employee_id': employees[0].id,
                'attendance_date': '2098-05-01', 'attendance_slot': 'day',
            })
