import csv
import datetime
import io
import os

from chalice.test import Client
import pytest

from chalicelib.sccjs import SCCJS


SCCJS_USERNAME = os.environ.get('SCCJS_USERNAME')
SCCJS_PASSWORD = os.environ.get('SCCJS_PASSWORD')
DATE = datetime.date.fromisoformat('2023-04-26')

@pytest.fixture(scope="module")
def vcr_config():
    return {"filter_headers": ["authorization"]}

@pytest.mark.vcr
def test_get_data():
    data = SCCJS(SCCJS_USERNAME, SCCJS_PASSWORD, entity='courtroom').get_data(DATE, DATE)
    
    # write and immediately read CSV to ensure expected serialization
    csv_data = io.StringIO()
    writer = csv.DictWriter(csv_data, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    data_reader = csv.DictReader(io.StringIO(csv_data.getvalue()))

    # happy to let the process exiting close the file handle
    expected_data_fp = open('test/fixtures/test_get_data.csv', newline='')
    expected_data_reader = csv.DictReader(expected_data_fp)

    for line, expected_line in zip(data_reader, expected_data_reader):
        assert line == expected_line
