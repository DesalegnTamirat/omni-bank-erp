from datetime import datetime, date
from dateutil import relativedelta

from odoo import _
from odoo.exceptions import UserError
from odoo import models, fields, api
import json
import requests

class CallApi(models.Model):
    _name = 'call.api.b'
    transaction_status = fields.Boolean(string="Transaction Status")

    def get_record_count(self):
        self.env.cr.execute("""
        SELECT count(*)
        FROM bunna_bonus_v bbv
        WHERE 1=1
        """)
        result = self.env.cr.fetchone()
        if result:
            n_count = result[0]
            print("******Record Count is **", n_count)
            return n_count
        return 0

    def get_json_array(self):
        self.env.cr.execute("""
        SELECT JSON_AGG(
            JSON_BUILD_OBJECT(
                'account', bbv.account,
                'amount', bbv.amount,
                'particular', bbv.particular,
                'flag', bbv.flag,
                'currency', bbv.currency,
                'report_code', bbv.report_code
            )
        )
        FROM bunna_bonus_v bbv
        WHERE 1=1
        """)

        result = self.env.cr.fetchone()[0]
        return result

    def process_json_array(self):
        payloads = []
        part_transactions = []
        json_array = self.get_json_array()
        part_transactions.extend(json_array)
        return part_transactions

    def generate_token(self, user_name, password):
        parameters = {
            "username": user_name,
            "password": password
        }
        response = requests.post(
            "http://10.1.13.41:8080/bunna_services/api/auth/login", json=parameters)

        return response.json()

    def post_transactions(self, token, date, reason, payloads, part_transactions):
        parameters = {
            'date': date,
            'reason': reason,
            'payloads': payloads,
            'part_transactions': part_transactions
        }

        headers = {
            'content-type': 'application/json',
            'Authorization': 'Bearer {0}'.format(token)
        }

        response = requests.post(
            "http://10.1.13.41:8080/bunna_services/api/core/transaction/admin/mc2mc", json=parameters, headers=headers)

        return response.json()

    def process_api(self):
        # form_id = value_x  # Assign the value of x to form_id
        # print("************form id", form_id)
        today = date. today()
        today = today. strftime("%d-%m-%Y")
        # Call the generate_token method from generate_token.py
        token_generation_response = self.generate_token(
            "erp_user@bunnabanksc.com", "sZ,11B9/CTsh")

        # Call the post_transactions method from transaction.py if token was generated successfully
        # print('*************************', token_generation_response)
        n_count = self.get_record_count()
        if n_count > 0:
            print('*************************', token_generation_response)
            if 'token' in token_generation_response:
                payloads = []
                part_transactions = self.process_json_array()
                transaction_response = self.post_transactions(
                    token_generation_response['token'],
                    today,
                    "Remark",
                    payloads,
                    part_transactions)
                print("+++++++++++++++++++++++++Transaction Response", transaction_response)
            else:
                print("Unauthorized!")

class bonus_transfer_wizard(models.TransientModel):
    _name = 'bonus.transfer.wizard'
    # _description = 'populate.net.salary.payment'

    # hr_period = fields.Many2one("hr.period", string='Payroll Period', domain=[('state', '=', 'open')])

    def bonus_transfer(self):
        # p_id = self.hr_period.id
        self.env["call.api.b"].process_api()
        # cr = self.env.cr
        # cr.execute("SELECT pre_process_payroll(%s,)", (p_id))
        # cr.commit()
        print("Bonus Transfer Executed")

    def cancel(self):
        print("self",self)
