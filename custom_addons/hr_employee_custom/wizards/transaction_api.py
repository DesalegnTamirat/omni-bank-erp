from odoo import models, fields, api
import json
import requests
# from bunna_api import generate_token

from odoo import models, api


# class GenerateToken(models.Model):
#     _name = 'generate.token'


class CallApi(models.Model):
    _name = 'call.api'
    transaction_status = fields.Boolean(string="Transaction Status")

    def get_record_count(self, form_id):
        self.env.cr.execute("""
        SELECT count(*)
        FROM bunna_payroll_entry_v bpev
        WHERE move_id = %s
        """, (form_id,))
        result = self.env.cr.fetchone()
        if result:
            n_count = result[0]
            print("******Record Count is **", n_count)
            return n_count
        return 0

    def get_json_array(self, form_id):
        self.env.cr.execute("""
        SELECT JSON_AGG(
            JSON_BUILD_OBJECT(
                'account', btv.account,
                'amount', btv.amount,
                'particular', btv.particular,
                'flag', btv.flag,
                'currency', btv.currency
            )
        )
        FROM bunna_payroll_entry_v bpev
        WHERE hr_period_id = %s
        """, (form_id,))

        result = self.env.cr.fetchone()[0]
        return result

    def process_json_array(self, form_id):
        payloads = []
        part_transactions = []
        json_array = self.get_json_array(form_id)
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

    def process_api(self, value_x):
        form_id = value_x  # Assign the value of x to form_id
        print("************form id", form_id)

        # Call the generate_token method from generate_token.py
        token_generation_response = self.generate_token(
            "erp_user@bunnabanksc.com", "12345678")

        # Call the post_transactions method from transaction.py if token was generated successfully
        # print('*************************', token_generation_response)
        n_count = self.get_record_count(form_id)
        if n_count > 0:
            print('*************************', token_generation_response)
            if 'token' in token_generation_response:
                payloads = []
                part_transactions = self.process_json_array(form_id)
                transaction_response = self.post_transactions(
                    token_generation_response['token'],
                    "05-02-2023 03:15:10",
                    "Remark",
                    payloads,
                    part_transactions)
                print("+++++++++++++++++++++++++Transaction Response", transaction_response)
            else:
                print("Unauthorized!")
