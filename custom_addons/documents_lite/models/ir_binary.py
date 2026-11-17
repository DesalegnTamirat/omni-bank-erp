from odoo import _, models
from odoo.exceptions import AccessError


class IrBinary(models.AbstractModel):
    _inherit = 'ir.binary'

    def _get_stream_from(self, record, field_name='raw', filename=None, filename_field='name',
                         mimetype=None, default_mimetype='application/octet-stream'):
        # /web/content?download=true sets this context key. Previews (no download flag) still work.
        if record.env.context.get('download_attachments') and record._name in (
                'dms.document', 'dms.document.version'):
            doc = record if record._name == 'dms.document' else record.document_id
            if not doc._dms_can_download():
                raise AccessError(_('Downloading this document is not allowed.'))
        return super()._get_stream_from(
            record, field_name, filename, filename_field, mimetype, default_mimetype)
