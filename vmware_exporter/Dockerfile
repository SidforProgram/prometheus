FROM python:3.9-alpine

LABEL MAINTAINER="Daniel Pryor <daniel@pryorda.net> modified by sid"
LABEL NAME=vmware_exporter

WORKDIR /opt/vmware_exporter/
COPY . /opt/vmware_exporter/

RUN set -x; buildDeps="gcc python3-dev musl-dev libffi-dev openssl openssl-dev rust cargo" \
 && apk add --no-cache --update $buildDeps \
 && pip install -r requirements.txt  \
 && apk del $buildDeps

EXPOSE 9272

ENV PYTHONUNBUFFERED=1


CMD ["/opt/vmware_exporter/vmware_exporter/vmware_exporter.py"]
ENTRYPOINT ["python3"]
