import csv
import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import os
import ssl
import sys

import boto3
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter, Retry
import urllib3


class TimeoutHTTPAdapter(HTTPAdapter):
    TIMEOUT = 5  # seconds

    def __init__(self, *args, ssl_context,  **kwargs):
        self.ssl_context = ssl_context
        self.timeout = self.TIMEOUT
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False):
        self._pool_connections = connections
        self._pool_maxsize = maxsize
        self._pool_block = block

        self.poolmanager = urllib3.poolmanager.PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=self.ssl_context
        )

    def send(self, request, **kwargs):
        kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DEBUG = os.environ.get('SCCJS_DEBUG', False)
SEND_EMAIL = os.environ.get('SCCJS_SEND_EMAIL', False)


class SCCJS:
    DATE_FORMAT = '%Y-%m-%d'
    LOGIN_AUTH_TOKEN_NAME = '__RequestVerificationToken'
    LOGIN_GET_URL = 'https://cjs.shelbycountytn.gov/CJS/Account/Login'
    LOGIN_POST_URL = 'https://cjs.shelbycountytn.gov/CJS/'
    SEARCH_URL = 'https://cjs.shelbycountytn.gov/CJS/Hearing/SearchHearings/HearingSearch'
    SEARCH_READ_URL = 'https://cjs.shelbycountytn.gov/CJS/Hearing/HearingResults/Read'
    CASE_URL = 'https://cjs.shelbycountytn.gov/CJS/Case/CaseDetail'
    JUDGE_IDS = [
      "1022",   # Anderson, William Bill
      "1030",   # Massey, Karen
      "1031",   # Lucchesi, Ronald
      "1032",   # Montesi, Louis J., Jr.
      "26775",  # Wilson, Lee
      "26776",  # Renfroe, Sheila B.
      "26777",  # Gilbert, Greg
      "26778",  # Johnson, Christian R.
    ]
    COURTROOM_IDS = [
      "1083",  # 7
      "1103",  # 7
      "1085",  # 8
      "1104",  # 8
      "1087",  # 9
      "1105",  # 9
      "1088",  # 10
      "1106",  # 10
    ]
    HEARING_TYPES = ["AR", "AR2", "AT", "FA"]
    ENTITIES = {
      "judge": {
        "search_type": "JudicialOfficer",
        "search_key": "SearchCriteria.SelectedJudicialOfficer",
        "entities": JUDGE_IDS,
      },
      "courtroom": {
        "search_type": "Courtroom",
        "search_key": "SearchCriteria.SelectedCourtroom",
        "entities": COURTROOM_IDS,
      }
    }
    MISSING_DATA_MESSAGE = 'UNKNOWN'

    class LoginFailed(Exception):
        pass

    def __init__(self, username, password, verify=False, entity="judge") -> None:
        self.username = username
        self.password = password
        self._logged_in_session = None
        self._anonymous_session = None
        self._entity = entity
        self._entity_map = self.ENTITIES[entity]
        self._search_type = self._entity_map["search_type"]
        self._search_key = self._entity_map["search_key"]
        if DEBUG:
          self._entities = self._entity_map["entities"][0:2]
        else:
          self._entities = self._entity_map["entities"]
        if verify:
            self._get_logged_in_session()

    def get_data(self, start_date, end_date):
        hearings = []

        dates = (start_date + datetime.timedelta(days=i) for i in range((end_date - start_date).days + 1))

        for date in dates:
            for entity_id in self._entities:
                logger.info(f'getting hearings for {self._entity} with id {entity_id} on {date.strftime(self.DATE_FORMAT)}')
                for hearing in self._get_hearings(entity_id, date):
                    encrypted_case_id = hearing['EncryptedCaseId']
                    extended_hearing_data = self._get_hearing(encrypted_case_id)
                    hearing_data = {
                        'hearing_date': hearing['HearingDate'],
                        'hearing_type': hearing['HearingTypeId']['Description'],
                        'judge_name': hearing['JudgeParsed'],
                        'defendant_case_type': hearing['CaseTypeId']['Description'],
                        'charges': extended_hearing_data.get('charges', self.MISSING_DATA_MESSAGE),
                        'case_number': hearing['CaseNumber'],
                        'defendant_name': hearing['DefendantName'],
                        'defendant_address': extended_hearing_data.get('address', self.MISSING_DATA_MESSAGE),
                        'defendant_has_attorney': extended_hearing_data.get('attorney', self.MISSING_DATA_MESSAGE),
                        'hearing_details': f'https://cjs.shelbycountytn.gov/CJS/Case/CaseDetail?eid={encrypted_case_id}'
                    }
                    hearings.append(hearing_data)
        return hearings

    def _get_session(self):
        session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
        )
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.options |= 0x4
        session.mount("https://", TimeoutHTTPAdapter(max_retries=retry_strategy, ssl_context=ctx))
        return session

    def _get_anonymous_session(self):
        if self._anonymous_session is not None:
            return self._anonymous_session
        self._anonymous_session = self._get_session()
        return self._anonymous_session

    def _get_logged_in_session(self):
        if self._logged_in_session is not None:
            return self._logged_in_session
        session = self._get_session()
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
        self._logged_in_session = session
        return self._logged_in_session

    def _get_hearings(self, entity_id, date):
        session = self._get_logged_in_session()
        formatted_date = date.strftime('%m/%d/%Y')
        session.post(self.SEARCH_URL,
                     data={
                         "PortletName": "HearingSearch",
                         "Settings.CaptchaEnabled": "False",
                         "Settings.DefaultLocation": "All Locations",
                         "SearchCriteria.SelectedCourt": "All Locations",
                         "SearchCriteria.SelectedHearingType": "All Hearing Types",
                         "SearchCriteria.SearchByType": self._search_type,
                         self._search_key: entity_id,
                         "SearchCriteria.DateFrom": formatted_date,
                         "SearchCriteria.DateTo": formatted_date,
                     })

        resp = session.post(self.SEARCH_READ_URL,
                            data={
                                "sort": "",
                                "group": "",
                                "filter": "",
                                "portletId": "27",
                            })

        hearing_data = resp.json()['Data']

        return filter(lambda hearing: hearing["HearingTypeId"]["Word"] in self.HEARING_TYPES, hearing_data)

    def _get_hearing(self, eid):
        session = self._get_anonymous_session()
        resp = session.get(self.CASE_URL, params={'eid': eid})
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            logger.warning(e)
            return {}
        soup = BeautifulSoup(resp.content, 'html.parser')
        address_header = soup.find('span', class_='text-muted', string='Address')
        charge_descriptions = soup.find_all(class_='chargeOffenseDescription')
        if address_header:
            address = ' '.join(address_header.next_sibling.next_sibling.text.split())
        else:
            address = ''
        if charge_descriptions:
            charges = ', '.join(
                map(lambda el: f'{el.text} - {el.parent.next_sibling.next_sibling.text}', charge_descriptions))
        else:
            charges = ''
        attorney = bool(soup.find('span', class_='text-muted', string='Lead Attorney'))
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
    DATA_FILE = 'data.csv'

    email_from = os.environ['SCCJS_EMAIL_FROM']

    username = sys.argv[1]
    password = sys.argv[2]
    start_date_raw = sys.argv[3]
    end_date_raw = sys.argv[4]
    try:
      entity_type = sys.argv[5]
    except IndexError:
      entity_type = "judge"

    email_to = os.environ.get('SCCJS_EMAIL_TO', username)

    start_date = datetime.datetime.strptime(start_date_raw, SCCJS.DATE_FORMAT)
    end_date = datetime.datetime.strptime(end_date_raw, SCCJS.DATE_FORMAT)

    data = SCCJS(username, password, entity=entity_type).get_data(start_date, end_date)

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
