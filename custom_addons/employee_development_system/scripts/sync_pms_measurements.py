"""Copy PMS measurement definitions from ERP_TEST3 into the local test DB.

Run inside the Odoo container. The remote connection uses HOST/USER/PASSWORD;
the local connection uses /etc/odoo/odoo.conf. Dry-run is the default.
Only PMS definition tables are written. HR references are matched by stable
employee identification or exact job/work-unit name, never by remote IDs.
"""

import argparse
import configparser
import os

import psycopg2
from psycopg2.extras import execute_values


SOURCE = 'ERP_TEST3'
TARGET = 'ERP_local_full'
TABLES = (
    'performance_objective', 'performance_measure',
    'performance_job_objective', 'performance_job_measure',
)


def rows(connection, query, params=()):
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def remap(remote_rows, local_rows, label, key_pos=1, exact_only=False):
    def display_key(value):
        if isinstance(value, dict):
            return value.get('en_US') or next(iter(value.values()), '')
        return str(value or '')

    local_index = {}
    for local_row in local_rows:
        key = display_key(local_row[key_pos]).strip()
        if key:
            local_index.setdefault(key if exact_only else key.casefold(), []).append((local_row[0], key))
    mapping = {}
    for remote_row in remote_rows:
        key = display_key(remote_row[key_pos]).strip()
        candidates = local_index.get(key if exact_only else key.casefold(), [])
        if not key or not candidates:
            raise ValueError('%s has no exact local match for remote ID %s' % (
                label, remote_row[0]))
        if len(candidates) > 1:
            exact = [candidate for candidate in candidates if candidate[1] == key]
            candidates = exact or candidates
        if len(candidates) != 1:
            raise ValueError('%s has ambiguous local matches for remote ID %s' % (
                label, remote_row[0]))
        mapping[remote_row[0]] = candidates[0][0]
    return mapping


def nullable(mapping, remote_id, label):
    if not remote_id:
        return None
    if remote_id not in mapping:
        raise ValueError('%s remote ID %s is unmapped' % (label, remote_id))
    return mapping[remote_id]


