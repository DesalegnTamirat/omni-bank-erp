from odoo import models, fields, api
import requests
from odoo.exceptions import UserError

class HrCashIndemnity(models.Model):
    _name = 'hr.cash.indemnity'
    _description = 'CBS Cash Indemnity Allowance'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one('hr.employee', string="Employee", required=True)
    cbs_user_id = fields.Char(related="employee_id.employee_identification", string="CBS User ID", readonly=True)
    
    date_from = fields.Date(string="Date From", required=True)
    date_to = fields.Date(string="Date To", required=True)
    working_days = fields.Integer(string="Working Days", required=True, default=25)
    
    amount = fields.Float(string="Fetched Amount", readonly=True, copy=False)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Currency', related='company_id.currency_id', readonly=True)
    raw_response = fields.Text(string="Raw Response", readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('fetched', 'Fetched from CBS')
    ], default='draft', string="Status")

    def action_fetch_from_cbs(self):
        for rec in self:
            if not rec.cbs_user_id:
                raise UserError("This employee does not have a CBS User ID set!")

            # 1. Get credentials securely from System Parameters
            IrConfig = self.env['ir.config_parameter'].sudo()
            base_url = IrConfig.get_param('cbs.api.url', 'http://10.1.11.242:7001')
            username = IrConfig.get_param('cbs.api.username', '')
            password = IrConfig.get_param('cbs.api.password', '')

            # 2. Login to CBS to get Token
            login_url = f"{base_url.rstrip('/')}/api/auth/login"
            try:
                login_resp = requests.post(login_url, params={'username': username, 'password': password}, timeout=15)
                login_resp.raise_for_status()
                token = login_resp.json().get('accessToken')
            except Exception as e:
                raise UserError(f"Failed to login to CBS API: {str(e)}")

            # 3. Fetch the Amount from CBS
            fetch_url = f"{base_url.rstrip('/')}/api/cbs/cash-indemnity"
            params = {
                'empId': rec.cbs_user_id,
                'formDate': rec.date_from.strftime('%Y-%m-%d'),
                'toDate': rec.date_to.strftime('%Y-%m-%d'),
                'workingDays': rec.working_days
            }
            headers = {'Authorization': f'Bearer {token}'}

            try:
                resp = requests.get(fetch_url, params=params, headers=headers, timeout=30)
                if resp.status_code == 404:
                    rec.amount = 0.0
                    rec.state = 'fetched'
                    return 

                resp.raise_for_status()
                data = resp.json()
                fetched_amount = data.get('computedIndemnity') or data.get('amount') or data.get('indemnityAmount') or 0.0
                
                rec.amount = float(fetched_amount)
                rec.state = 'fetched'
                
            except Exception as e:
                raise UserError(f"Failed to fetch Cash Indemnity: {str(e)}")
