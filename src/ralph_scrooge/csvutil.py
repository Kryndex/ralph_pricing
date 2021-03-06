#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Unicode reader and writer for CSV.
Code from http://docs.python.org/library/csv.html
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import codecs
import cStringIO
import csv

from django.http import HttpResponse


class excel_semicolon(csv.excel):
    delimiter = b';'


class UTF8Recoder:
    """
    Iterator that reads an encoded stream and reencodes the input to UTF-8
    """
    def __init__(self, f, encoding):
        self.reader = codecs.getreader(encoding)(f)

    def __iter__(self):
        return self

    def next(self):
        return self.reader.next().encode("utf-8")


class UnicodeReader:
    """
    A CSV reader which will iterate over lines in the CSV file "f",
    which is encoded in the given encoding.
    """

    def __init__(self, f, dialect=excel_semicolon, encoding="utf-8", **kwds):
        f = UTF8Recoder(f, encoding)
        self.reader = csv.reader(f, dialect=dialect, **kwds)

    def next(self):
        row = self.reader.next()
        return [unicode(s, "utf-8") for s in row]

    def __iter__(self):
        return self


class UnicodeWriter:
    """
    A CSV writer which will write rows to CSV file "f",
    which is encoded in the given encoding.
    """

    def __init__(self, f, dialect=excel_semicolon, encoding="utf-8", **kwds):
        # Redirect output to a queue
        self.queue = cStringIO.StringIO()
        self.writer = csv.writer(self.queue, dialect=dialect, **kwds)
        self.stream = f
        self.encoder = codecs.getincrementalencoder(encoding)()

    def writerow(self, row):
        self.writer.writerow([s.encode("utf-8") for s in row])
        # Fetch UTF-8 output from the queue ...
        data = self.queue.getvalue()
        data = data.decode("utf-8")
        # ... and reencode it into the target encoding
        data = self.encoder.encode(data)
        # write to the target stream
        self.stream.write(data)
        # empty queue
        self.queue.truncate(0)

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


def make_csv_response(data=[], filename='export.csv', encoding='cp1250'):
    """
    Create a HTTP response for downloading a CSV file with provided data.

    :param data - list of rows of data
    :param filename - the name of the file to be downloaded

    How to use:
    >>> rows = [
    ...    ['CAR', 'COLOR'],
    ...    ['Ford', 'Red'],
    ...    ['BMW', 'Black'],
    ... ]
    >>> response = make_csv_response(data=rows, filename='myfile.csv')
    """

    f = cStringIO.StringIO()
    UnicodeWriter(f, encoding=encoding).writerows(
        (unicode(item) for item in row) for row in data
    )
    response = HttpResponse(f.getvalue(), content_type='application/csv')
    disposition = 'attachment; filename=%s' % filename
    response['Content-Disposition'] = disposition
    return response


class scrooge_dialect(csv.excel):

    delimiter = str(';')


csv.register_dialect('scrooge', scrooge_dialect)


def parse_csv(file):
    """
    Parse CSV file.

    Args:
        file: Python file object

    Returns:
        tuple: headers from first line, result list.
    """
    reader = UnicodeReader(file, dialect=scrooge_dialect)
    result = []
    rows = list(reader)
    headers = rows[0]
    for row in rows[1:]:
        line = {}
        for i, item in enumerate(headers):
            line[item] = row[i]
        result.append(line)

    return (headers, result)
