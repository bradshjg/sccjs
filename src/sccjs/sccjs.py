import csv
import logging
import os
import sys

from bs4 import BeautifulSoup
import requests

logging.basicConfig()
logger = logging.getLogger(__name__)

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
    
    def get_data(self, date):
        hearings = []
        for judge_id in self.JUDGE_IDS:
            for hearing in self._get_hearings(judge_id, date):
                encrypted_case_id = hearing['EncryptedCaseId']
                hearing_data = {
                    'case_number': hearing['CaseNumber'],
                    'encrypted_case_id': encrypted_case_id,
                    'defendant_name': hearing['DefendantName'],
                    'case_type': hearing['CaseTypeId']['Description'],
                    'hearing_details': f'https://cjs.shelbycountytn.gov/CJS/Case/CaseDetail?eid={encrypted_case_id}'
                }
                hearings.append(hearing_data)
        logger.info('%s matching hearings', len(hearings))
        for hearing in hearings:
            extended_hearing_data = (self._get_hearing(hearing['encrypted_case_id']))
            hearing.update(extended_hearing_data)
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
        session.post(self.SEARCH_URL,
        data = {
            "PortletName": "HearingSearch",
            "Settings.CaptchaEnabled": "False",
            "Settings.DefaultLocation": "All Locations",
            "SearchCriteria.SelectedCourt": "All Locations",
            "SearchCriteria.SelectedHearingType": "All Hearing Types",
            "SearchCriteria.SearchByType": "JudicialOfficer",
            "SearchCriteria.SelectedJudicialOfficer": judge_id,
            "SearchCriteria.DateFrom": date,
            "SearchCriteria.DateTo": date,
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
        if address_header:
            address = ' '.join(address_header.next_sibling.next_sibling.text.split())
        else:
            address = ''
        attorney = bool(soup.find('span', class_='text-muted', text='Lead Attorney'))
        return {'address': address, 'attorney': attorney}


if __name__ == '__main__':
    date = sys.argv[1]
    username = os.environ['SCCJS_USERNAME']
    password = os.environ['SCCJS_PASSWORD']
    data = SCCJS(username, password).get_data(date)
    with open('data.csv', 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
