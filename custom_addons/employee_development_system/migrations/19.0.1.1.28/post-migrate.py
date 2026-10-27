"""Keep older provider awards external when the approved plan was internal."""


def migrate(cr, version):
    cr.execute("""
        UPDATE eds_course_vendor_selection AS sourcing
           SET delivery_method = CASE
               WHEN provider.category = 'international' THEN 'international'
               ELSE 'local_external'
           END
          FROM eds_external_provider AS provider
         WHERE sourcing.awarded_vendor_id = provider.id
           AND sourcing.delivery_method = 'internal'
    """)
    cr.execute("""
        UPDATE eds_hotel_selection AS hotel
           SET delivery_method = (
               SELECT sourcing.delivery_method
                 FROM eds_course_vendor_selection AS sourcing
                WHERE sourcing.plan_line_id = hotel.plan_line_id
                  AND sourcing.state = 'awarded'
                ORDER BY sourcing.id DESC
                LIMIT 1
           )
         WHERE EXISTS (
               SELECT 1
                 FROM eds_course_vendor_selection AS sourcing
                WHERE sourcing.plan_line_id = hotel.plan_line_id
                  AND sourcing.state = 'awarded'
           )
    """)
