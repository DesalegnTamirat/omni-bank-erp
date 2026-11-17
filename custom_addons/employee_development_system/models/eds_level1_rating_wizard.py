"""Choose a rating period and open one result row per rated entity."""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


_REPORT_TITLES = {
    'vendor': 'Vendor Reporting',
    'hotel': 'Hotel Reporting',
    'course': 'Course Reporting',
}
_RESULT_LIST_VIEWS = {
    'vendor': 'view_eds_vendor_rating_result_list',
    'hotel': 'view_eds_hotel_rating_result_list',
    'course': 'view_eds_course_rating_result_list',
}


class EdsRatingReportWizard(models.TransientModel):
    _name = 'eds.rating.report.wizard'
    _description = 'Generate Vendor, Hotel or Course Rating Report'

    @api.model
    def _default_fiscal_year(self):
        today = fields.Date.context_today(self)
        return today.year if today.month >= 7 else today.year - 1

    @api.model
    def _default_period_index(self):
        today = fields.Date.context_today(self)
        return str(((today.month - 7) % 12) // 3 + 1)

    target_area = fields.Selection([
        ('vendor', 'Vendor'),
        ('hotel', 'Hotel'),
        ('course', 'Course'),
    ], string='Reporting For', required=True, readonly=True)
    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda self: self.env.company)
    fiscal_year = fields.Integer(string='Fiscal Year Starting July', required=True,
                                 default=_default_fiscal_year)
    period_kind = fields.Selection([
        ('quarter', 'Quarterly'),
        ('half', 'Semiannual'),
        ('annual', 'Annual'),
    ], string='Period', required=True, default='quarter')
    period_index = fields.Selection([
        ('1', '1'), ('2', '2'), ('3', '3'), ('4', '4'),
    ], string='Quarter / Half Number', required=True,
        default=_default_period_index)
    provider_id = fields.Many2one('eds.external.provider', string='Vendor')
    venue_id = fields.Many2one('eds.venue', string='Hotel')
    course_id = fields.Many2one('eds.course', string='Course')

    @api.onchange('period_kind')
    def _onchange_period_kind(self):
        if self.period_kind == 'annual' or (
                self.period_kind == 'half' and self.period_index not in ('1', '2')):
            self.period_index = '1'

    def action_generate(self):
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group(
                'employee_development_system.group_eds_officer')):
            raise AccessError(_('Only Learning and Development staff can generate rating reports.'))
        fixed_target = self.env.context.get('eds_rating_target')
        if fixed_target and self.target_area != fixed_target:
            raise AccessError(_('The selected reporting area does not match this menu.'))
        if self.target_area not in _REPORT_TITLES:
            raise ValidationError(_('Choose Vendor, Hotel, or Course reporting.'))
        if self.company_id not in self.env.companies and not self.env.su:
            raise AccessError(_('Switch to the report company before generating it.'))

        values = {
            'company_id': self.company_id.id,
            'target_area': self.target_area,
            'fiscal_year': self.fiscal_year,
            'period_kind': self.period_kind,
            'period_index': self.period_index,
            'provider_id': self.provider_id.id if self.target_area != 'hotel' else False,
            'venue_id': self.venue_id.id if self.target_area == 'hotel' else False,
            'course_id': self.course_id.id,
        }
        domain = [(field, '=', value) for field, value in values.items()]
        Report = self.env['eds.level1.rating.report']
        report = Report.search(domain, order='id desc', limit=1)
        if not report:
            report = Report.create(values)
        report.action_generate()

        view = self.env.ref(
            'employee_development_system.' + _RESULT_LIST_VIEWS[self.target_area])
        form = self.env.ref(
            'employee_development_system.view_eds_level1_rating_report_line_form')
        search = self.env.ref(
            'employee_development_system.view_eds_level1_rating_report_line_search')
        return {
            'type': 'ir.actions.act_window',
            'name': _(_REPORT_TITLES[self.target_area]) + ' — ' + report.name.split('·')[-1].strip(),
            'res_model': 'eds.level1.rating.report.line',
            'view_mode': 'list,form',
            'views': [(view.id, 'list'), (form.id, 'form')],
            'search_view_id': search.id,
            'domain': [('report_id', '=', report.id)],
            'context': {'create': False, 'edit': False, 'delete': False},
        }
