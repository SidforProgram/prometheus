#!/usr/bin/env python
# -*- python -*-
# -*- coding: utf-8 -*-
# autopep8'd
"""
Handles collection of metrics for vmware.
"""
from __future__ import print_function

# Generic imports
import argparse
import os
import re
import ssl
import sys
import traceback
import pytz
import logging
import datetime
import yaml
import requests
import datetime

"""
disable annoying urllib3 warning messages for connecting to servers with non verified certificate Doh!
"""
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

"""
For custom attributes
used to plain some list of lists in a single one
"""
from itertools import chain

# Twisted
from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.resource import Resource
from twisted.internet import reactor, endpoints, defer, threads

# VMWare specific imports
from pyVmomi import vim, vmodl
from pyVim import connect

# Prometheus specific imports
from prometheus_client.core import GaugeMetricFamily
from prometheus_client import CollectorRegistry, generate_latest

from helpers import batch_fetch_properties, get_bool_env
from defer import parallelize, run_once_property

from __init__ import __version__

host_final_score =[]
datastore_score = 0
class VmwareCollector():

    def __init__(
            self,
            host,
            username,
            password,
            collect_only,
            specs_size,
            fetch_custom_attributes=False,
            ignore_ssl=False,
            fetch_tags=False,
            fetch_alarms=False,
    ):

        self.host = host
        self.username = username
        self.password = password
        self.ignore_ssl = ignore_ssl
        self.collect_only = collect_only
        self.specs_size = int(specs_size)
        self.vm_score_list = []
        self.host_score_list =[]
        self.host_vm_overload = []
        self._session = None

        # Custom Attributes
        # flag to wheter fetch custom attributes or not
        self.fetch_custom_attributes = fetch_custom_attributes
        # vms, hosts and datastores custom attributes must be stored by their moid
        self._vmsCustomAttributes = {}
        self._hostsCustomAttributes = {}
        self._datastoresCustomAttributes = {}

        # Tags
        # flag to wheter fetch tags or not
        self.fetch_tags = fetch_tags

        # Alarms
        # flag wheter to fetch alarms or not
        self.fetch_alarms = fetch_alarms

        # label names and ammount will be needed later to insert labels from custom attributes
        self._labelNames = {
            'vms': ['vm_name', 'ds_name', 'host_name', 'dc_name', 'cluster_name'],
            'vm_perf': ['vm_name', 'ds_name', 'host_name', 'dc_name', 'cluster_name'],
            'vmguests': ['vm_name', 'ds_name', 'host_name', 'dc_name', 'cluster_name'],
            'snapshots': ['vm_name', 'ds_name', 'host_name', 'dc_name', 'cluster_name'],
            'datastores': ['ds_name', 'dc_name', 'ds_cluster'],
            'hosts': ['host_name', 'dc_name', 'cluster_name'],
            'host_perf': ['host_name', 'dc_name', 'cluster_name'],
        }

        # if tags are gonna be fetched 'tags' will be a label too
        if self.fetch_tags:
            for section in self._labelNames.keys():
                self._labelNames[section] = self._labelNames[section] + ['tags']

        # as label names, metric are going to be used modified later
        # as labels from custom attributes are going to be inserted
        self._metricNames = {
            'vms': [],
            'vm_perf': [],
            'hosts': [],
            'host_perf': [],
            'datastores': [],
        }

    def _create_metric_containers(self):
        metric_list = {}
        metric_list['vms'] = {
            'vmware_vm_power_state': GaugeMetricFamily(
                'vmware_vm_power_state',
                'VMWare VM Power state (On / Off)',
                labels=self._labelNames['vms']),
            'vmware_vm_boot_timestamp_seconds': GaugeMetricFamily(
                'vmware_vm_boot_timestamp_seconds',
                'VMWare VM boot time in seconds',
                labels=self._labelNames['vms']),
            'vmware_vm_num_cpu': GaugeMetricFamily(
                'vmware_vm_num_cpu',
                'VMWare Number of processors in the virtual machine',
                labels=self._labelNames['vms']),
            'vmware_vm_memory_max': GaugeMetricFamily(
                'vmware_vm_memory_max',
                'VMWare VM Memory Max availability in Mbytes',
                labels=self._labelNames['vms']),
            'vmware_vm_memory_usage': GaugeMetricFamily(
                'vmware_vm_memory_usage',
                'VMWare VM Memory usage availability in Mbytes',
                labels=self._labelNames['vms']),
            'vmware_vm_max_cpu_usage': GaugeMetricFamily(
                'vmware_vm_max_cpu_usage',
                'VMWare VM Cpu Max availability in hz',
                labels=self._labelNames['vms']),
            'vmware_vm_memory_usedpercent': GaugeMetricFamily(
                'vmware_vm_memory_usedpercent',
                'VMWare VM Memory usage  percent availability in Mbytes',
                labels=self._labelNames['vms']),
            'vmware_vm_cpu_usedpercent': GaugeMetricFamily(
                'vmware_vm_cpu_usedpercent',
                'VMWare VM CPU usage  percent availability in Mbytes',
                labels=self._labelNames['vms']),
        }
        metric_list['vmguests'] = {
            'vmware_vm_guest_disk_free': GaugeMetricFamily(
                'vmware_vm_guest_disk_free',
                'Disk metric per partition',
                labels=self._labelNames['vmguests'] + ['partition', ]),
            'vmware_vm_guest_disk_capacity': GaugeMetricFamily(
                'vmware_vm_guest_disk_capacity',
                'Disk capacity metric per partition',
                labels=self._labelNames['vmguests'] + ['partition', ]),
            'vmware_vm_guest_disk_usage': GaugeMetricFamily(
                'vmware_vm_guest_disk_usage',
                'Disk usage metric per partition',
                labels=self._labelNames['vmguests'] + ['partition', ]),
            'vmware_vm_guest_disk_usedpercent': GaugeMetricFamily(
                'vmware_vm_guest_disk_usedpercent',
                'Disk usage metric per partition',
                labels=self._labelNames['vmguests'] + ['partition', ]),
            'vmware_vm_guest_tools_running_status': GaugeMetricFamily(
                'vmware_vm_guest_tools_running_status',
                'VM tools running status',
                labels=self._labelNames['vmguests'] + ['tools_status', ]),
            'vmware_vm_guest_tools_version': GaugeMetricFamily(
                'vmware_vm_guest_tools_version',
                'VM tools version',
                labels=self._labelNames['vmguests'] + ['tools_version', ]),
            'vmware_vm_perf_score': GaugeMetricFamily(
                'vmware_vm_perf_score',
                'VM performance score ',
                labels=self._labelNames['vmguests'] + ['partition', ]),
            
        }
        metric_list['snapshots'] = {
            'vmware_vm_snapshots': GaugeMetricFamily(
                'vmware_vm_snapshots',
                'VMWare current number of existing snapshots',
                labels=self._labelNames['snapshots']),
            'vmware_vm_snapshot_timestamp_seconds': GaugeMetricFamily(
                'vmware_vm_snapshot_timestamp_seconds',
                'VMWare Snapshot creation time in seconds',
                labels=self._labelNames['snapshots'] + ['vm_snapshot_name']),
        }
        metric_list['datastores'] = {
            'vmware_datastore_capacity_size': GaugeMetricFamily(
                'vmware_datastore_capacity_size',
                'VMWare Datasore capacity in bytes',
                labels=self._labelNames['datastores']),
            'vmware_datastore_freespace_size': GaugeMetricFamily(
                'vmware_datastore_freespace_size',
                'VMWare Datastore freespace in bytes',
                labels=self._labelNames['datastores']),
            'vmware_datastore_uncommited_size': GaugeMetricFamily(
                'vmware_datastore_uncommited_size',
                'VMWare Datastore uncommitted in bytes',
                labels=self._labelNames['datastores']),
            'vmware_datastore_usedpercent': GaugeMetricFamily(
                'vmware_datastore_usedpercent',
                'VMWare Datastore usaged percent in bytes',
                labels=self._labelNames['datastores']),
            'vmware_datastore_provisoned_size': GaugeMetricFamily(
                'vmware_datastore_provisoned_size',
                'VMWare Datastore provisoned in bytes',
                labels=self._labelNames['datastores']),
            'vmware_datastore_hosts': GaugeMetricFamily(
                'vmware_datastore_hosts',
                'VMWare Hosts number using this datastore',
                labels=self._labelNames['datastores']),
            'vmware_datastore_vms': GaugeMetricFamily(
                'vmware_datastore_vms',
                'VMWare Virtual Machines count per datastore',
                labels=self._labelNames['datastores']),
            'vmware_datastore_maintenance_mode': GaugeMetricFamily(
                'vmware_datastore_maintenance_mode',
                'VMWare datastore maintenance mode (normal / inMaintenance / enteringMaintenance)',
                labels=self._labelNames['datastores'] + ['mode']),
            'vmware_datastore_type': GaugeMetricFamily(
                'vmware_datastore_type',
                'VMWare datastore type (VMFS, NetworkFileSystem, NetworkFileSystem41, CIFS, VFAT, VSAN, VFFS)',
                labels=self._labelNames['datastores'] + ['ds_type']),
            'vmware_datastore_perf_score': GaugeMetricFamily(
                'vmware_datastore_perf_score',
                'vmware_datastore_perf_score',
                labels=self._labelNames['datastores'])
        }
        metric_list['hosts'] = {
            'vmware_host_power_state': GaugeMetricFamily(
                'vmware_host_power_state',
                'VMWare Host Power state (On / Off)',
                labels=self._labelNames['hosts']),
            'vmware_host_standby_mode': GaugeMetricFamily(
                'vmware_host_standby_mode',
                'VMWare Host Standby Mode (entering / exiting / in / none)',
                labels=self._labelNames['hosts'] + ['standby_mode_state']),
            'vmware_host_connection_state': GaugeMetricFamily(
                'vmware_host_connection_state',
                'VMWare Host connection state (connected / disconnected / notResponding)',
                labels=self._labelNames['hosts'] + ['state']),
            'vmware_host_maintenance_mode': GaugeMetricFamily(
                'vmware_host_maintenance_mode',
                'VMWare Host maintenance mode (true / false)',
                labels=self._labelNames['hosts']),
            'vmware_host_boot_timestamp_seconds': GaugeMetricFamily(
                'vmware_host_boot_timestamp_seconds',
                'VMWare Host boot time in seconds',
                labels=self._labelNames['hosts']),
            'vmware_host_cpu_max': GaugeMetricFamily(
                'vmware_host_cpu_max',
                'VMWare Host CPU max availability in Mhz',
                labels=self._labelNames['hosts']),
            'vmware_host_cpu_usedpercent': GaugeMetricFamily(
                'vmware_host_cpu_usedpercent',
                'VMWare Host CPU usage percent',
                labels=self._labelNames['hosts']),
            'vmware_host_cpu_total_usage': GaugeMetricFamily(
                'vmware_host_total_cpu_usage',
                'VMWare Host CPU total usage in Mhz',
                labels=self._labelNames['hosts']),
            'vmware_host_cpu_total_max': GaugeMetricFamily(
                'vmware_host_cpu_total_max',
                'VMWare Host CPU total max availability in Mhz',
                labels=self._labelNames['hosts']),
            'vmware_host_cpu_total_usedpercent': GaugeMetricFamily(
                'vmware_host_cpu_total_usedpercent',
                'VMWare Host CPU total usage percent',
                labels=self._labelNames['hosts']),
            'vmware_host_num_cpu': GaugeMetricFamily(
                'vmware_host_num_cpu',
                'VMWare Number of processors in the Host',
                labels=self._labelNames['hosts']),
            'vmware_host_memory_usage': GaugeMetricFamily(
                'vmware_host_memory_usage',
                'VMWare Host Memory usage in Mbytes',
                labels=self._labelNames['hosts']),
            'vmware_host_memory_total_usage': GaugeMetricFamily(
                'vmware_host_memory_total_usage',
                'VMWare Host Memory total usage in Mbytes',
                labels=self._labelNames['hosts']),
            'vmware_host_memory_max': GaugeMetricFamily(
                'vmware_host_memory_max',
                'VMWare Host Memory Max availability in Mbytes',
                labels=self._labelNames['hosts']),
            'vmware_host_memory_total_max': GaugeMetricFamily(
                'vmware_host_memory_total_max',
                'VMWare Host Memory Total Max availability in Mbytes',
                labels=self._labelNames['hosts']),
            'vmware_host_memory_usedpercentage': GaugeMetricFamily(
                'vmware_host_memory_usedpercentage',
                'VMWare Host Memory usage percent in Mbytes',
                labels=self._labelNames['hosts']),
            'vmware_host_memory_total_usedpercentage': GaugeMetricFamily(
                'vmware_host_memory_total_usedpercentage',
                'VMWare Host Memory total usage percent in Mbytes',
                labels=self._labelNames['hosts']),
            'vmware_host_product_info': GaugeMetricFamily(
                'vmware_host_product_info',
                'A metric with a constant "1" value labeled by version and build from os the host.',
                labels=self._labelNames['hosts'] + ['version', 'build']),
            'vmware_host_hardware_info': GaugeMetricFamily(
                'vmware_host_hardware_info',
                'A metric with a constant "1" value labeled by model and cpu model from the host.',
                labels=self._labelNames['hosts'] + ['hardware_model', 'hardware_cpu_model']),
            'vmware_host_sensor_state': GaugeMetricFamily(
                'vmware_host_sensor_state',
                'VMWare sensor state value (0=red / 1=yellow / 2=green / 3=unknown) labeled by sensor name and type '
                'from the host.',
                labels=self._labelNames['hosts'] + ['name', 'type']),
            'vmware_host_sensor_fan': GaugeMetricFamily(
                'vmware_host_sensor_fan',
                'VMWare sensor fan speed value in RPM labeled by sensor name from the host.',
                labels=self._labelNames['hosts'] + ['name']),
            'vmware_host_sensor_temperature': GaugeMetricFamily(
                'vmware_host_sensor_temperature',
                'VMWare sensor temperature value in degree C labeled by sensor name from the host.',
                labels=self._labelNames['hosts'] + ['name']),
            'vmware_host_sensor_power_voltage': GaugeMetricFamily(
                'vmware_host_sensor_power_voltage',
                'VMWare sensor power voltage value in volt labeled by sensor name from the host.',
                labels=self._labelNames['hosts'] + ['name']),
            'vmware_host_sensor_power_current': GaugeMetricFamily(
                'vmware_host_sensor_power_current',
                'VMWare sensor power current value in amp labeled by sensor name from the host.',
                labels=self._labelNames['hosts'] + ['name']),
            'vmware_host_sensor_power_watt': GaugeMetricFamily(
                'vmware_host_sensor_power_watt',
                'VMWare sensor power watt value in watt labeled by sensor name from the host.',
                labels=self._labelNames['hosts'] + ['name']),
            'vmware_host_sensor_redundancy': GaugeMetricFamily(
                'vmware_host_sensor_redundancy',
                'VMWare sensor redundancy value (1=ok / 0=ko) labeled by sensor name from the host.',
                labels=self._labelNames['hosts'] + ['name']),
            'vmware_host_perf_score': GaugeMetricFamily(
                'vmware_host_perf_score',
                'vmware_host_perf_score',
                labels=self._labelNames['hosts']),
            'vmware_cluster_score': GaugeMetricFamily(
                'vmware_cluster_score',
                'vmware_cluster_score',
                labels=self._labelNames['hosts'])
        }

        """
            if alarms are being retrieved, metrics have to been created here
        """
        if self.fetch_alarms:
            """
                for hosts
            """
            metric_list['hosts'].update(
                {
                    'vmware_host_yellow_alarms': GaugeMetricFamily(
                        'vmware_host_yellow_alarms',
                        'A metric with the amount of host yellow alarms and labeled with the list of alarm names',
                        labels=self._labelNames['hosts'] + ['alarms']
                    ),
                    'vmware_host_red_alarms': GaugeMetricFamily(
                        'vmware_host_red_alarms',
                        'A metric with the amount of host red alarms and labeled with the list of alarm names',
                        labels=self._labelNames['hosts'] + ['alarms']
                    )
                }
            )

            """
                for datastores
            """
            metric_list['datastores'].update(
                {
                    'vmware_datastore_yellow_alarms': GaugeMetricFamily(
                        'vmware_datastore_yellow_alarms',
                        'A metric with the amount of datastore yellow alarms and labeled with the list of alarm names',
                        labels=self._labelNames['datastores'] + ['alarms']
                    ),
                    'vmware_datastore_red_alarms': GaugeMetricFamily(
                        'vmware_datastore_red_alarms',
                        'A metric with the amount of datastore red alarms and labeled with the list of alarm names',
                        labels=self._labelNames['datastores'] + ['alarms']
                    )
                }
            )

            """
                for vms
            """
            metric_list['vms'].update(
                {
                    'vmware_vm_yellow_alarms': GaugeMetricFamily(
                        'vmware_vm_yellow_alarms',
                        'A metric with the amount of virtual machine yellow alarms and \
                                labeled with the list of alarm names',
                        labels=self._labelNames['vms'] + ['alarms']
                    ),
                    'vmware_vm_red_alarms': GaugeMetricFamily(
                        'vmware_vm_red_alarms',
                        'A metric with the amount of virtual machine red alarms and \
                                labeled with the list of alarm names',
                        labels=self._labelNames['vms'] + ['alarms']
                    )
                }
            )
            metric_list['vmguests'].update(
                {
                    'vmware_vm_yellow_alarms': GaugeMetricFamily(
                        'vmware_vm_yellow_alarms',
                        'A metric with the amount of virtual machine yellow alarms and \
                                labeled with the list of alarm names',
                        labels=self._labelNames['vms'] + ['alarms']
                    ),
                    'vmware_vm_red_alarms': GaugeMetricFamily(
                        'vmware_vm_red_alarms',
                        'A metric with the amount of virtual machine red alarms and \
                                labeled with the list of alarm names',
                        labels=self._labelNames['vms'] + ['alarms']
                    )
                }
            )
            metric_list['snapshots'].update(
                {
                    'vmware_vm_yellow_alarms': GaugeMetricFamily(
                        'vmware_vm_yellow_alarms',
                        'A metric with the amount of virtual machine yellow alarms and \
                                labeled with the list of alarm names',
                        labels=self._labelNames['vms'] + ['alarms']
                    ),
                    'vmware_vm_red_alarms': GaugeMetricFamily(
                        'vmware_vm_red_alarms',
                        'A metric with the amount of virtual machine red alarms and \
                                labeled with the list of alarm names',
                        labels=self._labelNames['vms'] + ['alarms']
                    )
                }
            )

        metrics = {}
        for key, value in self.collect_only.items():
            if value is True:
                """ storing metric names to be used later """
                self._metricNames[key] = list(metric_list[key].keys())
                metrics.update(metric_list[key])

        return metrics

    @defer.inlineCallbacks
    def collect(self):
        """ collects metrics """
        vsphere_host = self.host

        metrics = self._create_metric_containers()

        logging.info("Start collecting metrics from {vsphere_host}".format(vsphere_host=vsphere_host))

        self._labels = {}

        collect_only = self.collect_only

        tasks = []

        # Collect vm / snahpshot / vmguest metrics
        if collect_only['vmguests'] is True or collect_only['vms'] is True or collect_only['snapshots'] is True:
            tasks.append(self._vmware_get_vms(metrics))

        if collect_only['vms'] is True:
            tasks.append(self._vmware_get_vm_perf_manager_metrics(metrics))
        # Collect Datastore metrics
        if collect_only['datastores'] is True:
            tasks.append(self._vmware_get_datastores(metrics, ))

        if collect_only['hosts'] is True:
            tasks.append(self._vmware_get_hosts(metrics))
            tasks.append(self._vmware_get_host_perf_manager_metrics(metrics))
        yield parallelize(*tasks)
        self._vmware_cluster_status(metrics)
        yield self._vmware_disconnect()
        logging.info("Finished collecting metrics from {vsphere_host}".format(vsphere_host=vsphere_host))
        return list(metrics.values())  # noqa: F705

    def _to_epoch(self, my_date):
        """ convert to epoch time """
        return (my_date - datetime.datetime(1970, 1, 1, tzinfo=pytz.utc)).total_seconds()

    @run_once_property
    @defer.inlineCallbacks
    def session(self):

        if self._session is None:
            self._session = requests.Session()
            self._session.verify = not self.ignore_ssl
            self._session.auth = (self.username, self.password)

            try:
                yield threads.deferToThread(
                    self._session.post,
                    'https://{host}/rest/com/vmware/cis/session'.format(host=self.host)
                )
            except Exception as e:
                logging.error('Error creating vcenter API session ({})'.format(e))
                self._session = None

        return self._session

    @run_once_property
    @defer.inlineCallbacks
    def _tagIDs(self):
        """
        fetch a list of all tags ids
        """
        session = yield self.session
        response = yield threads.deferToThread(
            session.get,
            'https://{host}/rest/com/vmware/cis/tagging/tag'.format(host=self.host)
        )
        output = []
        try:
            output = response.json().get('value')
        except Exception as e:
            logging.error('Unable to fetch tag IDs from vcenter {} ({})'.format(self.host, e))

        return output

    @run_once_property
    @defer.inlineCallbacks
    def _attachedObjectsOnTags(self):
        """
        retrieve a dict with all objects which have a tag attached
        """
        session = yield self.session
        tagIDs = yield self._tagIDs
        jsonBody = {
            'tag_ids': tagIDs
        }
        response = yield threads.deferToThread(
            session.post,
            'https://{host}/rest/com/vmware/cis/tagging/tag-association?~action=list-attached-objects-on-tags'
            .format(host=self.host),
            json=jsonBody
        )

        output = {}

        try:
            output = response.json().get('value', output)
        except Exception as e:
            logging.error('Unable to fetch list of attached objects on tags on vcenter {} ({})'.format(self.host, e))

        return output

    @run_once_property
    @defer.inlineCallbacks
    def _tagNames(self):
        """
        tag IDs are useless to enduser, so they have to be translated
        to the tag text
        """
        session = yield self.session
        tagIDs = yield self._tagIDs
        tagNames = {}
        for tagID in tagIDs:
            response = yield threads.deferToThread(
                session.get,
                'https://{host}/rest/com/vmware/cis/tagging/tag/id:{tag_id}'.format(host=self.host, tag_id=tagID)
            )
            tagObj = response.json().get('value', {})
            if tagObj:
                tagNames[tagObj.get('id')] = tagObj.get('name')

        return tagNames

    @run_once_property
    @defer.inlineCallbacks
    def tags(self):
        """
        tags are finally stored by category: vms, hosts, and datastores
        and linked to object moid
        """
        logging.info("Fetching tags")
        start = datetime.datetime.utcnow()

        attachedObjs = yield self._attachedObjectsOnTags
        tagNames = yield self._tagNames
        tags = {
            'vms': {},
            'hosts': {},
            'datastores': {},
            'others': {},
        }

        sections = {'VirtualMachine': 'vms', 'Datastore': 'datastores', 'HostSystem': 'hosts'}

        for attachedObj in attachedObjs:
            tagName = tagNames.get(attachedObj.get('tag_id'))
            for obj in attachedObj.get('object_ids'):
                section = sections.get(obj.get('type'), 'others')
                if obj.get('id') not in tags[section]:
                    tags[section][obj.get('id')] = [tagName]
                else:
                    tags[section][obj.get('id')].append(tagName)

        fetch_time = datetime.datetime.utcnow() - start
        logging.info("Fetched tags ({fetch_time})".format(fetch_time=fetch_time))

        return tags

    @run_once_property
    @defer.inlineCallbacks
    def connection(self):
        """
        Connect to Vcenter and get connection
        """
        context = None
        if self.ignore_ssl:
            context = ssl._create_unverified_context()

        try:
            vmware_connect = yield threads.deferToThread(
                connect.SmartConnect,
                host=self.host,
                user=self.username,
                pwd=self.password,
                sslContext=context,
            )
            return vmware_connect

        except vmodl.MethodFault as error:
            logging.error("Caught vmodl fault: {error}".format(error=error.msg))
            return None

    @run_once_property
    @defer.inlineCallbacks
    def content(self):
        logging.info("Retrieving service instance content")
        connection = yield self.connection
        content = yield threads.deferToThread(
            connection.RetrieveContent
        )

        logging.info("Retrieved service instance content")
        return content

    @defer.inlineCallbacks
    def batch_fetch_properties(self, objtype, properties):
        content = yield self.content
        batch = yield threads.deferToThread(
            batch_fetch_properties,
            content,
            objtype,
            properties,
        )
        return batch

    @run_once_property
    @defer.inlineCallbacks
    def datastore_inventory(self):
        logging.info("Fetching vim.Datastore inventory")
        start = datetime.datetime.utcnow()
        properties = [
            'name',
            'summary.capacity',
            'summary.freeSpace',
            'summary.uncommitted',
            'summary.maintenanceMode',
            'summary.type',
            'summary.accessible',
            'host',
            'vm',
        ]

        """
        are custom attributes going to be retrieved?
        """
        if self.fetch_custom_attributes:
            """ yep! """
            properties.append('customValue')

        """
            triggeredAlarmState must be fetched to get datastore alarms list
        """
        if self.fetch_alarms:
            properties.append('triggeredAlarmState')

        datastores = yield self.batch_fetch_properties(
            vim.Datastore,
            properties
        )

        """
        once custom attributes are fetched,
        store'em linked to their moid
        if no customValue found for an object
        it get an empty dict
        """
        if self.fetch_custom_attributes:
            self._datastoresCustomAttributes = dict(
                [
                    (ds_moId, ds.get('customValue', {}))
                    for ds_moId, ds in datastores.items()
                ]
            )

        fetch_time = datetime.datetime.utcnow() - start
        logging.info("Fetched vim.Datastore inventory ({fetch_time})".format(fetch_time=fetch_time))

        return datastores

    @run_once_property
    @defer.inlineCallbacks
    def host_system_inventory(self):
        logging.info("Fetching vim.HostSystem inventory")
        start = datetime.datetime.utcnow()
        properties = [
            'name',
            'parent',
            'summary.hardware.numCpuCores',
            'summary.hardware.cpuMhz',
            'summary.hardware.memorySize',
            'summary.config.product.version',
            'summary.config.product.build',
            'runtime.powerState',
            'runtime.standbyMode',
            'runtime.bootTime',
            'runtime.connectionState',
            'runtime.inMaintenanceMode',
            'summary.quickStats.overallCpuUsage',
            'summary.quickStats.overallMemoryUsage',
            'summary.hardware.cpuModel',
            'summary.hardware.model',
            'runtime.healthSystemRuntime.systemHealthInfo.numericSensorInfo',
            'runtime.healthSystemRuntime.hardwareStatusInfo.cpuStatusInfo',
            'runtime.healthSystemRuntime.hardwareStatusInfo.memoryStatusInfo',
        ]

        """
        signal to fetch hosts custom attributes
        yay!
        """
        if self.fetch_custom_attributes:
            properties.append('summary.customValue')

        """
            triggeredAlarmState must be fetched to get host alarms list
            in case of hosts, sensors, cpu and memory status alarms
            are going to be retrieved as well
        """
        if self.fetch_alarms:
            properties.append('triggeredAlarmState')

        host_systems = yield self.batch_fetch_properties(
            vim.HostSystem,
            properties,
        )

        """
        once custom attributes are fetched,
        store'em linked to their moid
        if no customValue found for an object
        it get an empty dict
        """
        if self.fetch_custom_attributes:
            self._hostsCustomAttributes = dict(
                [
                    (host_moId, host.get('summary.customValue', {}))
                    for host_moId, host in host_systems.items()
                ]
            )

        fetch_time = datetime.datetime.utcnow() - start
        logging.info("Fetched vim.HostSystem inventory ({fetch_time})".format(fetch_time=fetch_time))

        return host_systems

    @run_once_property
    @defer.inlineCallbacks
    def vm_inventory(self):
        logging.info("Fetching vim.VirtualMachine inventory")
        start = datetime.datetime.utcnow()
        properties = [
            'name',
            'runtime.host',
            'parent',
            'summary.config.vmPathName',
        ]

        if self.collect_only['vms'] is True:
            properties.extend([
                'runtime.powerState',
                'runtime.bootTime',
                'summary.config.numCpu',
                'summary.config.memorySizeMB',
                'summary.quickStats.overallCpuUsage',
                'runtime.maxCpuUsage',
                'summary.config.template',
                'summary.quickStats.guestMemoryUsage'
            ])

        if self.collect_only['vmguests'] is True:
            properties.extend([
                'guest.disk',
                'guest.toolsStatus',
                'guest.toolsVersion',
                'guest.toolsVersionStatus2',
            ])

        if self.collect_only['snapshots'] is True:
            properties.append('snapshot')

        """
        papa smurf, are we collecting custom attributes?
        """
        if self.fetch_custom_attributes:
            properties.append('summary.customValue')

        """
            triggeredAlarmState must be fetched to get vm alarms list
        """
        if self.fetch_alarms:
            properties.append('triggeredAlarmState')

        virtual_machines = yield self.batch_fetch_properties(
            vim.VirtualMachine,
            properties,
        )

        """
        once custom attributes are fetched,
        store'em linked to their moid
        if no customValue found for an object
        it get an empty dict
        """
        if self.fetch_custom_attributes:
            self._vmsCustomAttributes = dict(
                [
                    (vm_moId, vm.get('summary.customValue', {}))
                    for vm_moId, vm in virtual_machines.items()
                ]
            )

        fetch_time = datetime.datetime.utcnow() - start
        logging.info("Fetched vim.VirtualMachine inventory ({fetch_time})".format(fetch_time=fetch_time))

        return virtual_machines

    @defer.inlineCallbacks
    def customAttributesLabelNames(self, metric_type):
        """
            vm perf, vms, vmguestes and snapshots metrics share the same custom attributes
            as they re related to virtual machine objects

            host perf and hosts metrics share the same custom attributes
            as they re related to host system objects
        """

        labelNames = []

        if metric_type in ('datastores',):
            labelNames = yield self.datastoresCustomAttributesLabelNames

        if metric_type in ('vms', 'vm_perf', 'snapshots', 'vmguests'):
            labelNames = yield self.vmsCustomAttributesLabelNames

        if metric_type in ('hosts', 'host_perf'):
            labelNames = yield self.hostsCustomAttributesLabelNames
        if metric_type in ('cluster',):
            labelNames = yield self.datastoresCustomAttributesLabelNames
        return labelNames

    @run_once_property
    @defer.inlineCallbacks
    def datastoresCustomAttributesLabelNames(self):
        """
        normalizes custom attributes to all objects of the same type
        it means
        all objects of type datastore will share the same set of custom attributes
        but these custom attributes can be filled or not, depending on
        what has been gathered (of course)
        """
        customAttributesLabelNames = []

        if self.fetch_custom_attributes:
            customAttributes = yield self._datastoresCustomAttributes
            customAttributesLabelNames = list(
                set(
                    chain(
                        *[
                            attributes.keys()
                            for attributes in customAttributes.values()
                        ]
                    )
                )
            )

        return customAttributesLabelNames

    @run_once_property
    @defer.inlineCallbacks
    def hostsCustomAttributesLabelNames(self):
        """
        normalizes custom attributes to all objects of the same type
        it means
        all objects of type host system will share the same set of custom attributes
        but these custom attributes can be filled or not, depending on
        what has been gathered (of course)
        """
        customAttributesLabelNames = []

        if self.fetch_custom_attributes:
            customAttributes = yield self._hostsCustomAttributes
            customAttributesLabelNames = list(
                set(
                    chain(
                        *[
                            attributes.keys()
                            for attributes in customAttributes.values()
                        ]
                    )
                )
            )

        return customAttributesLabelNames

    @run_once_property
    @defer.inlineCallbacks
    def vmsCustomAttributesLabelNames(self):
        """
        normalizes custom attributes to all objects of the same type
        it means
        all objects of type virtual machine will share the same set of custom attributes
        but these custom attributes can be filled or not, depending on
        what has been gathered (of course)
        """
        customAttributesLabelNames = []

        if self.fetch_custom_attributes:
            customAttributes = yield self._vmsCustomAttributes
            customAttributesLabelNames = list(
                set(
                    chain(
                        *[
                            attributes.keys()
                            for attributes in customAttributes.values()
                        ]
                    )
                )
            )

        return customAttributesLabelNames

    @run_once_property
    @defer.inlineCallbacks
    def datastoresCustomAttributes(self):
        """
        creates a list of the custom attributes values,
        in order their labels re gonna be inserted
        when no value was found for that custom attribute
        'n/a' is inserted
        """
        customAttributes = {}

        if self.fetch_custom_attributes:
            customAttributes = yield self._datastoresCustomAttributes
            datastoresCustomAttributesLabelNames = yield self.datastoresCustomAttributesLabelNames
            for labelName in datastoresCustomAttributesLabelNames:
                for ds in customAttributes.keys():
                    if labelName not in customAttributes[ds].keys():
                        customAttributes[ds][labelName] = 'n/a'

        return customAttributes

    @run_once_property
    @defer.inlineCallbacks
    def hostsCustomAttributes(self):
        """
        creates a list of the custom attributes values,
        in order their labels re gonna be inserted
        when no value was found for that custom attribute
        'n/a' is inserted
        """
        customAttributes = {}

        if self.fetch_custom_attributes:
            customAttributes = yield self._hostsCustomAttributes
            hostsCustomAttributesLabelNames = yield self.hostsCustomAttributesLabelNames
            for labelName in hostsCustomAttributesLabelNames:
                for host in customAttributes.keys():
                    if labelName not in customAttributes[host].keys():
                        customAttributes[host][labelName] = 'n/a'

        return customAttributes

    @run_once_property
    @defer.inlineCallbacks
    def vmsCustomAttributes(self):
        """
        creates a list of the custom attributes values,
        in order their labels re gonna be inserted
        when no value was found for that custom attribute
        'n/a' is inserted
        """
        customAttributes = {}

        if self.fetch_custom_attributes:
            customAttributes = yield self._vmsCustomAttributes
            vmsCustomAttributesLabelNames = yield self.customAttributesLabelNames('vms')
            for labelName in vmsCustomAttributesLabelNames:
                for vm in customAttributes.keys():
                    if labelName not in customAttributes[vm].keys():
                        customAttributes[vm][labelName] = 'n/a'

        return customAttributes

    @run_once_property
    @defer.inlineCallbacks
    def datacenter_inventory(self):
        content = yield self.content
        # FIXME: It's unclear if this is operating on data already fetched in
        # content or if this is doing stealth HTTP requests
        # Right now we assume it does stealth lookups
        datacenters = yield threads.deferToThread(lambda: content.rootFolder.childEntity)
        return datacenters

    @run_once_property
    @defer.inlineCallbacks
    def datastore_labels(self):

        def _collect(node, level=1, dc=None, storagePod=""):
            inventory = {}
            if isinstance(node, vim.Folder) and not isinstance(node, vim.StoragePod):
                logging.debug("[Folder    ] {level} {name}".format(name=node.name, level=('-' * level).ljust(7)))
                for child in node.childEntity:
                    inventory.update(_collect(child, level + 1, dc))
            elif isinstance(node, vim.Datacenter):
                logging.debug("[Datacenter] {level} {name}".format(name=node.name, level=('-' * level).ljust(7)))
                inventory.update(_collect(node.datastoreFolder, level + 1, node.name))
            elif isinstance(node, vim.Folder) and isinstance(node, vim.StoragePod):
                logging.debug("[StoragePod] {level} {name}".format(name=node.name, level=('-' * level).ljust(7)))
                for child in node.childEntity:
                    inventory.update(_collect(child, level + 1, dc, node.name))
            elif isinstance(node, vim.Datastore):
                logging.debug("[Datastore ] {level} {name}".format(name=node.name, level=('-' * level).ljust(7)))
                inventory[node.name] = [node.name, dc, storagePod]
            else:
                logging.debug("[?         ] {level} {node}".format(node=node, level=('-' * level).ljust(7)))
            return inventory

        labels = {}
        dcs = yield self.datacenter_inventory
        for dc in dcs:
            result = yield threads.deferToThread(lambda: _collect(dc))
            labels.update(result)

        return labels

    @run_once_property
    @defer.inlineCallbacks
    def host_labels(self):

        def _collect(node, level=1, dc=None, folder=None):
            inventory = {}
            if isinstance(node, vim.Folder) and not isinstance(node, vim.StoragePod):
                logging.debug("[Folder    ] {level} {name}".format(level=('-' * level).ljust(7), name=node.name))
                for child in node.childEntity:
                    inventory.update(_collect(child, level + 1, dc))
            elif isinstance(node, vim.Datacenter):
                logging.debug("[Datacenter] {level} {name}".format(level=('-' * level).ljust(7), name=node.name))
                inventory.update(_collect(node.hostFolder, level + 1, node.name))
            elif isinstance(node, vim.ComputeResource):
                logging.debug("[ComputeRes] {level} {name}".format(level=('-' * level).ljust(7), name=node.name))
                for host in node.host:
                    inventory.update(_collect(host, level + 1, dc, node))
            elif isinstance(node, vim.HostSystem):
                logging.debug("[HostSystem] {level} {name}".format(level=('-' * level).ljust(7), name=node.name))
                inventory[node._moId] = [
                    node.summary.config.name.rstrip('.'),
                    dc,
                    folder.name if isinstance(folder, vim.ClusterComputeResource) else ''
                ]
            else:
                logging.debug("[?         ] {level} {node}".format(level=('-' * level).ljust(7), node=node))
            return inventory

        labels = {}
        dcs = yield self.datacenter_inventory
        for dc in dcs:
            result = yield threads.deferToThread(lambda: _collect(dc))
            labels.update(result)
        return labels

    @run_once_property
    @defer.inlineCallbacks
    def vm_tags(self):
        """
        return a dict that links vms moid to its tags
        """
        tags = {}
        if self.fetch_tags:
            tags = yield self.tags
            tags = tags['vms']
        return tags

    @run_once_property
    @defer.inlineCallbacks
    def host_tags(self):
        """
        return a dict that links hosts moid to its tags
        """
        tags = {}
        if self.fetch_tags:
            tags = yield self.tags
            tags = tags['hosts']
        return tags

    @run_once_property
    @defer.inlineCallbacks
    def datastore_tags(self):
        """
        return a dict that links datastore moid to its tags
        """
        tags = {}
        if self.fetch_tags:
            tags = yield self.tags
            tags = tags['datastores']
        return tags

    @run_once_property
    @defer.inlineCallbacks
    def vm_labels(self):

        virtual_machines, host_labels = yield parallelize(self.vm_inventory, self.host_labels)

        labels = {}
        for moid, row in virtual_machines.items():

            host_moid = None
            if 'runtime.host' in row:
                host_moid = row['runtime.host']._moId

            labels[moid] = [row['name']]

            if 'summary.config.vmPathName' in row:
                p = row['summary.config.vmPathName']
                if p[0] == '[':
                    p = p[1:p.find("]")]
            else:
                p = 'n/a'

            labels[moid] = labels[moid] + [p]

            if host_moid in host_labels:
                labels[moid] = labels[moid] + host_labels[host_moid]

            """
            this code was in vm_inventory before
            but I have the feeling it is best placed here where
            vms label values are handled
            """
            labels_cnt = len(labels[moid])
            if self.fetch_tags:
                labels_cnt += 1

            if labels_cnt < len(self._labelNames['vms']):
                logging.info(
                    "Only ${cnt}/{expected} labels (vm, host, dc, cluster) found, filling n/a"
                    .format(
                        cnt=labels_cnt,
                        expected=len(self._labelNames['vms'])
                    )
                )

            for i in range(labels_cnt, len(self._labelNames['vms'])):
                labels[moid].append('n/a')

        return labels

    @run_once_property
    @defer.inlineCallbacks
    def counter_ids(self):
        """
        create a mapping from performance stats to their counterIDs
        counter_info: [performance stat => counterId]
        performance stat example: cpu.usagemhz.LATEST
        """
        content = yield self.content
        counter_info = {}
        for counter in content.perfManager.perfCounter:
            prefix = counter.groupInfo.key
            counter_full = "{}.{}.{}".format(prefix, counter.nameInfo.key, counter.rollupType)
            counter_info[counter_full] = counter.key
        return counter_info

    @defer.inlineCallbacks
    def _vmware_disconnect(self):
        """
        Disconnect from Vcenter
        """
        connection = yield self.connection
        yield threads.deferToThread(
            connect.Disconnect,
            connection,
        )
        del self.connection

    def _vmware_full_snapshots_list(self, snapshots):
        """
        Get snapshots from a VM list, recursively
        """
        snapshot_data = []
        for snapshot in snapshots:
            snap_timestamp = self._to_epoch(snapshot.createTime)
            today= datetime.datetime.today().timestamp()
            lifetime = today - snap_timestamp
            snap_info = {'name': snapshot.name, 'timestamp_seconds': lifetime}
            snapshot_data.append(snap_info)
            snapshot_data = snapshot_data + self._vmware_full_snapshots_list(
                snapshot.childSnapshotList)
        return snapshot_data

    @defer.inlineCallbacks
    def updateMetricsLabelNames(self, metrics, metric_types):
        """
        by the time metrics are created, we have no clue what are gonna be the custom attributes
        or even if they re gonna be fetched.
        so after custom attributes are finally retrieved from the datacenter,
        their labels need to be inserted inside the already defined metric labels.
        to be possible, we previously had to store metric names and map'em by object type, vms,
        hosts and datastores, and so its metrics, so as to gather everything here
        """
        # Insert custom attributes names as metric labels
        if self.fetch_custom_attributes:

            for metric_type in metric_types:

                customAttributesLabelNames = yield self.customAttributesLabelNames(metric_type)

                for metric_name in self._metricNames.get(metric_type, []):
                    metric = metrics.get(metric_name)
                    labelnames = metric._labelnames
                    metric._labelnames = labelnames[0:len(self._labelNames[metric_type])]
                    metric._labelnames += customAttributesLabelNames
                    metric._labelnames += labelnames[len(self._labelNames[metric_type]):]
                    metric._labelnames = list(map(lambda x: re.sub('[^a-zA-Z0-9_]', '_', x), metric._labelnames))

    @defer.inlineCallbacks
    def _vmware_get_datastores(self, ds_metrics):
        global datastore_score
        """
        Get Datastore information
        """

        if self.fetch_tags:
            """
            if we need the tags, we fetch'em here
            """
            results, datastore_labels, datastore_tags = yield parallelize(
                self.datastore_inventory,
                self.datastore_labels,
                self.datastore_tags
            )
        else:
            results, datastore_labels = yield parallelize(self.datastore_inventory, self.datastore_labels)

        """
        fetch custom attributes
        """
        customAttributes = {}
        customAttributesLabelNames = {}
        if self.fetch_custom_attributes:
            customAttributes = yield self.datastoresCustomAttributes
            customAttributesLabelNames = yield self.datastoresCustomAttributesLabelNames

        """
        updates the datastore metric label names with custom attributes names
        """
        self.updateMetricsLabelNames(ds_metrics, ['datastores'])
        datastore_warning = 0
        datastore_total = 0
        datastore_critical =0

        total_datastore = len(results.items())
        for datastore_id, datastore in results.items():
            warningevent = 0
            criticalevent = 0
            try:
                name = datastore['name']
                labels = datastore_labels[name]

                """
                insert the tags values if needed
                if tags are empty they receive a 'n/a'
                """
                if self.fetch_tags:
                    tags = datastore_tags.get(datastore_id, [])
                    tags = ','.join(tags)
                    if not tags:
                        tags = 'n/a'

                    labels += [tags]

                """
                time to insert the custom attributes values in order
                """
                customLabels = []
                for labelName in customAttributesLabelNames:
                    customLabels.append(customAttributes[datastore_id].get(labelName))

                labels += customLabels

            except KeyError as e:
                logging.info(
                    "Key error, unable to register datastore {error}, datastores are {datastore_labels}".format(
                        error=e, datastore_labels=datastore_labels
                    )
                )
                continue

            """
                filter red and yellow alarms
            """
            if self.fetch_alarms:
                alarms = datastore.get('triggeredAlarmState').split(',')
                alarms = [a for a in alarms if ':' in a]

                # Red alarms
                red_alarms = [':'.join(a.split(':')[:-1]) for a in alarms if a.split(':')[-1] == 'red']
                red_alarms_label = ','.join(red_alarms) if red_alarms else 'n/a'
                ds_metrics['vmware_datastore_red_alarms'].add_metric(
                    labels + [red_alarms_label],
                    len(red_alarms)
                )
                # Yellow alarms
                yellow_alarms = [':'.join(a.split(':')[:-1]) for a in alarms if a.split(':')[-1] == 'yellow']
                yellow_alarms_label = ','.join(yellow_alarms) if yellow_alarms else 'n/a'
                ds_metrics['vmware_datastore_yellow_alarms'].add_metric(
                    labels + [yellow_alarms_label],
                    len(yellow_alarms)
                )
                warningevent = len(yellow_alarms)
                criticalevent = len(red_alarms)
            ds_capacity = float(datastore.get('summary.capacity', 0))
            ds_freespace = float(datastore.get('summary.freeSpace', 0))
            ds_uncommitted = float(datastore.get('summary.uncommitted', 0))
            ds_provisioned = ds_capacity - ds_freespace + ds_uncommitted
            ds_usedper = (ds_capacity - ds_freespace) / ds_capacity
            ds_metrics['vmware_datastore_capacity_size'].add_metric(labels, ds_capacity)
            ds_metrics['vmware_datastore_freespace_size'].add_metric(labels, ds_freespace)
            ds_metrics['vmware_datastore_uncommited_size'].add_metric(labels, ds_uncommitted)
            ds_metrics['vmware_datastore_provisoned_size'].add_metric(labels, ds_provisioned)
            ds_metrics['vmware_datastore_usedpercent'].add_metric(labels, ds_usedper)
            
            if (ds_usedper > 0.8 and ds_usedper<0.95) or warningevent >0:
                datastore_warning +=1
            elif ds_usedper > 0.95 or criticalevent >0:
                datastore_critical += 1

            ds_metrics['vmware_datastore_hosts'].add_metric(labels, len(datastore.get('host', [])))
            ds_metrics['vmware_datastore_vms'].add_metric(labels, len(datastore.get('vm', [])))

            ds_metrics['vmware_datastore_maintenance_mode'].add_metric(
                labels + [datastore.get('summary.maintenanceMode', 'unknown')],
                1
            )

            ds_metrics['vmware_datastore_type'].add_metric(
                labels + [datastore.get('summary.type', 'normal')],
                1
            )

        warning_per = datastore_warning/total_datastore
        critical_per = datastore_critical/total_datastore
        if(warning_per <0.3 or critical_per<0.1):
            datastore_score =100
        elif(warning_per ==0.3 or(critical_per > 0.1 and critical_per<0.2)):
            datastore_score =70
        elif((warning_per >0.3 and warning_per<0.4) or(critical_per > 0.2 and critical_per<0.3)):
            datastore_score =60
        elif((warning_per >0.4 and warning_per<0.5) or(critical_per > 0.3 and critical_per<0.4)):
            datastore_score =50
        elif((warning_per > 0.5 and warning_per < 0.6) ):
            datastore_score = 40
        elif((warning_per >0.6 and warning_per<0.7) or(critical_per > 0.4 and critical_per<0.5)):
            datastore_score =30
        elif(warning_per >0.7 or critical_per>0.5):
            datastore_score =0
        labels[0]="All"
        ds_metrics['vmware_datastore_perf_score'].add_metric(labels, datastore_score)
        return results

    @defer.inlineCallbacks
    def _vmware_get_vm_perf_manager_metrics(self, vm_metrics):
        logging.info('START: _vmware_get_vm_perf_manager_metrics')

        virtual_machines, counter_info = yield parallelize(self.vm_inventory, self.counter_ids)

        # List of performance counter we want
        perf_list = [
            'cpu.ready.summation',
            'cpu.maxlimited.summation',
            'cpu.usage.average',
            'cpu.usagemhz.average',
            'cpu.idle.summation',
            'mem.active.average',
            'mem.swapped.average',
            'mem.vmmemctl.average',
            'disk.maxTotalLatency.latest',
            'disk.usage.average',
            'disk.read.average',
            'disk.write.average',
            'net.received.average',
            'net.transmitted.average',
            'net.multicastRx.summation',
            'net.multicastTx.summation',
            'net.broadcastTx.summation',
            'net.broadcastRx.summation',
            'net.droppedRx.summation',
            'net.droppedTx.summation',
        ]

        # Prepare gauges
        for p in perf_list:
            p_metric = 'vmware_vm_' + p.replace('.', '_')
            vm_metrics[p_metric] = GaugeMetricFamily(
                p_metric,
                p_metric,
                labels=self._labelNames['vm_perf'])
            """
            store perf metric name for later ;)
            """
            self._metricNames['vm_perf'].append(p_metric)

        metrics = []
        metric_names = {}
        for perf_metric in perf_list:
            perf_metric_name = 'vmware_vm_' + perf_metric.replace('.', '_')
            counter_key = counter_info[perf_metric]
            metrics.append(vim.PerformanceManager.MetricId(
                counterId=counter_key,
                instance=''
            ))
            metric_names[counter_key] = perf_metric_name

        """
        updates vm perf metrics label names with vms custom attributes names
        """
        self.updateMetricsLabelNames(vm_metrics, ['vm_perf'])

        specs = []
        for vm in virtual_machines.values():
            if vm.get('runtime.powerState') != 'poweredOn':
                continue
            specs.append(vim.PerformanceManager.QuerySpec(
                maxSample=1,
                entity=vm['obj'],
                metricId=metrics,
                intervalId=20
            ))
            if vm.get('summary.quickStats.guestMemoryUsage'):
                self.vm_score_list.append({"vmname": vm['name'], "memused": vm['summary.quickStats.guestMemoryUsage']})
        content = yield self.content
        if len(specs) > 0:
            chunks = [specs[x:x + self.specs_size] for x in range(0, len(specs), self.specs_size)]
            for list_specs in chunks:
                results, labels = yield parallelize(
                    threads.deferToThread(content.perfManager.QueryStats, querySpec=list_specs),
                    self.vm_labels,
                )

                for ent in results:
                    for metric in ent.value:
                        if(metric_names[metric.id.counterId] == "vmware_vm_cpu_usagemhz_average"):
                            try:
                                updatenode = next(item for item in self.vm_score_list if item["vmname"] == labels[ent.entity._moId])
                                updatenode['cpuused'] = float(sum(metric.value))
                            except:
                                self.vm_score_list.append({"vmname": labels[ent.entity._moId], "cpuused": float(sum(metric.value))})
                        
                        if(metric_names[metric.id.counterId] == "vmware_vm_disk_maxTotalLatency_latest"):
                            try:
                                updatenode = next(item for item in self.vm_score_list if item["vmname"] == labels[ent.entity._moId])
                                updatenode['disk'] = float(sum(metric.value))
                            except:
                                self.vm_score_list.append({"vmname": labels[ent.entity._moId], "disk": float(sum(metric.value))})
                        if(metric_names[metric.id.counterId] == "vmware_vm_cpu_ready_summation"):
                            try:
                                updatenode = next(item for item in self.vm_score_list if item["vmname"] == labels[ent.entity._moId])
                                updatenode['cpuready'] = float(sum(metric.value))
                            except:
                                self.vm_score_list.append({"vmname": labels[ent.entity._moId], "cpuready": float(sum(metric.value))})
                        vm_metrics[metric_names[metric.id.counterId]].add_metric(
                            labels[ent.entity._moId],
                            float(sum(metric.value)),
                        )
        for item in self.vm_score_list:
            hostname = item['vmname'][2]
            try:
                updatenode = next(item for item in self.host_vm_overload if item["hostname"] == hostname)
                updatenode['totalvm'] += 1
            except:
                self.host_vm_overload.append({"hostname": hostname, "totalvm": 1})
            if("memused" in item.keys() and "cpuused" in item.keys() and item['cputotal'] > 0 and item['memtotal'] > 0):
                logging.info('Score')
                cpuused_score = 0
                memused_score = 0
                cpuready_score = 0
                disk_score = 0
                snapshot_score = 0
                cpuusedper = item['cpuused']/item['cputotal']
                memusedper = item['memused']/item['memtotal']
                # cpuuse
                if(cpuusedper < 0.85):
                    cpuusedscore = 100
                elif(cpuusedper < 0.9):
                    cpuusedscore = 50
                elif(cpuusedper < 0.95):
                    cpuusedscore = 25
                else:
                    cpuusedscore = 0
                # cpu ready
                if(item['cpuready'] < 50):
                    cpuready_score = 100
                elif(item['cpuready'] < 500):
                    cpuready_score = 50
                elif(item['cpuready'] < 1000):
                    cpuready_score = 25
                else:
                    cpuready_score = 0
                    try:
                        updatenode = next(item for item in self.host_vm_overload if item["hostname"] == hostname)
                        updatenode['cpureadyover'] += 1
                    except:
                        self.host_vm_overload.append({"hostname": hostname, "cpureadyover": 1})
                    
                # ram used
                if(memusedper < 0.85):
                    memused_score = 100
                elif(memusedper < 0.90):
                    memused_score = 50
                elif(memusedper < 0.95):
                    memused_score = 25
                else:
                    memused_score = 0
                # disk latency
                if(item['disk'] < 10):
                    disk_score = 100
                elif(item['disk'] < 20):
                    disk_score = 50
                elif(item['disk'] < 40):
                    disk_score = 25
                else:
                    disk_score = 0
                    try:
                        updatenode = next(item for item in self.host_vm_overload if item["hostname"] == hostname)
                        updatenode['diskover'] += 1
                    except:
                        self.host_vm_overload.append({"hostname": hostname, "diskover": 1})
                if("snapshot" in item.keys()):
                    if item['snapshot'] < (72 * 60 * 60):
                        snapshot_score = 100
                    elif item['snapshot'] < (14 * 24 * 60 * 60):
                        snapshot_score = 50
                    elif item['snapshot'] < (30 * 24 * 60 * 60):
                        snapshot_score = 25
                    else:
                        snapshot_score = 0
                else:
                    snapshot_score = 100
                vm_totalscore = cpuused_score * 0.15 + cpuused_score * 0.15 + memused_score * 0.3 + snapshot_score * 0.1 + disk_score*0.3
                vm_metrics["vmware_vm_perf_score"].add_metric(
                    item["vmname"],
                    float(vm_totalscore),
                )
        logging.info('FIN: _vmware_get_vm_perf_manager_metrics')

    @defer.inlineCallbacks
    def _vmware_get_host_perf_manager_metrics(self, host_metrics):
        global host_final_score
        logging.info('START: _vmware_get_host_perf_manager_metrics')

        host_systems, counter_info = yield parallelize(self.host_system_inventory, self.counter_ids)

        # List of performance counter we want
        perf_list = [
            'cpu.idle.summation',
            'cpu.ready.summation',
            'cpu.swapwait.summation',
            'cpu.usage.average',
            'cpu.usagemhz.average',
            'cpu.used.summation',
            'disk.read.average',
            'disk.write.average',
            'mem.active.average',
            'mem.latency.average',
            'mem.vmmemctl.average',
            'net.bytesRx.average',
            'net.bytesTx.average',
            'net.droppedRx.summation',
            'net.droppedTx.summation',
            'net.errorsRx.summation',
            'net.errorsTx.summation',
            'net.usage.average',
        ]

        # Prepare gauges
        for p in perf_list:
            p_metric = 'vmware_host_' + p.replace('.', '_')
            host_metrics[p_metric] = GaugeMetricFamily(
                p_metric,
                p_metric,
                labels=self._labelNames['host_perf'])
            self._metricNames['host_perf'].append(p_metric)

        metrics = []
        metric_names = {}
        for perf_metric in perf_list:
            perf_metric_name = 'vmware_host_' + perf_metric.replace('.', '_')
            counter_key = counter_info[perf_metric]
            metrics.append(vim.PerformanceManager.MetricId(
                counterId=counter_key,
                instance=''
            ))
            metric_names[counter_key] = perf_metric_name

        # Insert custom attributes names as metric labels
        self.updateMetricsLabelNames(host_metrics, ['host_perf'])

        specs = []
        for host in host_systems.values():
            if host.get('runtime.powerState') != 'poweredOn':
                continue
            specs.append(vim.PerformanceManager.QuerySpec(
                maxSample=1,
                entity=host['obj'],
                metricId=metrics,
                intervalId=20
            ))

        content = yield self.content

        if len(specs) > 0:
            results, labels = yield parallelize(
                threads.deferToThread(content.perfManager.QueryStats, querySpec=specs),
                self.host_labels,
            )
            for ent in results:
                for metric in ent.value:
                    if(metric_names[metric.id.counterId] == "vmware_host_cpu_usagemhz_average"):
                        try:
                            updatenode = next(item for item in self.host_score_list if item["hostname"] == labels[ent.entity._moId])
                            updatenode['cpuused'] = float(sum(metric.value))
                        except:
                            self.host_score_list.append({"hostname": labels[ent.entity._moId], "cpuused": float(sum(metric.value))})
                    if(metric_names[metric.id.counterId] == "vmware_host_net_errorsRx_summation"):
                        try:
                            updatenode = next(item for item in self.host_score_list if item["hostname"] == labels[ent.entity._moId])
                            updatenode['netrxerror'] = float(sum(metric.value))
                        except:
                            self.host_score_list.append({"hostname": labels[ent.entity._moId], "netrxerror": float(sum(metric.value))})
                    if(metric_names[metric.id.counterId] == "vmware_host_net_errorsTx_summation"):
                        try:
                            updatenode = next(item for item in self.host_score_list if item["hostname"] == labels[ent.entity._moId])
                            updatenode['nettxerror'] = float(sum(metric.value))
                        except:
                            self.host_score_list.append({"hostname": labels[ent.entity._moId], "nettxerror": float(sum(metric.value))})
                    host_metrics[metric_names[metric.id.counterId]].add_metric(
                        labels[ent.entity._moId],
                        float(sum(metric.value)),
                    )
        # host values table for warning
        # if redvalue >1 hostvalue = 0        
        scoretable = [100,85,75,60,45,30,15]
        for item in self.host_score_list:
            criticalvalue = 0
            warnnigvalue = 0
            vmcpu_readyper =0
            vmdisk_latencyper = 0
            hostname = item['hostname'][0]
            specific_host = next(problem for problem in self.host_vm_overload if problem["hostname"] == hostname)
            if "cpureadyover" in specific_host:
                vmcpu_readyper = specific_host['cpureadyover'] / specific_host['totalvm']
            if "diskover" in specific_host:
                vmcpu_readyper = specific_host['diskover'] / specific_host['totalvm']
            cpuusedper = item['cpuused']/item['cputotal']
            memusedpef = item['memused']/item['memtotal']
            # CPU USED
            if cpuusedper <0.95 and cpuusedper >0.8:
                warnnigvalue +=1
            elif cpuusedper >0.95:
                criticalvalue +=1
            # Memory USED
            if memusedpef < 0.95 and memusedpef > 0.75:
                warnnigvalue += 1
            elif memusedpef > 0.95:
                criticalvalue += 1
            # event
            if "warningevent" in item:
                warnnigvalue += 1
            elif "criticalevent" in item:
                criticalvalue += 1
            # network
            if (item['nettxerror'] > 0.01 and item['nettxerror'] < 0.03) or (item['netrxerror'] > 0.01 and item['netrxerror'] < 0.03):
                warnnigvalue += 1
            elif (item['nettxerror'] > 0.03) or (item['netrxerror'] > 0.03):
                criticalvalue += 1
            # vm disk_latency statistics
            if vmdisk_latencyper < 0.1 and vmdisk_latencyper > 0.25:
                warnnigvalue += 1
            elif vmdisk_latencyper > 0.1:
                criticalvalue += 1
            # vm cpu_ready statistics
            if vmcpu_readyper < 0.1 and vmcpu_readyper > 0.025:
                warnnigvalue += 1
            elif vmcpu_readyper > 0.1:
                criticalvalue += 1
            if criticalvalue >0:
                host_metrics['vmware_host_perf_score'].add_metric(
                    item['hostname'],
                    0,
                )
                host_final_score.append({"hostname":item['hostname'],"score":0})
            else:
                host_metrics['vmware_host_perf_score'].add_metric(
                    item['hostname'],
                    scoretable[warnnigvalue],
                )
                host_final_score.append({"hostname": item['hostname'], "score": scoretable[warnnigvalue]})
        logging.info('FIN: _vmware_get_host_perf_manager_metrics')

    @defer.inlineCallbacks
    def _vmware_get_vms(self, metrics):
        """
        Get VM information
        """
        logging.info("Starting vm metrics collection")

        if self.fetch_tags:
            virtual_machines, vm_labels, vm_tags = yield parallelize(
                self.vm_inventory,
                self.vm_labels,
                self.vm_tags
            )
        else:
            virtual_machines, vm_labels = yield parallelize(self.vm_inventory, self.vm_labels)

        # fetch Custom Attributes Labels ("values")
        customAttributes = {}
        customAttributesLabelNames = {}
        if self.fetch_custom_attributes:
            customAttributes = yield self.vmsCustomAttributes
            customAttributesLabelNames = yield self.customAttributesLabelNames('vms')

        # Insert custom attributes names as metric labels
        self.updateMetricsLabelNames(metrics, ['vms', 'vmguests', 'snapshots'])

        for moid, row in virtual_machines.items():
            # Ignore vm if field "runtime.host" does not exist
            # It will happen during a VM is cloning
            if 'runtime.host' not in row:
                continue

            labels = vm_labels[moid]

            customLabels = []
            for labelName in customAttributesLabelNames:
                customLabels.append(customAttributes[moid].get(labelName))

            if self.fetch_tags:
                tags = vm_tags.get(moid, [])
                tags = ','.join(tags)
                if not tags:
                    tags = 'n/a'

                vm_labels[moid] += [tags] + customLabels

            else:
                vm_labels[moid] += customLabels

            """
                filter red and yellow alarms
            """
            if self.fetch_alarms and ('triggeredAlarmState' in row):
                alarms = row.get('triggeredAlarmState').split(',')
                alarms = [a for a in alarms if ':' in a]

                # Red alarms
                red_alarms = [':'.join(a.split(':')[:-1]) for a in alarms if a.split(':')[-1] == 'red']
                red_alarms_label = ','.join(red_alarms) if red_alarms else 'n/a'
                metrics['vmware_vm_red_alarms'].add_metric(
                    labels + [red_alarms_label],
                    len(red_alarms)
                )

                # Yellow alarms
                yellow_alarms = [':'.join(a.split(':')[:-1]) for a in alarms if a.split(':')[-1] == 'yellow']
                yellow_alarms_label = ','.join(yellow_alarms) if yellow_alarms else 'n/a'
                metrics['vmware_vm_yellow_alarms'].add_metric(
                    labels + [yellow_alarms_label],
                    len(yellow_alarms)
                )

            if 'runtime.powerState' in row:
                power_state = 1 if row['runtime.powerState'] == 'poweredOn' else 0
                metrics['vmware_vm_power_state'].add_metric(labels, power_state)
            
                if power_state and row.get('runtime.bootTime'):
                    today= datetime.datetime.today().timestamp()
                    uptime_second = (today - self._to_epoch(row['runtime.bootTime']))
                    metrics['vmware_vm_boot_timestamp_seconds'].add_metric(
                        labels,
                        uptime_second
                    )
            
            if 'summary.config.numCpu' in row:
                metrics['vmware_vm_num_cpu'].add_metric(labels, row['summary.config.numCpu'])
                
            if 'summary.config.memorySizeMB' in row:
                metrics['vmware_vm_memory_max'].add_metric(labels, row['summary.config.memorySizeMB'])
                try:
                    updatenode = next(item for item in self.vm_score_list if item["vmname"] == labels)
                    updatenode['memtotal'] = row['summary.config.memorySizeMB']
                except:
                    self.vm_score_list.append({"vmname": labels, "memtotal": row['summary.config.memorySizeMB']})
            if 'summary.quickStats.guestMemoryUsage' in row:
                metrics['vmware_vm_memory_usage'].add_metric(labels, row['summary.quickStats.guestMemoryUsage'])
                try:
                    memused = row['summary.quickStats.guestMemoryUsage']
                    memmax = row['summary.config.memorySizeMB']
                    memusedperc = round((memused/memmax),2)
                    metrics['vmware_vm_memory_usedpercent'].add_metric(labels, memusedperc)
                except:
                    metrics['vmware_vm_memory_usedpercent'].add_metric(labels, 0)
                try:
                    updatenode = next(item for item in self.vm_score_list if item["vmname"] == labels)
                    updatenode['memused'] = row['summary.quickStats.guestMemoryUsage']
                except:
                    self.vm_score_list.append({"vmname": labels, "memused": row['summary.quickStats.guestMemoryUsage']})
            if 'runtime.maxCpuUsage' in row:
                metrics['vmware_vm_max_cpu_usage'].add_metric(labels, row['runtime.maxCpuUsage'])
                try:
                    updatenode = next(item for item in self.vm_score_list if item["vmname"] == labels)
                    updatenode['cputotal'] = row['runtime.maxCpuUsage']
                    
                except:
                    self.vm_score_list.append({"vmname": labels, "cputotal": row['runtime.maxCpuUsage']})
                try:
                    cpuused = row['summary.quickStats.overallCpuUsage']
                    cpumax = row['runtime.maxCpuUsage']
                    cpuusedperc = round((cpuused / cpumax), 2)
                    metrics['vmware_vm_cpu_usedpercent'].add_metric(labels, cpuusedperc)
                except:
                    metrics['vmware_vm_cpu_usedpercent'].add_metric(labels, 0)
            if 'guest.disk' in row and len(row['guest.disk']) > 0:
                for disk in row['guest.disk']:
                    metrics['vmware_vm_guest_disk_free'].add_metric(
                        labels + [disk.diskPath], disk.freeSpace
                    )
                    metrics['vmware_vm_guest_disk_capacity'].add_metric(
                        labels + [disk.diskPath], disk.capacity
                    )
                    diskused = disk.capacity - disk.freeSpace
                    diskusedperc = round((diskused/disk.capacity),2)
                    metrics['vmware_vm_guest_disk_usage'].add_metric(
                        labels + [disk.diskPath], diskused
                    )
                    metrics['vmware_vm_guest_disk_usedpercent'].add_metric(
                        labels + [disk.diskPath], diskusedperc
                    )

            if 'guest.toolsStatus' in row:
                metrics['vmware_vm_guest_tools_running_status'].add_metric(
                    labels + [row['guest.toolsStatus']], 1
                )

            if 'guest.toolsVersion' in row:
                metrics['vmware_vm_guest_tools_version'].add_metric(
                    labels + [row['guest.toolsVersion']], 1
                )


            if 'snapshot' in row:
                snapshots = self._vmware_full_snapshots_list(row['snapshot'].rootSnapshotList)

                metrics['vmware_vm_snapshots'].add_metric(
                    labels,
                    len(snapshots),
                )

                for snapshot in snapshots:
                    try:
                        updatenode = next(item for item in self.vm_score_list if item["vmname"] == labels)
                        updatenode['snapshot'] = snapshot['timestamp_seconds']
                    except:
                        self.vm_score_list.append({"vmname": labels, "snapshot": snapshot['timestamp_seconds']})
                    metrics['vmware_vm_snapshot_timestamp_seconds'].add_metric(
                        labels + [snapshot['name']],
                        snapshot['timestamp_seconds'],
                    )
                    
        logging.info("Finished vm metrics collection")

    @defer.inlineCallbacks
    def _vmware_get_hosts(self, host_metrics):
        """
        Get Host (ESXi) information
        """
        logging.info("Starting host metrics collection")
        total_cpuusaged = 0
        total_cpumax = 0
        total_memusaged = 0
        total_memmax = 0
        if self.fetch_tags:
            results, host_labels, host_tags = yield parallelize(
                self.host_system_inventory,
                self.host_labels,
                self.host_tags
            )

        else:
            results, host_labels = yield parallelize(self.host_system_inventory, self.host_labels)

        # fetch Custom Attributes Labels ("values")
        customAttributes = {}
        customAttributesLabelNames = {}
        if self.fetch_custom_attributes:
            customAttributes = yield self.hostsCustomAttributes
            customAttributesLabelNames = yield self.hostsCustomAttributesLabelNames

        # Insert custom attributes names as metric labels
        self.updateMetricsLabelNames(host_metrics, ['hosts'])

        for host_id, host in results.items():

            try:
                labels = host_labels[host_id]

                if self.fetch_tags:
                    tags = host_tags.get(host_id, [])
                    tags = ','.join(tags)
                    if not tags:
                        tags = 'n/a'

                    labels += [tags]

                customLabels = []
                for labelName in customAttributesLabelNames:
                    customLabels.append(customAttributes[host_id].get(labelName))

                labels += customLabels

            except KeyError as e:
                logging.info(
                    "Key error, unable to register host {error}, host labels are {host_labels}".format(
                        error=e, host_labels=host_labels
                    )
                )
                continue

            """
                filter red and yellow alarms
            """
            if self.fetch_alarms:
                alarms = [a for a in host.get('triggeredAlarmState', '').split(',') if ':' in a]

                # Red alarms
                red_alarms = [':'.join(a.split(':')[:-1]) for a in alarms if a.split(':')[-1] == 'red']
                red_alarms_label = ','.join(red_alarms) if red_alarms else 'n/a'
                host_metrics['vmware_host_red_alarms'].add_metric(
                    labels + [red_alarms_label],
                    len(red_alarms)
                )
                try:
                    updatenode = next(item for item in self.host_score_list if item["hostname"] == labels)
                    updatenode['critcal'] = len(red_alarms)
                except:
                    self.host_score_list.append({"hostname": labels, "critcalevent": len(red_alarms)})
                # Yellow alarms
                yellow_alarms = [':'.join(a.split(':')[:-1]) for a in alarms if a.split(':')[-1] == 'yellow']
                yellow_alarms_label = ','.join(yellow_alarms) if yellow_alarms else 'n/a'
                host_metrics['vmware_host_yellow_alarms'].add_metric(
                    labels + [yellow_alarms_label],
                    len(yellow_alarms)
                )
                try:
                    updatenode = next(item for item in self.host_score_list if item["hostname"] == labels)
                    updatenode['warning'] = len(yellow_alarms)
                except:
                    self.host_score_list.append({"hostname": labels, "warningevent": len(yellow_alarms)})
            # Numeric Sensor Info
            sensors = host.get('runtime.healthSystemRuntime.systemHealthInfo.numericSensorInfo', '').split(',') + \
                host.get('runtime.healthSystemRuntime.hardwareStatusInfo.cpuStatusInfo', '').split(',') + \
                host.get('runtime.healthSystemRuntime.hardwareStatusInfo.memoryStatusInfo', '').split(',')

            sensors = [s for s in sensors if ':' in s]

            for s in sensors:
                sensor = dict(item.split("=") for item in re.split(r':(?=\w+=)', s)[1:])

                if not all(key in sensor for key in ['sensorStatus', 'name', 'type', 'unit', 'value']):
                    continue

                sensor_status = {
                    'red': 0,
                    'yellow': 1,
                    'green': 2,
                    'unknown': 3,
                }[sensor['sensorStatus'].lower()]

                host_metrics['vmware_host_sensor_state'].add_metric(
                    labels + [sensor['name'], sensor['type']],
                    sensor_status
                )

                # FAN speed
                if sensor["unit"] == 'rpm':
                    host_metrics['vmware_host_sensor_fan'].add_metric(
                        labels + [sensor['name']],
                        int(sensor['value']) * (10 ** (int(sensor['unitModifier'])))
                    )

                # Temperature
                if sensor["unit"] == 'degrees c':
                    host_metrics['vmware_host_sensor_temperature'].add_metric(
                        labels + [sensor['name']],
                        int(sensor['value']) * (10 ** (int(sensor['unitModifier'])))
                    )

                # Power Voltage
                if sensor["unit"] == 'volts':
                    host_metrics['vmware_host_sensor_power_voltage'].add_metric(
                        labels + [sensor['name']],
                        int(sensor['value']) * (10 ** (int(sensor['unitModifier'])))
                    )

                # Power Current
                if sensor["unit"] == 'amps':
                    host_metrics['vmware_host_sensor_power_current'].add_metric(
                        labels + [sensor['name']],
                        int(sensor['value']) * (10 ** (int(sensor['unitModifier'])))
                    )

                # Power Watt
                if sensor["unit"] == 'watts':
                    host_metrics['vmware_host_sensor_power_watt'].add_metric(
                        labels + [sensor['name']],
                        int(sensor['value']) * (10 ** (int(sensor['unitModifier'])))
                    )

                # Redundancy
                if sensor["unit"] == 'redundancy-discrete':
                    host_metrics['vmware_host_sensor_redundancy'].add_metric(
                        labels + [sensor['name']],
                        int(sensor['value'])
                    )

            # Standby Mode
            standby_mode = 1 if host.get('runtime.standbyMode') == 'in' else 0
            standby_mode_state = host.get('runtime.standbyMode', 'unknown')
            host_metrics['vmware_host_standby_mode'].add_metric(
                labels + [standby_mode_state],
                standby_mode
            )

            # Power state
            power_state = 1 if host['runtime.powerState'] == 'poweredOn' else 0
            host_metrics['vmware_host_power_state'].add_metric(labels, power_state)

            # Host connection state (connected, disconnected, notResponding)
            connection_state = host.get('runtime.connectionState', 'unknown')
            host_metrics['vmware_host_connection_state'].add_metric(
                labels + [connection_state],
                1
            )

            # Host in maintenance mode?
            if 'runtime.inMaintenanceMode' in host:
                host_metrics['vmware_host_maintenance_mode'].add_metric(
                    labels,
                    host['runtime.inMaintenanceMode'] * 1,
                )

            if not power_state:
                continue

            if host.get('runtime.bootTime'):
                # Host uptime
                today= datetime.datetime.today().timestamp()
                uptime_second = (today - self._to_epoch(host['runtime.bootTime']))
                host_metrics['vmware_host_boot_timestamp_seconds'].add_metric(
                    labels,
                    uptime_second)
                

            # CPU Usage (in Mhz)
            if 'summary.quickStats.overallCpuUsage' in host:
                try:
                    updatenode = next(item for item in self.host_score_list if item["hostname"] == labels)
                    updatenode['cpuused'] = host['summary.quickStats.overallCpuUsage']
                except:
                    self.host_score_list.append({"hostname": labels, "cpuused": host['summary.quickStats.overallCpuUsage']})

            cpu_core_num = host.get('summary.hardware.numCpuCores')
            if cpu_core_num:
                host_metrics['vmware_host_num_cpu'].add_metric(labels, cpu_core_num)

            cpu_mhz = host.get('summary.hardware.cpuMhz')
            if cpu_core_num and cpu_mhz:
                cpu_total = cpu_core_num * cpu_mhz
                host_metrics['vmware_host_cpu_max'].add_metric(labels, cpu_total)

                try:
                    updatenode = next(item for item in self.host_score_list if item["hostname"] == labels)
                    updatenode['cputotal'] = cpu_total
                except:
                    self.host_score_list.append({"hostname": labels, "cputotal": cpu_total})
                try:
                    cpu_used = host['summary.quickStats.overallCpuUsage']
                    cpu_usedpercent = round( (cpu_used /cpu_total),2)
                    total_cpumax += cpu_total
                    total_cpuusaged += cpu_used
                    host_metrics['vmware_host_cpu_usedpercent'].add_metric(labels, cpu_usedpercent)
                except:
                    host_metrics['vmware_host_cpu_usedpercent'].add_metric(labels, 0)
            # Memory Usage (in MB)
            if 'summary.quickStats.overallMemoryUsage' in host:
                host_metrics['vmware_host_memory_usage'].add_metric(
                    labels,
                    host['summary.quickStats.overallMemoryUsage']
                )
                try:
                    updatenode = next(item for item in self.host_score_list if item["hostname"] == labels)
                    updatenode['memused'] = host['summary.quickStats.overallMemoryUsage']
                except:
                    self.host_score_list.append({"hostname": labels, "memused": host['summary.quickStats.overallMemoryUsage']})
            if 'summary.hardware.memorySize' in host:
                host_metrics['vmware_host_memory_max'].add_metric(
                    labels,
                    float(host['summary.hardware.memorySize']) / 1024 / 1024
                )
                
                try:
                    updatenode = next(item for item in self.host_score_list if item["hostname"] == labels)
                    updatenode['memtotal'] = float(host['summary.hardware.memorySize']) / 1024 / 1024
                except:
                    self.host_score_list.append({"hostname": labels, "memtotal": float(host['summary.hardware.memorySize']) / 1024 / 1024})
                try:
                    mem_used = host['summary.quickStats.overallMemoryUsage']
                    mem_max = float(host['summary.hardware.memorySize']) / 1024 / 1024
                    mem_usedpercent = round((mem_used/mem_max),2)
                    host_metrics['vmware_host_memory_usedpercentage'].add_metric(labels, mem_usedpercent)
                    total_memusaged += mem_used
                    total_memmax += float(host['summary.hardware.memorySize']) / 1024 / 1024
                except:
                    host_metrics['vmware_host_memory_usedpercentage'].add_metric(labels, 0)
            config_ver = host.get('summary.config.product.version', 'unknown')
            build_ver = host.get('summary.config.product.build', 'unknown')
            host_metrics['vmware_host_product_info'].add_metric(
                labels + [config_ver, build_ver],
                1
            )

            hardware_cpu_model = host.get('summary.hardware.cpuModel', 'unknown')
            hardware_model = host.get('summary.hardware.model', 'unknown')
            host_metrics['vmware_host_hardware_info'].add_metric(
                labels + [hardware_model, hardware_cpu_model],
                1
            )
        clusterlabel = ['all',labels[1],labels[2]]
        host_metrics['vmware_host_memory_total_max'].add_metric(labels,total_memmax)
        host_metrics['vmware_host_memory_total_usage'].add_metric(labels, total_memusaged)
        host_metrics['vmware_host_memory_total_usedpercentage'].add_metric(labels, round((total_memusaged/total_memmax),2))
        host_metrics['vmware_host_cpu_total_max'].add_metric(labels, total_cpumax)
        host_metrics['vmware_host_cpu_total_usage'].add_metric(labels, total_cpuusaged)
        host_metrics['vmware_host_cpu_total_usedpercent'].add_metric(labels, round((total_cpuusaged / total_cpumax), 2))
        logging.info("Finished host metrics perf collection")
        return results

    @defer.inlineCallbacks
    def _vmware_cluster_status(self,cluster_metics):
        global host_final_score 
        global datastore_score 
        if self.fetch_tags:
            results, host_labels, host_tags = yield parallelize(
                self.host_system_inventory,
                self.host_labels,
                self.host_tags
            )

        else:
            results, host_labels = yield parallelize(self.host_system_inventory, self.host_labels)
        
        
        hostname = list(host_labels.keys())
        cluster_labels = host_labels[hostname[-1]]
        cluster_labels[0] = ""
        if(len(host_final_score) > 0 and datastore_score>0):
            
            total_host = len(host_final_score)
            host_bad = 0
            for node in host_final_score:
                if(node["score"]<50):
                   host_bad +=1
            if((host_bad / total_host) < 0.3 or datastore_score <30):
                cluster_metics["vmware_cluster_score"].add_metric(cluster_labels, 100)
            elif((host_bad / total_host) < 0.5 or (datastore_score > 30 and datastore_score <50)):
                cluster_metics["vmware_cluster_score"].add_metric(cluster_labels, 50)
            else:
                cluster_metics["vmware_cluster_score"].add_metric(cluster_labels, 0)

        else:
            print(cluster_metics)
            cluster_metics["vmware_cluster_score"].add_metric(cluster_labels, -1)

