# -*- coding: utf-8 -*-
from odoo import models, fields, api
import base64


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record, vals in zip(records, vals_list):
            image_value = vals.get('image_1920', False)
            if image_value:
                image_bytes = None
                if isinstance(image_value, str):
                    image_bytes = image_value.encode('utf-8')
                elif isinstance(image_value, (bytes, bytearray)):
                    image_bytes = image_value
                if image_bytes:
                    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                    self._insert_into_emp_profile(record.id, image_base64)
        return records

    def write(self, vals):
        res = super().write(vals)
        image_value = vals.get('image_1920', False)
        if image_value:
            for emp in self:
                image_bytes = None
                if isinstance(image_value, str):
                    image_bytes = image_value.encode('utf-8')
                elif isinstance(image_value, (bytes, bytearray)):
                    image_bytes = image_value
                if image_bytes:
                    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                    self._insert_into_emp_profile(emp.id, image_base64)
        return res

    def _insert_into_emp_profile(self, emp_id, image_base64):
        """Insert/update photo into employee_profile_photo table as bytea."""
        current_uid = self.env.uid
        current_time = fields.Datetime.now()

        query = """
            INSERT INTO employee_profile_photo (
                employee_id,
                profile_picture,
                create_uid,
                create_date,
                write_uid,
                write_date
            ) VALUES (%s, decode(%s, 'base64'), %s, %s, %s, %s)
            ON CONFLICT (employee_id) DO UPDATE
            SET profile_picture = EXCLUDED.profile_picture,
                write_uid = EXCLUDED.write_uid,
                write_date = EXCLUDED.write_date
        """

        self.env.cr.execute(query, (
            emp_id,
            image_base64,
            current_uid,
            current_time,
            current_uid,
            current_time
        ))