def main(apply):
    config = configparser.ConfigParser()
    config.read('/etc/odoo/odoo.conf')
    options = config['options']
    remote = psycopg2.connect(
        host=os.environ['HOST'], user=os.environ['USER'],
        password=os.environ['PASSWORD'], dbname=SOURCE, connect_timeout=10,
    )
    remote.set_session(readonly=True)
    local = psycopg2.connect(
        host=options['db_host'], port=options.getint('db_port'),
        user=options['db_user'], password=options['db_password'],
        dbname=TARGET, connect_timeout=10,
    )
    try:
        source = {
            'objectives': rows(remote, '''
                SELECT id, name, employee_id, perspective_id, parent_objective_id,
                       employee_operating_unit_id, coach_operating_unit_id,
                       active, total_weight, create_date, write_date
                FROM performance_objective ORDER BY id'''),
            'measures': rows(remote, '''
                SELECT id, name, objective_id, perspective_id, kpi, weight,
                       target_type, active, create_date, write_date
                FROM performance_measure ORDER BY id'''),
            'job_objectives': rows(remote, '''
                SELECT id, name, operating_unit_id, job_id, parent_measure_id,
                       parent_objective_id, perspective_id, active, total_weight,
                       create_date, write_date
                FROM performance_job_objective ORDER BY id'''),
            'job_measures': rows(remote, '''
                SELECT id, name, job_objective_id, weight, target_type, active,
                       create_date, write_date
                FROM performance_job_measure ORDER BY id'''),
        }
        if any(not values for values in source.values()):
            raise ValueError('The remote PMS hierarchy is incomplete')

        employee_ids = set(row[2] for row in source['objectives'])
        remote_employees = rows(remote, '''
            SELECT id, employee_identification FROM hr_employee WHERE id = ANY(%s)
        ''', (list(employee_ids),))
        local_employees = rows(local, '''
            SELECT id, employee_identification FROM hr_employee
        ''')
        employees = remap(remote_employees, local_employees, 'employee identification')
        if len(employees) != len(employee_ids):
            raise ValueError('Some remote PMS objective owners are missing')

        job_ids = set(row[3] for row in source['job_objectives'])
        jobs = remap(
            rows(remote, 'SELECT id, name FROM hr_job WHERE id = ANY(%s)', (list(job_ids),)),
            rows(local, 'SELECT id, name FROM hr_job'), 'job title', exact_only=True,
        )
        if len(jobs) != len(job_ids):
            raise ValueError('Some remote PMS job positions are missing')

        unit_ids = set(row[2] for row in source['job_objectives'])
        for row in source['objectives']:
            unit_ids.update(unit for unit in (row[5], row[6]) if unit)
        units = remap(
            rows(remote, 'SELECT id, name FROM operating_unit WHERE id = ANY(%s)',
                 (list(unit_ids),)),
            rows(local, 'SELECT id, name FROM operating_unit'), 'work unit',
        )
        if len(units) != len(unit_ids):
            raise ValueError('Some remote PMS work units are missing')

        mapped_objectives = {}
        for row in source['job_objectives']:
            unique_key = (units[row[2]], jobs[row[3]], row[1])
            if unique_key in mapped_objectives:
                raise ValueError(
                    'PMS job objectives %s and %s would collide after HR mapping'
                    % (mapped_objectives[unique_key], row[0]))
            mapped_objectives[unique_key] = row[0]

        perspectives = remap(
            rows(remote, 'SELECT id, name FROM performance_perspective'),
            rows(local, 'SELECT id, name FROM performance_perspective'),
            'PMS perspective',
        )
        counts = {table: rows(local, 'SELECT count(*) FROM ' + table)[0][0]
                  for table in TABLES}
        if any(counts.values()):
            raise ValueError('Local PMS definition tables are not empty: %s' % counts)
        print('Source: %s; target: %s' % (SOURCE, TARGET))
        print('Definition counts: %s' % {
            key: len(value) for key, value in source.items()})
        print('Unique reference matches: %d employees, %d jobs, %d work units, %d perspectives' % (
            len(employees), len(jobs), len(units), len(perspectives)))
        if not apply:
            print('Dry run only; no local records changed.')
            return

        # Keep source IDs inside the four empty PMS tables so their internal
        # relationships remain stable. HR and perspective IDs are remapped.
        with local.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', (9719873,))
            objective_values = [(
                row[0], row[1], employees[row[2]],
                nullable(perspectives, row[3], 'perspective'),
                nullable(units, row[5], 'owner work unit'),
                nullable(units, row[6], 'coach work unit'),
                row[7], row[8], row[9], row[10],
            ) for row in source['objectives']]
            execute_values(cursor, '''
                INSERT INTO performance_objective
                    (id, name, employee_id, perspective_id,
                     employee_operating_unit_id, coach_operating_unit_id,
                     active, total_weight, create_date, write_date)
                VALUES %s
            ''', objective_values)
            cursor.executemany('''
                UPDATE performance_objective SET parent_objective_id=%s WHERE id=%s
            ''', [(row[4], row[0]) for row in source['objectives'] if row[4]])

            measure_values = [(
                row[0], row[1], row[2],
                nullable(perspectives, row[3], 'measure perspective'),
                row[4], row[5], row[6], row[7], row[8], row[9],
            ) for row in source['measures']]
            execute_values(cursor, '''
                INSERT INTO performance_measure
                    (id, name, objective_id, perspective_id, kpi, weight,
                     target_type, active, create_date, write_date)
                VALUES %s
            ''', measure_values)

            job_objective_values = [(
                row[0], row[1], units[row[2]], jobs[row[3]], row[4],
                row[5], nullable(perspectives, row[6], 'job perspective'),
                row[7], row[8], row[9], row[10],
            ) for row in source['job_objectives']]
            execute_values(cursor, '''
                INSERT INTO performance_job_objective
                    (id, name, operating_unit_id, job_id, parent_measure_id,
                     parent_objective_id, perspective_id, active, total_weight,
                     create_date, write_date)
                VALUES %s
            ''', job_objective_values)
            job_context = {row[0]: (units[row[2]], jobs[row[3]],
                                    nullable(perspectives, row[6], 'job perspective'), row[5])
                           for row in source['job_objectives']}
            job_measure_values = [(
                row[0], row[1], row[2], *job_context[row[2]],
                row[3], row[4], row[5], row[6], row[7],
            ) for row in source['job_measures']]
            execute_values(cursor, '''
                INSERT INTO performance_job_measure
                    (id, name, job_objective_id, operating_unit_id, job_id,
                     perspective_id, parent_objective_id, weight, target_type,
                     active, create_date, write_date)
                VALUES %s
            ''', job_measure_values)
            for table in TABLES:
                cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,))
                sequence = cursor.fetchone()[0]
                if sequence:
                    cursor.execute('SELECT setval(%s, (SELECT max(id) FROM ' + table + '))',
                                   (sequence,))
            for table, expected in zip(TABLES, (
                len(source['objectives']), len(source['measures']),
                len(source['job_objectives']), len(source['job_measures']),
            )):
                cursor.execute('SELECT count(*) FROM ' + table)
                if cursor.fetchone()[0] != expected:
                    raise ValueError('Imported count mismatch in %s' % table)
        local.commit()
        print('Imported PMS definitions and committed all four tables.')
    except Exception:
        local.rollback()
        raise
    finally:
        remote.close()
        local.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    main(parser.parse_args().apply)