class ListCollector(object):

    def __init__(self, metrics):
        self.metrics = list(metrics)

    def collect(self):
        return self.metrics


class VMWareMetricsResource(Resource):
    isLeaf = True

    def __init__(self, args):
        """
        Init Metric Resource
        """
        Resource.__init__(self)
        self.configure(args)

    def configure(self, args):
        if args.config_file:
            try:
                with open(args.config_file) as cf:
                    self.config = yaml.load(cf, Loader=yaml.FullLoader)

                if 'default' not in self.config.keys():
                    logging.error("Error, you must have a default section in config file (for now)")
                    exit(1)
                return
            except Exception as exception:
                raise SystemExit("Error while reading configuration file: {0}".format(exception.message))

        self.config = {
            'default': {
                'vsphere_host': os.environ.get('VSPHERE_HOST'),
                'vsphere_user': os.environ.get('VSPHERE_USER'),
                'vsphere_password': os.environ.get('VSPHERE_PASSWORD'),
                'ignore_ssl': get_bool_env('VSPHERE_IGNORE_SSL', False),
                'specs_size': os.environ.get('VSPHERE_SPECS_SIZE', 5000),
                'fetch_custom_attributes': get_bool_env('VSPHERE_FETCH_CUSTOM_ATTRIBUTES', False),
                'fetch_tags': get_bool_env('VSPHERE_FETCH_TAGS', False),
                'fetch_alarms': get_bool_env('VSPHERE_FETCH_ALARMS', True),
                'collect_only': {
                    'vms': get_bool_env('VSPHERE_COLLECT_VMS', True),
                    'vmguests': get_bool_env('VSPHERE_COLLECT_VMGUESTS', True),
                    'datastores': get_bool_env('VSPHERE_COLLECT_DATASTORES', True),
                    'hosts': get_bool_env('VSPHERE_COLLECT_HOSTS', True),
                    'snapshots': get_bool_env('VSPHERE_COLLECT_SNAPSHOTS', True),
                }
            }
        }

        for key in os.environ.keys():
            if key == 'VSPHERE_USER':
                continue
            if not key.startswith('VSPHERE_') or not key.endswith('_USER'):
                continue

            section = key.split('_', 1)[1].rsplit('_', 1)[0]

            self.config[section.lower()] = {
                'vsphere_host': os.environ.get('VSPHERE_{}_HOST'.format(section)),
                'vsphere_user': os.environ.get('VSPHERE_{}_USER'.format(section)),
                'vsphere_password': os.environ.get('VSPHERE_{}_PASSWORD'.format(section)),
                'ignore_ssl': get_bool_env('VSPHERE_{}_IGNORE_SSL'.format(section), False),
                'specs_size': os.environ.get('VSPHERE_{}_SPECS_SIZE'.format(section), 5000),
                'fetch_custom_attributes': get_bool_env('VSPHERE_{}_FETCH_CUSTOM_ATTRIBUTES'.format(section), False),
                'fetch_tags': get_bool_env('VSPHERE_{}_FETCH_TAGS'.format(section), False),
                'fetch_alarms': get_bool_env('VSPHERE_{}_FETCH_ALARMS'.format(section), False),
                'collect_only': {
                    'vms': get_bool_env('VSPHERE_{}_COLLECT_VMS'.format(section), True),
                    'vmguests': get_bool_env('VSPHERE_{}_COLLECT_VMGUESTS'.format(section), True),
                    'datastores': get_bool_env('VSPHERE_{}_COLLECT_DATASTORES'.format(section), True),
                    'hosts': get_bool_env('VSPHERE_{}_COLLECT_HOSTS'.format(section), True),
                    'snapshots': get_bool_env('VSPHERE_{}_COLLECT_SNAPSHOTS'.format(section), True),
                }
            }

    def render_GET(self, request):
        """ handles get requests for metrics, health, and everything else """
        self._async_render_GET(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def _async_render_GET(self, request):
        try:
            yield self.generate_latest_metrics(request)
        except Exception:
            logging.error(traceback.format_exc())
            request.setResponseCode(500)
            request.write(b'# Collection failed')
            request.finish()

        # We used to call request.processingFailed to send a traceback to browser
        # This can make sense in debug mode for a HTML site - but we don't want
        # prometheus trying to parse a python traceback

    @defer.inlineCallbacks
    def generate_latest_metrics(self, request):
        """ gets the latest metrics """
        section = request.args.get(b'section', [b'default'])[0].decode('utf-8')
        if section not in self.config.keys():
            logging.info("{} is not a valid section, using default".format(section))
            section = 'default'

        if self.config[section].get('vsphere_host') and self.config[section].get('vsphere_host') != "None":
            vsphere_host = self.config[section].get('vsphere_host')
        elif request.args.get(b'target', [None])[0]:
            vsphere_host = request.args.get(b'target', [None])[0].decode('utf-8')
        elif request.args.get(b'vsphere_host', [None])[0]:
            vsphere_host = request.args.get(b'vsphere_host')[0].decode('utf-8')
        else:
            request.setResponseCode(500)
            logging.info("No vsphere_host or target defined")
            request.write(b'No vsphere_host or target defined!\n')
            request.finish()
            return

        collector = VmwareCollector(
            vsphere_host,
            self.config[section]['vsphere_user'],
            self.config[section]['vsphere_password'],
            self.config[section]['collect_only'],
            self.config[section]['specs_size'],
            self.config[section]['fetch_custom_attributes'],
            self.config[section]['ignore_ssl'],
            self.config[section]['fetch_tags'],
            self.config[section]['fetch_alarms'],
        )
        metrics = yield collector.collect()

        registry = CollectorRegistry()
        registry.register(ListCollector(metrics))
        output = generate_latest(registry)

        request.setHeader("Content-Type", "text/plain; charset=UTF-8")
        request.setResponseCode(200)
        request.write(output)
        request.finish()


class HealthzResource(Resource):
    isLeaf = True

    def render_GET(self, request):
        request.setHeader("Content-Type", "text/plain; charset=UTF-8")
        request.setResponseCode(200)
        logging.info("Service is UP")
        return 'Server is UP'.encode()


class IndexResource(Resource):
    isLeaf = False

    def getChild(self, name, request):
        if name == b'':
            return self
        return Resource.getChild(self, name, request)

    def render_GET(self, request):
        output = """<html>
            <head><title>VMware Exporter</title></head>
            <body>
            <h1>VMware Exporter</h1>
            <p><a href="/metrics">Metrics</a></p>
            </body>
            </html>"""
        request.setHeader("Content-Type", "text/html; charset=UTF-8")
        request.setResponseCode(200)
        return output.encode()


def registerEndpoints(args):
    root = Resource()
    root.putChild(b'', IndexResource())
    root.putChild(b'metrics', VMWareMetricsResource(args))
    root.putChild(b'healthz', HealthzResource())
    return root


def main(argv=None):
    """ start up twisted reactor """
    parser = argparse.ArgumentParser(description='VMWare metrics exporter for Prometheus')
    parser.add_argument('-c', '--config', dest='config_file',
                        default=None, help="configuration file")
    parser.add_argument('-a', '--address', dest='address', type=str,
                        default='', help="HTTP address to expose metrics")
    parser.add_argument('-p', '--port', dest='port', type=int,
                        default=9272, help="HTTP port to expose metrics")
    parser.add_argument('-l', '--loglevel', dest='loglevel',
                        default="INFO", help="Set application loglevel INFO, DEBUG")
    parser.add_argument('-v', '--version', action="version",
                        version='vmware_exporter {version}'.format(version=__version__),
                        help='Print version and exit')

    args = parser.parse_args(argv or sys.argv[1:])

    numeric_level = getattr(logging, args.loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError("Invalid log level: {level}".format(level=args.loglevel))
    logging.basicConfig(level=numeric_level, format='%(asctime)s %(levelname)s:%(message)s')

    reactor.suggestThreadPoolSize(25)

    factory = Site(registerEndpoints(args))
    logging.info("Starting web server on port {address}:{port}".format(address=args.address, port=args.port))
    endpoint = endpoints.TCP4ServerEndpoint(reactor, args.port, interface=args.address)
    endpoint.listen(factory)
    reactor.run()


if __name__ == '__main__':
    main()