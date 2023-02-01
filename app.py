import datetime

import boto3
from chalice import Chalice, CORSConfig
from chalicelib.sccjs import SCCJS

app = Chalice(app_name='sccjs')

cors_config = CORSConfig(
    allow_origin='https://bradshjg.github.io',
    allow_headers=['HX-Current-URL', 'HX-Request', 'HX-Target'],
    max_age=600,
    expose_headers=['HX-Current-URL', 'HX-Request', 'HX-Target'],
)

@app.route('/', methods=['POST'], cors=cors_config)
def submit():
    request_json = app.current_request.json_body

    try:
        username = request_json['username']
        password = request_json['password']
        start_date = request_json['start_date']
        end_date = request_json['end_date']
        search_type = request_json['search_type']
    except KeyError:
        return {'sucess': False, 'message': 'invalid payload'}

    try:
        datetime.datetime.strptime(start_date, SCCJS.DATE_FORMAT)
    except ValueError:
        return {'success': False, 'message': 'invalid start date'}

    try:
        datetime.datetime.strptime(end_date, SCCJS.DATE_FORMAT)
    except ValueError:
        return {'success': False, 'message': 'invalid end date'}

    if start_date > end_date:
        return {'success': False, 'message': 'end date must be on or after start date'}

    try:
        SCCJS(username, password, verify=True)
    except SCCJS.LoginFailed:
        return {'success': False, 'message': 'login failed'}

    ecs_client = boto3.client("ecs", region_name="us-east-1")
    response = ecs_client.run_task(
        cluster='sccjs',
        launchType='FARGATE',
        taskDefinition='sccjs:2',
        networkConfiguration={
            'awsvpcConfiguration': {
                'subnets': [
                    'subnet-0b12f999d81ec4965',
                    'subnet-0c76add5090a242c5',
                    'subnet-0f75bf22dbf03deea',
                    'subnet-04a34b29f041a8bd1',
                    'subnet-09e5c9ff165ebdab3',
                    'subnet-065e9ed7d17202b73'
                ],
                'assignPublicIp': 'ENABLED'
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": "sccjs",
                    "command": [username, password, start_date, end_date, search_type],
                }
            ]
        }
    )

    if response['failures']:
        response_body = {
            'success': False,
            'message': 'task failed to launch',
            'context': {
                'failures': response['failures']
            }
        }
    else:
        response_body = {
            'success': True,
            'message': 'task launched',
            'context': {
                'taskArn': response['tasks'][0]['taskArn']
            }
        }

    return response_body
