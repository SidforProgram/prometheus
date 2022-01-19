docker run --user $(id -u):$(id -g) --rm --name grafana-backup-tool \
	   --env-file .grafana_backup \
           -v /tmp/backup/:/opt/grafana-backup-tool/_OUTPUT_ \
           grafana-backup:1
