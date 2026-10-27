from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged


def _unused_fiscal_year(env, start=2099):
    year = start
    while env['eds.annual.plan'].sudo().search_count([('fiscal_year', '=', str(year))]):
        year += 1
    return str(year)


@tagged('post_install', '-at_install', 'eds', 'meeting_minutes')
class TestApprovalMinuteWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = cls.env['eds.annual.plan'].sudo().create({
            'fiscal_year': _unused_fiscal_year(cls.env),
        })

    def _wizard(self, **extra):
        values = {
            'approval_type': 'annual_plan',
            'annual_plan_id': self.plan.id,
        }
        values.update(extra)
        return self.env['eds.approval.minute.wizard'].sudo().create(values)

    def test_download_accepts_only_currently_published_plan(self):
        wizard = self._wizard()
        with self.assertRaises(UserError):
            wizard.action_download()

        self.plan.sudo().write({'state': 'published'})
        self.assertEqual(wizard._get_approved_record(), self.plan)
        report_action = wizard.action_download()
        self.assertEqual(report_action['type'], 'ir.actions.report')
        self.assertEqual(
            report_action['report_name'],
            'employee_development_system.report_eds_meeting_minutes_document',
        )

        # The status is checked again at download, not trusted from the dropdown.
        self.plan.sudo().write({'state': 'amended'})
        with self.assertRaises(UserError):
            wizard.action_download()

    def test_category_and_record_must_match(self):
        self.plan.sudo().write({'state': 'published'})
        wrong_category = self._wizard(approval_type='unscheduled_request')
        with self.assertRaises(UserError):
            wrong_category.action_download()

        no_record = self.env['eds.approval.minute.wizard'].sudo().create({
            'approval_type': 'annual_plan',
        })
        with self.assertRaises(UserError):
            no_record.action_download()

    def test_changing_category_clears_the_previous_record(self):
        wizard = self._wizard()
        wizard.approval_type = 'unscheduled_request'
        wizard._onchange_approval_type()
        self.assertFalse(wizard.annual_plan_id)
        self.assertFalse(wizard.unscheduled_request_id)

    def test_source_read_access_is_required(self):
        self.plan.sudo().write({'state': 'published'})
        public_user = self.env.ref('base.public_user')
        with self.assertRaises(AccessError):
            self.plan.with_user(public_user).check_access('read')
        with self.assertRaises(AccessError):
            self._wizard().with_user(public_user)._get_approved_record()

    def test_record_from_another_company_is_denied(self):
        other = self.env['res.company'].sudo().create({
            'name': 'Approval Minute Other Company',
        })
        foreign_plan = self.env['eds.annual.plan'].sudo().create({
            'company_id': other.id,
            'fiscal_year': _unused_fiscal_year(
                self.env, int(self.plan.fiscal_year) + 1,
            ),
        })
        foreign_plan.sudo().write({'state': 'published'})
        wizard = self._wizard(annual_plan_id=foreign_plan.id).with_context(
            allowed_company_ids=[self.env.company.id],
        )
        with self.assertRaises(AccessError):
            wizard._get_approved_record()

    def test_published_plan_renders_approval_pdf(self):
        self.plan.sudo().write({'state': 'published'})
        wizard = self._wizard()
        report_name = wizard.action_download()['report_name']
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            report_name, [wizard.id],
        )
        self.assertIn(b'Approval Minute', html)
        self.assertIn(self.plan.name.encode(), html)

        pdf, report_format = self.env['ir.actions.report'].with_context(
            force_report_rendering=True,
        )._render_qweb_pdf(report_name, [wizard.id])
        self.assertEqual(report_format, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF'))

    def _render_source_pdf(self, approval_type, field_name, source, heading):
        wizard = self.env['eds.approval.minute.wizard'].sudo().create({
            'approval_type': approval_type,
            field_name: source.id,
        })
        self.assertEqual(wizard._get_approved_record(), source)
        report_name = wizard.action_download()['report_name']
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            report_name, [wizard.id],
        )
        self.assertIn(heading.encode(), html)
        self.assertIn(source.name.encode(), html)
        pdf, report_format = self.env['ir.actions.report'].with_context(
            force_report_rendering=True,
        )._render_qweb_pdf(report_name, [wizard.id])
        self.assertEqual(report_format, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF'))

    def _approved_unscheduled_request(self):
        course = self.env['eds.course'].sudo().create({
            'name': 'Approval Minute Training Course',
        })
        request = self.env['eds.unscheduled.request'].sudo().create({
            'course_id': course.id,
            'justification': 'Urgent operating need for training.',
            'delivery_method': 'local_external',
            'state': 'approved',
        })
        return request

    def test_unscheduled_request_pdf_branch(self):
        request = self._approved_unscheduled_request()
        self._render_source_pdf(
            'unscheduled_request', 'unscheduled_request_id', request,
            'Approved Unscheduled Training Request',
        )

    def test_training_provider_award_pdf_branch(self):
        request = self._approved_unscheduled_request()
        selection = self.env['eds.course.vendor.selection'].sudo().create({
            'source_type': 'unscheduled',
            'unscheduled_request_id': request.id,
            'state': 'awarded',
        })
        self._render_source_pdf(
            'vendor_selection', 'vendor_selection_id', selection,
            'Awarded Training Provider',
        )

    def test_hotel_award_pdf_branch(self):
        request = self._approved_unscheduled_request()
        selection = self.env['eds.hotel.selection'].sudo().create({
            'source_type': 'unscheduled',
            'unscheduled_request_id': request.id,
            'state': 'awarded',
        })
        self._render_source_pdf(
            'hotel_selection', 'hotel_selection_id', selection,
            'Awarded Hotel / Venue',
        )

    def test_sponsorship_pdf_branch(self):
        employee = self.env['hr.employee'].sudo().create({
            'name': 'Approval Minute Sponsored Employee',
        })
        sponsorship = self.env['eds.sponsorship'].sudo().create({
            'employee_id': employee.id,
            'program_name': 'Professional Certification',
            'approved_amount': 1000,
            'state': 'approved',
        })
        self._render_source_pdf(
            'sponsorship', 'sponsorship_id', sponsorship,
            'Approved Staff Sponsorship',
        )

    def test_tna_consolidation_pdf_branch(self):
        cycle = self.env['eds.tna.cycle'].sudo().create({})
        consolidation = self.env['eds.tna.consolidation'].sudo().create({
            'cycle_id': cycle.id,
            'state': 'approved',
        })
        self._render_source_pdf(
            'tna_consolidation', 'tna_consolidation_id', consolidation,
            'Approved Training Needs Consolidation',
        )

    def test_rfp_award_pdf_branch(self):
        course = self.env['eds.course'].sudo().create({
            'name': 'Approval Minute RFP Course',
        })
        rfp = self.env['eds.rfp'].sudo().create({
            'course_id': course.id,
            'scope_of_work': 'Provide course instruction.',
            'submission_deadline': '2026-12-31',
            'state': 'awarded',
        })
        self._render_source_pdf('rfp', 'rfp_id', rfp, 'Awarded Request for Proposal')
