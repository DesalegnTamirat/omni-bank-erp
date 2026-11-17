# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from .eds_employee_projection import safe_employee_web_read
import logging

_logger = logging.getLogger(__name__)

class EdsIntegrationLog(models.Model):
    _name = 'eds.integration.log'
    _description = 'EDS External System Integration Audit Log'
    _order = 'create_date desc, id desc'

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
        ('recorded', 'Handoff Recorded'),
        ('failed', 'Failed'),
        ('retry', 'Retry Queued'),
    ], string='Status', required=True, default='success')
    details = fields.Text(string='Transaction Details / Message')
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now)

class EdsLmsRouting(models.Model):
    _name = 'eds.lms.routing'
    _description = 'EDS E-Learning Course Routing to LMS'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    course_id = fields.Many2one('eds.course', string='EDS Course', required=True, ondelete='cascade')
    curriculum_id = fields.Many2one('eds.curriculum', string='Approved Curriculum', ondelete='set null')
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

    def _lms_course_lineage_ids(self, lms_course):
        """Return this version and its predecessors for existing learner links."""
        lineage = []
        seen = set()
        while lms_course and lms_course.id not in seen:
            lineage.append(lms_course.id)
            seen.add(lms_course.id)
            lms_course = lms_course.previous_version_id
        return lineage

    def _resolve_lms_course(self):
        """Find the published successor of the course stored on this route."""
        self.ensure_one()
        Course = self.env['lms.course'].sudo().with_context(active_test=False)
        course = Course.browse(
            int(self.lms_ref) if self.lms_ref and self.lms_ref.isdigit() else 0
        ).exists()
        if not course or (course.state == 'published' and course.is_latest_version and course.active):
            return course
        frontier = course
        visited = {course.id}
        latest = Course.browse()
        while frontier:
            successors = Course.search([('previous_version_id', 'in', frontier.ids)])
            successors = successors.filtered(lambda successor: successor.id not in visited)
            if not successors:
                break
            current = successors.filtered(
                lambda successor: successor.state == 'published'
                and successor.is_latest_version and successor.active
            )
            if len(current) > 1:
                raise UserError(_('Multiple published LMS successors exist for this EDS route.'))
            if current:
                latest = current
            visited.update(successors.ids)
            frontier = successors
        return latest or course

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
                    lms_course = rec._resolve_lms_course()
                    if lms_course:
                        if lms_course.state == 'draft':
                            lms_course.write(values)
                    else:
                        lms_course = self.env['lms.course'].sudo().create(values)
                    # EDS creates an LMS draft shell. Publishing its reviewed
                    # lessons is the gate for participant notification.
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
        if (lms_course.state != 'published' or not lms_course.is_latest_version
                or not lms_course.active):
            return 0
        Enrollment = self.env['lms.enrollment'].sudo()
        lineage_ids = self._lms_course_lineage_ids(lms_course)
        created = 0
        for eds_enrollment in self.session_id.enrollment_ids.filtered(
            lambda enrollment: enrollment.state in ('enrolled', 'completed')
        ):
            linked = Enrollment.browse(
                int(eds_enrollment.lms_enrollment_ref)
                if eds_enrollment.lms_enrollment_ref and eds_enrollment.lms_enrollment_ref.isdigit()
                else 0
            ).exists()
            if linked and (linked.course_id.id not in lineage_ids or
                           linked.employee_id != eds_enrollment.employee_id):
                linked = Enrollment.browse()
            if linked:
                continue
            existing = Enrollment.search([
                ('course_id', '=', lms_course.id),
                ('employee_id', '=', eds_enrollment.employee_id.id),
                ('state', 'in', ('enrolled', 'in_progress')),
            ], order='attempt_number desc, id desc', limit=1)
            if existing:
                eds_enrollment.sudo().lms_enrollment_ref = str(existing.id)
                continue
            lms_enrollment = Enrollment.create({
                'course_id': lms_course.id,
                'employee_id': eds_enrollment.employee_id.id,
                'is_mandatory': self.course_id.category == 'technical_compliance',
                'due_date': fields.Date.to_date(self.session_id.date_end) if self.session_id.date_end else False,
            })
            eds_enrollment.sudo().lms_enrollment_ref = str(lms_enrollment.id)
            created += 1
        return created

    def action_sync_assignments(self):
        if not self.env.su and not self.env.user.has_group('employee_development_system.group_eds_manager'):
            raise UserError(_('Only an EDS manager may sync LMS participants.'))
        for rec in self:
            if not rec.lms_ref or not rec.lms_ref.isdigit():
                raise UserError(_('Sync the EDS course to LMS first.'))
            lms_course = rec._resolve_lms_course()
            if not lms_course:
                raise UserError(_('The linked LMS course no longer exists.'))
            if (lms_course.state != 'published' or not lms_course.is_latest_version
                    or not lms_course.active):
                raise UserError(_('Publish the current LMS course before syncing participants.'))
            if rec.lms_ref != str(lms_course.id):
                rec.write({'lms_ref': str(lms_course.id)})
            count = rec._sync_lms_enrollments(lms_course)
            rec.action_reconcile_lms()
            rec.message_post(body=_('%d participant(s) enrolled in LMS.') % count)

    @api.model
    def cron_sync_lms(self):
        """Nightly EDS/LMS course sync and published-course learner feedback."""
        if not self.env.registry.get('lms.course') or not self.env.registry.get('lms.enrollment'):
            return
        for routing in self.sudo().search([('sync_state', '=', 'pending')], order='id'):
            routing.action_sync_to_lms()
        for routing in self.sudo().search([('sync_state', '=', 'synced')], order='id'):
            try:
                with self.env.cr.savepoint():
                    lms_course = routing._resolve_lms_course()
                    if not lms_course:
                        continue
                    if (lms_course.state == 'published' and lms_course.is_latest_version
                            and lms_course.active and routing.lms_ref != str(lms_course.id)):
                        routing.write({
                            'lms_ref': str(lms_course.id),
                            'last_sync_date': fields.Datetime.now(),
                        })
                    routing._sync_lms_enrollments(lms_course)
                    routing.action_reconcile_lms()
            except Exception:
                _logger.exception('EDS nightly LMS reconciliation failed for routing %s', routing.id)

    def action_reconcile_lms(self):
        """Refresh course metrics and each EDS participant's LMS evidence."""
        if not self.env.registry.get('lms.enrollment'):
            return
        for rec in self:
            if not rec.lms_ref or not rec.lms_ref.isdigit():
                continue
            course_id = int(rec.lms_ref)
            lms_course = self.env['lms.course'].sudo().browse(course_id).exists()
            lineage_ids = rec._lms_course_lineage_ids(lms_course)
            Enrollment = self.env['lms.enrollment'].sudo()
            today = fields.Date.context_today(rec)
            if rec.session_id:
                participants = rec.session_id.enrollment_ids.filtered(
                    lambda enrollment: enrollment.state in ('enrolled', 'completed')
                )
                completed = 0
                for participant in participants:
                    lms_enrollment = Enrollment.browse(
                        int(participant.lms_enrollment_ref)
                        if participant.lms_enrollment_ref and participant.lms_enrollment_ref.isdigit()
                        else 0
                    ).exists()
                    if lms_enrollment and (lms_enrollment.course_id.id not in lineage_ids or
                                           lms_enrollment.employee_id != participant.employee_id):
                        lms_enrollment = Enrollment.browse()
                    if not lms_enrollment:
                        lms_enrollment = Enrollment.search([
                            ('course_id', '=', course_id),
                            ('employee_id', '=', participant.employee_id.id),
                        ], order='attempt_number desc, id desc', limit=1)
                    certificate = lms_enrollment.certificate_id
                    certificate_state = certificate.state if certificate else False
                    if (certificate_state == 'valid' and certificate.expiry_date
                            and certificate.expiry_date < today):
                        certificate_state = 'expired'
                    participant.sudo().write({
                        'lms_enrollment_ref': str(lms_enrollment.id) if lms_enrollment else False,
                        'lms_completion_state': lms_enrollment.state if lms_enrollment else False,
                        'lms_completion_date': lms_enrollment.completion_date if lms_enrollment else False,
                        'lms_certificate_state': certificate_state,
                    })
                    if lms_enrollment.state == 'completed':
                        completed += 1
                total = len(participants)
            else:
                enrollments = Enrollment.search([
                    ('course_id', 'in', lineage_ids),
                ], order='employee_id, id desc')
                latest_by_employee = {}
                for enrollment in enrollments:
                    latest_by_employee.setdefault(enrollment.employee_id.id, enrollment)
                total = len(latest_by_employee)
                completed = sum(
                    enrollment.state == 'completed'
                    for enrollment in latest_by_employee.values()
                )
            rec.sudo().write({'lms_completion_pct': 100.0 * completed / total if total else 0.0})


