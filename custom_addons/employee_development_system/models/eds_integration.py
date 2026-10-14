# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class EdsIntegrationLog(models.Model):
    _name = 'eds.integration.log'
    _description = 'EDS External System Integration Audit Log'
    _order = 'create_date desc'

    name = fields.Char(string='Transaction ID', required=True, default=lambda self: _('New'))
    system = fields.Selection([
        ('lms', 'Learning Management System (LMS)'),
        ('pms', 'Performance Management System (PMS)'),
        ('finance', 'Core Finance & Accounting'),
        ('payroll', 'Payroll Module'),
    ], string='Target System', required=True)
    direction = fields.Selection([
        ('inbound', 'Inbound to EDS'),
        ('outbound', 'Outbound from EDS'),
    ], string='Direction', required=True)
    payload_hash = fields.Char(string='Payload Hash / Ref')
    status = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('retry', 'Retry Queued'),
    ], string='Status', required=True, default='success')
    details = fields.Text(string='Transaction Details / Message')
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now)

class EdsLmsRouting(models.Model):
    _name = 'eds.lms.routing'
    _description = 'EDS E-Learning Course Routing to LMS'
    _inherit = ['mail.thread']

    course_id = fields.Many2one('eds.course', string='EDS Course', required=True, ondelete='cascade')
    session_id = fields.Many2one('eds.session', string='Training Session')
    delivery_mode = fields.Selection([
        ('e_learning', 'E-Learning'),
        ('blended', 'Blended (Classroom + E-Learning)'),
    ], string='Delivery Mode', required=True, default='e_learning')
    lms_ref = fields.Char(string='LMS External Course ID / Ref')
    sync_state = fields.Selection([
        ('pending', 'Pending Sync'),
        ('synced', 'Synced to LMS'),
        ('error', 'Sync Error'),
    ], string='Sync State', default='pending', tracking=True)
    lms_completion_pct = fields.Float(string='LMS Completion Rate (%)', default=0.0)
    last_sync_date = fields.Datetime(string='Last Sync Date')
    sync_error = fields.Text(string='Last Sync Error', readonly=True)

    def action_sync_to_lms(self):
        for rec in self:
            if not self.env.registry.get('lms.course'):
                raise UserError(_('Install Learning Management before syncing EDS courses.'))
            if not self.env.user.has_group('employee_development_system.group_eds_manager') and not self.env.su:
                raise UserError(_('Only an EDS manager may sync courses to LMS.'))
            try:
                with self.env.cr.savepoint():
                    self.env.cr.execute('SELECT id FROM eds_lms_routing WHERE id = %s FOR UPDATE', (rec.id,))
                    category = self.env['lms.category'].sudo().search([('code', '=', 'EDS_IMPORT')], limit=1)
                    if not category:
                        category = self.env['lms.category'].sudo().create({
                            'name': _('EDS Routed Courses'), 'code': 'EDS_IMPORT',
                        })
                    instructor = rec.course_id.create_uid.employee_id or self.env.user.employee_id
                    if not instructor:
                        raise UserError(_('Assign an employee account to the course owner before LMS sync.'))
                    values = {
                        'name': rec.course_id.name,
                        'category_id': category.id,
                        'description': rec.course_id.description or rec.course_id.name,
                        'instructor_id': instructor.id,
                        'estimated_duration_hours': (rec.course_id.duration_days or 1) * 8,
                        'target_department_ids': [(6, 0, rec.course_id.department_ids.ids)],
                        'target_job_ids': [(6, 0, rec.course_id.target_audience_ids.ids)],
                    }
                    lms_course = self.env['lms.course'].sudo().browse(
                        int(rec.lms_ref) if rec.lms_ref and rec.lms_ref.isdigit() else 0
                    ).exists()
                    if lms_course:
                        if lms_course.state == 'draft':
                            lms_course.write(values)
                    else:
                        lms_course = self.env['lms.course'].sudo().create(values)
                    rec._sync_lms_enrollments(lms_course)
                    rec.write({
                        'lms_ref': str(lms_course.id),
                        'sync_state': 'synced',
                        'sync_error': False,
                        'last_sync_date': fields.Datetime.now(),
                    })
                    self.env['eds.integration.log'].sudo().create({
                        'name': f'LMS-SYNC-{rec.course_id.code}',
                        'system': 'lms', 'direction': 'outbound', 'status': 'success',
                        'details': _('EDS course %s synced to LMS course %s.') % (rec.course_id.name, lms_course.code),
                    })
            except Exception as exc:
                _logger.exception('EDS to LMS synchronization failed for routing %s', rec.id)
                rec.write({'sync_state': 'error', 'sync_error': str(exc)})
                self.env['eds.integration.log'].sudo().create({
                    'name': f'LMS-SYNC-{rec.course_id.code}',
                    'system': 'lms', 'direction': 'outbound', 'status': 'failed',
                    'details': str(exc),
                })

    def _sync_lms_enrollments(self, lms_course):
        self.ensure_one()
        if not self.session_id:
            return 0
        Enrollment = self.env['lms.enrollment'].sudo()
        created = 0
        for eds_enrollment in self.session_id.enrollment_ids.filtered(
            lambda enrollment: enrollment.state in ('enrolled', 'completed')
        ):
            existing = Enrollment.search([
                ('course_id', '=', lms_course.id),
                ('employee_id', '=', eds_enrollment.employee_id.id),
            ], limit=1)
            if existing:
                continue
            Enrollment.create({
                'course_id': lms_course.id,
                'employee_id': eds_enrollment.employee_id.id,
                'is_mandatory': self.course_id.category == 'technical_compliance',
                'due_date': fields.Date.to_date(self.session_id.date_end) if self.session_id.date_end else False,
            })
            created += 1
        return created

    def action_sync_assignments(self):
        if not self.env.su and not self.env.user.has_group('employee_development_system.group_eds_manager'):
            raise UserError(_('Only an EDS manager may sync LMS participants.'))
        for rec in self:
            if not rec.lms_ref or not rec.lms_ref.isdigit():
                raise UserError(_('Sync the EDS course to LMS first.'))
            lms_course = self.env['lms.course'].sudo().browse(int(rec.lms_ref)).exists()
            if not lms_course:
                raise UserError(_('The linked LMS course no longer exists.'))
            count = rec._sync_lms_enrollments(lms_course)
            rec.action_reconcile_lms()
            rec.message_post(body=_('%d participant(s) enrolled in LMS.') % count)

    def action_reconcile_lms(self):
        """Refresh completion metrics from the actual linked LMS enrollment records."""
        if not self.env.registry.get('lms.enrollment'):
            return
        for rec in self:
            if not rec.lms_ref or not rec.lms_ref.isdigit():
                continue
            course_id = int(rec.lms_ref)
            Enrollment = self.env['lms.enrollment'].sudo()
            domain = [('course_id', '=', course_id)]
            if rec.session_id:
                employee_ids = rec.session_id.enrollment_ids.filtered(
                    lambda enrollment: enrollment.state in ('enrolled', 'completed')
                ).mapped('employee_id').ids
                domain.append(('employee_id', 'in', employee_ids))
            total = Enrollment.search_count(domain)
            completed = Enrollment.search_count(domain + [('state', '=', 'completed')])
            rec.sudo().write({'lms_completion_pct': 100.0 * completed / total if total else 0.0})

