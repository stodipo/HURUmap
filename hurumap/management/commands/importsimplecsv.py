import csv
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from wazimap.data.utils import get_session
from wazimap.data.tables import get_datatable, get_table_id


import logging

logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARN)

"""
This is a helper script that reads in a structured CSV file with
column names that match the database columns to be created
and imports the data into the Wazi database, creating tables as necessary.
A total column is expected.

https://github.com/OpenUpSA/wazimap-za/blob/master/wazimap_za/management/commands/importsimplecsv.py
"""


class Command(BaseCommand):
    help = ("Imports data from a structured CSV file. " +
            "The database table is automatically created from the fields in " +
            "the file headers. Must be in the format" +
            "geo_level, geo_code, [fields], total")

    def add_arguments(self, parser):
        parser.add_argument(
            'filepath',
            action='store',
            help='The file path to a structured CSV file'
        )
        parser.add_argument(
            '--table',
            action='store',
            dest='table',
            default=None,
            help='The name of the database table where the imported data will be stored. '
                 'If not provided, it is generated from the field names'
        )
        parser.add_argument(
            '--release_year',
            action='store',
            dest='release_year',
            default=None,
            help='The release year for the database table being imported.'
        )
        parser.add_argument(
            '--geo_version',
            action='store',
            dest='geo_version',
            default='2011',
            help='The the value for the geo_version column for this data. Default: 2011'
        )
        parser.add_argument(
            '--value_type',
            action='store',
            dest='value_type',
            default='Integer',
            help='The type of values used in the total column: Integer or Float'
        )
        parser.add_argument(
            '--add_to_100',
            action='store_true',
            dest='add_to_100',
            default=False,
            help="Should values of final field combination add to 100%% for each geo",
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dryrun',
            default=False,
            help="Dry-run, don't actuall write any data.",
        )

    def debug(self, msg):
        if self.verbosity >= 2:
            self.stdout.write(str(msg))

    def handle(self, *args, **options):
        self.filepath = options['filepath']

        self.verbosity = options.get('verbosity', 1)
        self.table_id = options.get('table')
        self.release_year = options.get('release_year')
        self.geo_version = options.get('geo_version')
        self.value_type = options.get('value_type', 'Integer')
        self.add_to_100 = options.get('add_to_100', False)
        self.dryrun = options.get('dryrun', False)

        if self.dryrun:
            self.stdout.write("DRY RUN: not actually writing data")

        with open(self.filepath) as f:
            self.f = f
            self.reader = csv.DictReader(self.f, delimiter=",")
            # Fields excluding geo_level, geo_code and total
            self.fields = self.reader.fieldnames[2:-1]

            self.setup_table()
            self.store_values()

    def setup_table(self):
        table_id = self.table_id or get_table_id(self.fields)
        try:
            table_model = get_datatable(table_id)
            release = table_model.get_release(year=self.release_year)
            self.table = table_model.get_db_table(release=release)
            self.stdout.write("Table for fields %s is %s" % (self.fields, self.table.id))
        except KeyError:
            raise CommandError("Couldn't establish which table to use for these fields. Have you added a FieldTable entry in wazimap_za/tables.py?\nFields: %s" % self.fields)


    def store_values(self):
        session = get_session()
        count = 0
        geo = None
        totals = defaultdict(float)
        for row in self.reader:
            count += 1
            row['geo_version'] = self.geo_version

            if row['total'] == 'no data':
                row['total'] = None
            else:
                row['total'] = round(float(row['total']), 1) if self.value_type == 'Float' else int(round(float(row['total'])))

            if self.add_to_100 == True:
                geo = row['geo_level'], row['geo_code']
                field_values = tuple(row[field] for field in self.fields[:-1])
                key = (geo + field_values)

                if row['total']:
                    totals[key] += row['total']
                    if totals[key] > 100:
                        diff = totals[key] - 100
                        row['total'] = row['total'] - diff

            if self.value_type == 'Float' and row['total']:
                row['total'] = str(row['total'])
            self.stdout.write("%s-%s" % (row['geo_level'], row['geo_code']))
            entry = self.table.model(**row)

            if not self.dryrun:
                session.add(entry)

            if count % 100 == 0:
                session.flush()

        if not self.dryrun:
            session.commit()

        session.close()