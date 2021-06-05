FROM python:3-alpine

WORKDIR /src

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY chalicelib/sccjs.py .

ENTRYPOINT [ "python", "sccjs.py" ]
