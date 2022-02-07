taragetip=$(hostname -I | cut -d' ' -f1)
sed -i 's/10.11.233.103/'"$taragetip"'/g' ./prometheus/prometheus.yml
