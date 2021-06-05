# SCCJS Data

`docker build -t sccjs .`

# SCCJS Data

## Running Locally

Create `.env` like

```
# for sending emails
AWS_ACCESS_KEY_ID=super
AWS_SECRET_ACCESS_KEY=secret

# debug stuff
SCCJS_DEBUG=1 # limit the amount of data grabbed
SCCJS_SEND_EMAIL=1 # by default data is printed to stdout if SCCJS_DEBUG is set, this sends the email anyways
SCCJS_EMAIL_TO=override@email.com # by default the first arg is used for sending emails (the login username)
```

`docker run --rm --env-file .env sccjs 'user@email.com' 'password' 2021-06-03 2021-06-04`

The passed args are the start and end dates to search for hearings.
