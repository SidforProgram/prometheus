docker run --rm -it -v "${PWD}:/opt" -v "mibs:/root/.snmp/mibs" prom/snmp-generator generate
sed  -i 's/hh3cEntityExtCpuUsage/SwitchCpuUsage/g' snmp.yml
sed  -i 's/hh3cEntityExtMemUsage/SwitchMemUsage/g' snmp.yml
sed  -i 's/ciscoMemoryPoolUsed/SwitchMemUsed/g' snmp.yml
sed  -i 's/ciscoMemoryPoolFree/SwitchMemFree/g' snmp.yml
sed  -i 's/cpmCPUTotal5minRev/SwitchCpuUsage/g' snmp.yml
