"""Fail closed for previously stored documents with unrecognized classifications."""


def migrate(cr, version):
    cr.execute("""
        UPDATE kms_document AS doc
           SET classification = 'restricted'
          FROM kms_classification AS classification
         WHERE doc.classification_id = classification.id
           AND COALESCE(split_part(upper(classification.code), '-', 1), '') NOT IN (
               'PUB', 'PUBLIC', 'INT', 'INTERNAL',
               'CONF', 'CONFIDENTIAL', 'SCONF', 'RESTRICTED'
           )
           AND doc.classification IS DISTINCT FROM 'restricted'
    """)
    cr.execute("""
        UPDATE kms_document
           SET classification = 'restricted'
         WHERE classification_id IS NULL
           AND classification IS DISTINCT FROM 'restricted'
    """)
