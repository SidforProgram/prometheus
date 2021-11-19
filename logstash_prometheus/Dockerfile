# Dockerfile for ELK stack  logstash
# Elasticsearch, Logstash, Kibana 7.2.0

# Build with:
# docker build -t <repo-user>/elk .

# Run with:
# docker run -p 5601:5601 -p 9200:9200 -p 5044:5044 -it --name elk <repo-user>/elk

#FROM ubuntu
#process the Rapid7 VA report with csv format transform to logstash
#for microsoft ad event log
FROM docker.elastic.co/logstash/logstash-oss:7.10.2
MAINTAINER tony
ENV \
 REFRESHED_AT=2021-09-01 

###############################################################################
#                                INSTALLATION
###############################################################################



### configure logrotate

RUN $HOME/bin/logstash-plugin update logstash-input-beats 

###############################################################################
#                                   START
###############################################################################
WORKDIR /usr/share/logstash/config
COPY --chown=logstash:logstash ./logstash.yml ./
COPY --chown=logstash:logstash ./pipelines.yml ./
COPY --chown=logstash:logstash ./logstash.keystore ./

WORKDIR /etc/logstash
COPY --chown=logstash:root ./logstash-conf/ ./

EXPOSE 5044/udp
ENTRYPOINT ["/usr/local/bin/docker-entrypoint"]






