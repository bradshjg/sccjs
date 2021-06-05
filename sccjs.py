import csv
import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import os
import sys

import boto3
from bs4 import BeautifulSoup
import requests

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DEBUG = os.environ.get('SCCJS_DEBUG', False)
SEND_EMAIL = os.environ.get('SCCJS_SEND_EMAIL', False)

class SCCJS:
    LOGIN_AUTH_TOKEN_NAME = '__RequestVerificationToken'
    LOGIN_GET_URL = 'https://cjs.shelbycountytn.gov/CJS/Account/Login'
    LOGIN_POST_URL = 'https://cjs.shelbycountytn.gov/CJS/'
    SEARCH_URL = 'https://cjs.shelbycountytn.gov/CJS/Hearing/SearchHearings/HearingSearch'
    SEARCH_READ_URL = 'https://cjs.shelbycountytn.gov/CJS/Hearing/HearingResults/Read'
    CASE_URL = 'https://cjs.shelbycountytn.gov/CJS/Case/CaseDetail'
    JUDGE_IDS = ["1028", "1025", "1023", "1022", "1030", "1031", "1075", "1032"]
    HEARING_TYPES = ["AR", "AR2", "AT", "FA"]

    class LoginFailed(Exception):
        pass

    def __init__(self, username, password) -> None:
        self.username = username
        self.password = password
        self._session = None

    def get_data(self, start_date, end_date):
        hearings = []

        if DEBUG:
            judge_ids = self.JUDGE_IDS[0:2]
        else:
            judge_ids = self.JUDGE_IDS

        dates = (start_date + datetime.timedelta(days=i) for i in range((end_date - start_date).days + 1))

        for date in dates:
            for judge_id in judge_ids:
                logger.info(f'getting hearings for judge with id {judge_id} on {date.strftime("%Y-%m-%d")}')
                for hearing in self._get_hearings(judge_id, date):
                    encrypted_case_id = hearing['EncryptedCaseId']
                    extended_hearing_data = self._get_hearing(encrypted_case_id)
                    hearing_data = {
                        'hearing_date': hearing['HearingDate'],
                        'hearing_type': hearing['HearingTypeId']['Description'],
                        'judge_name': hearing['JudgeParsed'],
                        'defendant_case_type': hearing['CaseTypeId']['Description'],
                        'charges': extended_hearing_data['charges'],
                        'case_number': hearing['CaseNumber'],
                        'defendant_name': hearing['DefendantName'],
                        'defendant_address': extended_hearing_data['address'],
                        'defendant_has_attorney': extended_hearing_data['attorney'],
                        'hearing_details': f'https://cjs.shelbycountytn.gov/CJS/Case/CaseDetail?eid={encrypted_case_id}'
                    }
                    hearings.append(hearing_data)
        return hearings

    def _get_session(self):
        if self._session is not None:
            return self._session
        session = requests.session()
        login_get_resp = session.get(self.LOGIN_GET_URL)
        login_get_resp.raise_for_status()
        login_get_parsed = BeautifulSoup(login_get_resp.content, 'html.parser')
        token = login_get_parsed.find('input', {'name': self.LOGIN_AUTH_TOKEN_NAME})
        login_data = {
            self.LOGIN_AUTH_TOKEN_NAME: token.get('value'),
            'UserName': self.username,
            'Password': self.password
        }
        login_post_resp = session.post(login_get_resp.url, data=login_data)
        login_post_resp.raise_for_status()
        login_post_parsed = BeautifulSoup(login_post_resp.content, 'html.parser')
        sso_data = {
            hidden_input.get('name'): hidden_input.get('value')
            for hidden_input in login_post_parsed.find_all('input', {'type': 'hidden'})
        }
        action = login_post_parsed.find('form').get('action')
        if action != self.LOGIN_POST_URL:
            raise self.LoginFailed
        session.post(action, data=sso_data).raise_for_status()
        self._session = session
        return session

    def _get_hearings(self, judge_id, date):
        session = self._get_session()
        formatted_date = date.strftime('%m/%d/%Y')
        session.post(self.SEARCH_URL,
        data = {
            "PortletName": "HearingSearch",
            "Settings.CaptchaEnabled": "False",
            "Settings.DefaultLocation": "All Locations",
            "SearchCriteria.SelectedCourt": "All Locations",
            "SearchCriteria.SelectedHearingType": "All Hearing Types",
            "SearchCriteria.SearchByType": "JudicialOfficer",
            "SearchCriteria.SelectedJudicialOfficer": judge_id,
            "SearchCriteria.DateFrom": formatted_date,
            "SearchCriteria.DateTo": formatted_date,
        })

        resp = session.post(self.SEARCH_READ_URL,
        data = {
            "sort": "",
            "group": "",
            "filter": "",
            "portletId": "27",
        })

        hearing_data = resp.json()['Data']

        return filter(lambda hearing: hearing["HearingTypeId"]["Word"] in self.HEARING_TYPES, hearing_data)

    def _get_hearing(self, eid):
        resp = requests.get(self.CASE_URL, params={'eid': eid})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, 'html.parser')
        address_header = soup.find('span', class_='text-muted', text='Address')
        charge_descriptions = soup.find_all(class_='chargeOffenseDescription')
        if address_header:
            address = ' '.join(address_header.next_sibling.next_sibling.text.split())
        else:
            address = ''
        if charge_descriptions:
            charges = ', '.join(map(lambda el: f'{el.text} - {el.parent.next_sibling.next_sibling.text}', charge_descriptions))
        else:
            charges = ''
        attorney = bool(soup.find('span', class_='text-muted', text='Lead Attorney'))
        return {'address': address, 'attorney': attorney, 'charges': charges}


def send_email_with_attachment(email_from, email_to, start, end, csv_fp):
    msg = MIMEMultipart()
    msg["Subject"] = f"SCCJS leads for {start} to {end}"
    msg["From"] = email_from
    msg["To"] = email_to

    # Set message body
    body = MIMEText("Data attached.", "plain")
    msg.attach(body)

    part = MIMEApplication(csv_fp.read())
    part.add_header("Content-Disposition",
                    "attachment",
                    filename='leads.csv')
    msg.attach(part)

    # Convert message to string and send
    ses_client = boto3.client("ses", region_name="us-east-1")
    response = ses_client.send_raw_email(
        Source=email_from,
        Destinations=[email_to],
        RawMessage={"Data": msg.as_string()}
    )
    print(response)


if __name__ == '__main__':
    DATE_FORMAT = '%Y-%m-%d'
    DATA_FILE = 'data.csv'

    email_from = os.environ['SCCJS_EMAIL_FROM']

    username = sys.argv[1]
    password = sys.argv[2]
    start_date_raw = sys.argv[3]
    end_date_raw = sys.argv[4]
    email_to = os.environ.get('SCCJS_EMAIL_TO', username)

    start_date = datetime.datetime.strptime(start_date_raw, DATE_FORMAT)
    end_date = datetime.datetime.strptime(end_date_raw, DATE_FORMAT)

    data = SCCJS(username, password).get_data(start_date, end_date)

    if not data:
        logger.warning('no hearings found')
        sys.exit(0)

    with open(DATA_FILE, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)

    with open(DATA_FILE, 'rb') as fp:
        if DEBUG and not SEND_EMAIL:
            logger.info('would have sent e-mail to %s', email_to)
            for line in fp:
                print(line.decode('utf-8'), end='')
        else:
            send_email_with_attachment(email_from, email_to, start_date_raw, end_date_raw, fp)