class EdsEnrollmentLmsFeedback(models.Model):
    _inherit = 'eds.enrollment'

    lms_enrollment_ref = fields.Char(string='Linked LMS Enrollment ID', readonly=True, copy=False)
    lms_completion_state = fields.Selection([
        ('enrolled', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ], string='LMS Completion', readonly=True, copy=False)
    lms_completion_date = fields.Date(string='LMS Completion Date', readonly=True, copy=False)
    lms_certificate_state = fields.Selection([
        ('valid', 'Valid'),
        ('expired', 'Expired'),
        ('revoked', 'Revoked'),
    ], string='LMS Certificate', readonly=True, copy=False)

class EdsPayrollPayload(models.Model):
    _name = 'eds.payroll.payload'
    _description = 'EDS Payroll Cost Recovery / Deduction Payload'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

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
    payroll_reference = fields.Char(
        string='Payroll Handoff Reference', tracking=True,
        help='Reference supplied by Payroll after the recovery instruction is handed over.')
    transferred_by = fields.Many2one('res.users', string='Handoff Recorded By', readonly=True)
    transferred_at = fields.Datetime(string='Handoff Recorded At', readonly=True)
    processed_reference = fields.Char(
        string='Payroll Processing Reference', tracking=True,
        help='Payroll reference confirming that the deduction was processed.')
    processed_at = fields.Datetime(string='Processing Confirmed At', readonly=True)
    state = fields.Selection([
        ('pending', 'Pending Transfer to Payroll'),
        ('transferred', 'Payroll Handoff Recorded'),
        ('processed', 'Payroll Processing Confirmed'),
    ], string='Status', default='pending', required=True, tracking=True)

    @api.constrains('amount', 'state', 'payroll_reference', 'transferred_at',
                    'processed_reference', 'processed_at')
    def _check_payroll_evidence(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_('A payroll recovery amount cannot be negative.'))
            if rec.state in ('transferred', 'processed') and (
                    rec.amount <= 0 or not (rec.payroll_reference or '').strip()
                    or not rec.transferred_at):
                raise ValidationError(_(
                    'Record a positive amount and the payroll handoff reference before '
                    'marking this instruction as transferred.'))
            if rec.state == 'processed' and (
                    not (rec.processed_reference or '').strip() or not rec.processed_at):
                raise ValidationError(_(
                    'Enter the payroll processing reference before confirming a deduction.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.payroll.payload') or _('New')
        return super(EdsPayrollPayload, self).create(vals_list)

    def write(self, vals):
        if ('state' in vals and any(rec.state != vals['state'] for rec in self)
                and not self.env.su
                and not (self.env.user.has_group('employee_development_system.group_eds_manager')
                         or self.env.user.has_group('employee_development_system.group_eds_admin'))):
            raise UserError(_('Only an L&D manager can record a payroll handoff or processing result.'))
        return super().write(vals)

    def action_transfer_to_payroll(self):
        for rec in self:
            if not (self.env.su or self.env.user.has_group(
                    'employee_development_system.group_eds_manager')):
                raise UserError(_('Only an L&D manager can record a payroll handoff.'))
            if rec.state != 'pending':
                raise UserError(_('Only pending recovery instructions can be handed to Payroll.'))
            if not (rec.payroll_reference or '').strip():
                raise ValidationError(_(
                    'Enter the reference supplied by Payroll after handing over the instruction.'))
            rec.write({
                'state': 'transferred',
                'transferred_by': self.env.user.id,
                'transferred_at': fields.Datetime.now(),
            })
            self.env['eds.integration.log'].sudo().create({
                'name': f"PAYROLL-PAYLOAD-{rec.name}",
                'system': 'payroll',
                'direction': 'outbound',
                'status': 'recorded',
                'details': f"Payroll handoff for {rec.name} recorded with reference {rec.payroll_reference}.",
            })

    def action_confirm_processed(self):
        for rec in self:
            if not (self.env.su or self.env.user.has_group(
                    'employee_development_system.group_eds_manager')):
                raise UserError(_('Only an L&D manager can confirm payroll processing.'))
            if rec.state != 'transferred':
                raise UserError(_('Record a payroll handoff before confirming processing.'))
            if not (rec.processed_reference or '').strip():
                raise ValidationError(_('Enter the payroll processing reference.'))
            rec.write({'state': 'processed', 'processed_at': fields.Datetime.now()})
            rec.message_post(body=_('Payroll processing confirmed with reference %s.')
                             % rec.processed_reference)
