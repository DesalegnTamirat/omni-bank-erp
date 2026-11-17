# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Old posts were pre-filled with 'OdooBot' as the signature: use the bank name."""
    cr.execute("UPDATE bunna_announcement SET signed_by = %s WHERE signed_by = %s",
               ('Bunna Bank S.C', 'OdooBot'))