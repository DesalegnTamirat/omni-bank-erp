"""Clear the former answer-shuffle setting until an order snapshot exists."""


def migrate(cr, version):
    cr.execute("""
        UPDATE lms_assessment
           SET shuffle_answers = FALSE
         WHERE shuffle_answers IS DISTINCT FROM FALSE
    """)