class EdsPayrollPayload(models.Model):
    _name = 'eds.payroll.payload'
    _description = 'EDS Payroll Cost Recovery / Deduction Payload'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Payload Reference', required=True, default=lambda self: _('New'))
    payload_type = fields.Selection([
        ('cost_recovery', 'Training Cost Recovery'),
        ('sponsorship_recovery', 'Sponsorship Bond Breach Recovery'),
    ], string='Payload Type', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(string='Recovery Amount', currency_field='currency_id', required=True, tracking=True)
    effective_date = fields.Date(string='Effective Payroll Date', default=fields.Date.context_today, required=True)
    source_ref = fields.Char(string='Source Record Ref (Sponsorship / Course)', required=True)
    waiver_authority = fields.Text(string='CEO Waiver Authority Notes')
    state = fields.Selection([
        ('pending', 'Pending Transfer to Payroll'),
        ('transferred', 'Transferred to Payroll'),
        ('processed', 'Processed / Deducted'),
    ], string='Status', default='pending', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.payroll.payload') or _('New')
        return super(EdsPayrollPayload, self).create(vals_list)

    def action_transfer_to_payroll(self):
        for rec in self:
            rec.state = 'transferred'
            self.env['eds.integration.log'].create({
                'name': f"PAYROLL-PAYLOAD-{rec.name}",
                'system': 'payroll',
                'direction': 'outbound',
                'status': 'success',
                'details': f"Cost recovery payload {rec.name} for {rec.employee_id.name} ({rec.amount}) transferred to Payroll queue.",
            })
