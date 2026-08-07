# -*- coding: utf-8 -*-
from odoo import api, models


class TransferCommitteeMinutesReport(models.AbstractModel):
    _name = "report.custom_recruitment.report_transfer_minute_template"
    _description = "Transfer Committee Minutes Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["transfer.committee.minutes"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "transfer.committee.minutes",
            "docs": docs,
            "data": data,
        }
