# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class DmsDashboard(models.AbstractModel):
    _name = 'dms.dashboard'
    _description = 'Documents Dashboard'

    @api.model
    def get_dashboard_data(self):
        user = self.env.user
        is_manager = user.has_group('documents_lite.group_dms_manager')
        Doc = self.env['dms.document']
        Folder = self.env['dms.folder']

        # Total counts
        total_docs = Doc.search_count([('active', '=', True)])
        disabled_docs = Doc.search_count([('active', '=', False)]) if is_manager else 0
        total_folders = Folder.search_count([('active', '=', True)])
        my_docs = Doc.search_count([('active', '=', True), ('create_uid', '=', user.id)])

        # Calculate total storage size
        all_docs = Doc.search([('active', '=', True)])
        total_bytes = sum(all_docs.mapped('file_size') or [0])
        total_size_human = self._format_size(total_bytes)

        # File type breakdown
        type_counts = {}
        for doc in all_docs:
            ext = (doc.extension or 'other').lower()
            type_counts[ext] = type_counts.get(ext, 0) + 1
        
        top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:6]
        type_data = [{'label': k.upper(), 'count': v} for k, v in top_types]

        # Top folders
        folders = Folder.search([('active', '=', True)])
        folder_list = []
        for f in sorted(folders, key=lambda x: x.document_count, reverse=True)[:6]:
            folder_list.append({
                'id': f.id,
                'name': f.name,
                'count': f.document_count,
            })

        # Recent uploads
        recent_docs = Doc.search([('active', '=', True)], order='id desc', limit=6)
        recent_list = []
        for d in recent_docs:
            recent_list.append({
                'id': d.id,
                'name': d.name,
                'folder': d.folder_id.name or '',
                'size': d.file_size_human or '',
                'extension': (d.extension or '').upper(),
                'create_uid': d.create_uid.name or '',
                'create_date': fields.Date.to_string(d.create_date.date()) if d.create_date else '',
            })

        # Duplicates count
        duplicate_count = len(all_docs.filtered('has_duplicate'))

        kpis = [
            {
                'key': 'total',
                'label': _('Total Documents'),
                'value': total_docs,
                'icon': 'fa-file-text-o',
                'tone': 'primary',
                'hint': _('Active documents in DMS'),
                'domain': [('active', '=', True)],
            },
            {
                'key': 'storage',
                'label': _('Storage Used'),
                'value': total_size_human,
                'icon': 'fa-database',
                'tone': 'info',
                'hint': _('Total file volume'),
                'domain': [('active', '=', True)],
            },
            {
                'key': 'folders',
                'label': _('Active Folders'),
                'value': total_folders,
                'icon': 'fa-folder-open',
                'tone': 'warning',
                'hint': _('Structured folders'),
                'action': 'documents_lite.dms_folder_action',
            },
            {
                'key': 'my_docs',
                'label': _('My Uploads'),
                'value': my_docs,
                'icon': 'fa-cloud-upload',
                'tone': 'success',
                'hint': _('Uploaded by you'),
                'domain': [('active', '=', True), ('create_uid', '=', user.id)],
            },
        ]

        if is_manager and disabled_docs:
            kpis.append({
                'key': 'disabled',
                'label': _('Disabled Documents'),
                'value': disabled_docs,
                'icon': 'fa-ban',
                'tone': 'danger',
                'hint': _('Hidden from viewers'),
                'domain': [('active', '=', False)],
            })

        if duplicate_count:
            kpis.append({
                'key': 'duplicates',
                'label': _('Duplicate Files'),
                'value': duplicate_count,
                'icon': 'fa-copy',
                'tone': 'muted',
                'hint': _('Identical file contents'),
                'domain': [('has_duplicate', '=', True)],
            })

        return {
            'user_name': user.name,
            'is_manager': is_manager,
            'today': fields.Date.context_today(self).strftime('%A, %d %B %Y'),
            'kpis': kpis,
            'type_data': type_data,
            'folder_list': folder_list,
            'recent_docs': recent_list,
        }

    @api.model
    def _format_size(self, size):
        size = float(size or 0)
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024 or unit == 'GB':
                return f'{int(size)} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
            size /= 1024
        return f'{size:.1f} GB'
