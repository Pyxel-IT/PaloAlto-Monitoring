#!/usr/bin/env python3

import time
import yaml
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Any
import requests
import urllib3
from influxdb import InfluxDBClient
from pathlib import Path
import sys

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class PaloAltoCollector:
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self._setup_logging()
        self.influx_client = self._setup_influxdb()

    def _load_config(self, config_path: str) -> Dict:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    def _setup_logging(self):
        log_config = self.config.get('logging', {})
        log_file = log_config.get('file', 'logs/collector.log')

        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=getattr(logging, log_config.get('level', 'INFO')),
            format=log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def _setup_influxdb(self) -> InfluxDBClient:
        influx_config = self.config['influxdb']
        client = InfluxDBClient(
            host=influx_config['host'],
            port=influx_config['port'],
            username=influx_config['username'],
            password=influx_config['password'],
            database=influx_config['database']
        )

        try:
            client.create_database(influx_config['database'])
            self.logger.info(f"Database '{influx_config['database']}' created or already exists")
        except Exception as e:
            self.logger.debug(f"Database creation info: {str(e)}")

        retention_policy = influx_config.get('retention_policy', '30d')
        try:
            client.create_retention_policy(
                name='autogen',
                duration=retention_policy,
                replication=1,
                database=influx_config['database'],
                default=True
            )
            self.logger.info(f"Retention policy 'autogen' created with {retention_policy} duration")
        except Exception as e:
            if "already exists" in str(e):
                self.logger.info("Retention policy already exists, continuing...")
            else:
                self.logger.error(f"Error creating retention policy: {str(e)}")
                raise

        return client

    def _get_metrics(self, device: Dict) -> Dict[str, Dict]:
        url = f"https://{device['host']}:{device.get('port', 443)}/api/"

        params = {
            'type': 'op',
            'cmd': '<show><running><resource-monitor><second><last>60</last></second></resource-monitor></running></show>',
            'key': device['api_key']
        }
        if device.get('target'):
            params['target'] = device['target']

        try:
            response = requests.get(
                url,
                params=params,
                verify=device.get('verify_ssl', False),
                timeout=self.config['collector']['timeout_seconds']
            )
            response.raise_for_status()

            root = ET.fromstring(response.text)

            metrics = {
                'cpu_load_average': {},
                'cpu_load_maximum': {},
                'tasks': {},
                'resources': {},
                'global_counters': {}
            }

            # Parse data for each dataplane
            for dp in root.findall(".//data-processors/*"):
                dp_name = dp.tag  # dp0, dp1, etc.

                # CPU Load Average
                for entry in dp.findall(".//cpu-load-average/entry"):
                    coreid_elem = entry.find('coreid')
                    value_elem = entry.find('value')

                    if coreid_elem is not None and value_elem is not None and value_elem.text:
                        cpu_id = coreid_elem.text
                        values = [int(v) for v in value_elem.text.split(',')]
                        metrics['cpu_load_average'][f"{dp_name}_cpu_{cpu_id}"] = values

                # CPU Load Maximum
                for entry in dp.findall(".//cpu-load-maximum/entry"):
                    coreid_elem = entry.find('coreid')
                    value_elem = entry.find('value')

                    if coreid_elem is not None and value_elem is not None and value_elem.text:
                        cpu_id = coreid_elem.text
                        values = [int(v) for v in value_elem.text.split(',')]
                        metrics['cpu_load_maximum'][f"{dp_name}_cpu_{cpu_id}"] = values

                # Tasks utilization
                task_elem = dp.find('.//task')
                if task_elem is not None:
                    for task in task_elem:
                        task_name = task.tag
                        if task.text and task.text.endswith('%'):
                            # Convert percentage to float (remove % and convert)
                            task_value = float(task.text.rstrip('%'))
                            metrics['tasks'][f"{dp_name}_{task_name}"] = task_value

                # Resource utilization
                for entry in dp.findall(".//resource-utilization/entry"):
                    name_elem = entry.find('name')
                    value_elem = entry.find('value')

                    if name_elem is not None and value_elem is not None and value_elem.text:
                        resource_name = name_elem.text.replace(' ', '_')
                        values = [int(v) for v in value_elem.text.split(',')]
                        metrics['resources'][f"{dp_name}_{resource_name}"] = values

            total_metrics = (len(metrics['cpu_load_average']) + len(metrics['cpu_load_maximum']) +
                           len(metrics['tasks']) + len(metrics['resources']))

            if total_metrics == 0:
                self.logger.warning(f"No metrics found in response from {device['name']}")
            else:
                self.logger.debug(f"Collected {total_metrics} metric types from {device['name']}")

            return metrics

        except Exception as e:
            self.logger.error(f"Error collecting metrics from {device['name']}: {str(e)}")
            return {'cpu_load_average': {}, 'cpu_load_maximum': {}, 'tasks': {}, 'resources': {}, 'global_counters': {}}

    def _get_global_counters(self, device: Dict) -> Dict[str, Any]:
        """Récupère les compteurs globaux des dataplanes"""
        url = f"https://{device['host']}:{device.get('port', 443)}/api/"

        params = {
            'type': 'op',
            'cmd': '<show><counter><global></global></counter></show>',
            'key': device['api_key']
        }
        if device.get('target'):
            params['target'] = device['target']

        try:
            response = requests.get(
                url,
                params=params,
                verify=device.get('verify_ssl', False),
                timeout=self.config['collector']['timeout_seconds']
            )
            response.raise_for_status()

            root = ET.fromstring(response.text)
            global_counters = {}

            # Parse les compteurs globaux
            dp_elem = root.find('.//dp')
            dp_name = dp_elem.text if dp_elem is not None else 'dp0'

            # Parse tous les compteurs
            for entry in root.findall('.//counters/entry'):
                name_elem = entry.find('name')
                value_elem = entry.find('value')
                rate_elem = entry.find('rate')
                category_elem = entry.find('category')
                aspect_elem = entry.find('aspect')
                severity_elem = entry.find('severity')
                desc_elem = entry.find('desc')

                if name_elem is not None and value_elem is not None:
                    counter_name = name_elem.text
                    counter_value = int(value_elem.text) if value_elem.text else 0
                    counter_rate = int(rate_elem.text) if rate_elem is not None and rate_elem.text else 0
                    counter_category = category_elem.text if category_elem is not None else 'unknown'
                    counter_aspect = aspect_elem.text if aspect_elem is not None else 'unknown'
                    counter_severity = severity_elem.text if severity_elem is not None else 'info'
                    counter_desc = desc_elem.text if desc_elem is not None else ''

                    global_counters[counter_name] = {
                        'value': counter_value,
                        'rate': counter_rate,
                        'category': counter_category,
                        'aspect': counter_aspect,
                        'severity': counter_severity,
                        'description': counter_desc,
                        'dataplane': dp_name
                    }

            self.logger.debug(f"Collected {len(global_counters)} global counters from {device['name']}")
            return global_counters

        except Exception as e:
            self.logger.error(f"Error collecting global counters from {device['name']}: {str(e)}")
            return {}

    def _store_metrics(self, device_name: str, metrics: Dict[str, Dict]):
        points = []
        timestamp = datetime.utcnow()

        # CPU Load Average (time series data)
        for cpu_name, values in metrics['cpu_load_average'].items():
            for i, value in enumerate(values):
                point_time = timestamp.timestamp() - (60 - i)
                points.append({
                    "measurement": "cpu_load_average",
                    "tags": {
                        "device": device_name,
                        "cpu": cpu_name
                    },
                    "time": int(point_time * 1e9),
                    "fields": {
                        "usage_percent": float(value)
                    }
                })

        # CPU Load Maximum (time series data)
        for cpu_name, values in metrics['cpu_load_maximum'].items():
            for i, value in enumerate(values):
                point_time = timestamp.timestamp() - (60 - i)
                points.append({
                    "measurement": "cpu_load_maximum",
                    "tags": {
                        "device": device_name,
                        "cpu": cpu_name
                    },
                    "time": int(point_time * 1e9),
                    "fields": {
                        "usage_percent": float(value)
                    }
                })

        # Tasks utilization (current values)
        for task_name, value in metrics['tasks'].items():
            points.append({
                "measurement": "task_utilization",
                "tags": {
                    "device": device_name,
                    "task": task_name
                },
                "time": int(timestamp.timestamp() * 1e9),
                "fields": {
                    "usage_percent": float(value)
                }
            })

        # Resource utilization (time series data)
        for resource_name, values in metrics['resources'].items():
            for i, value in enumerate(values):
                point_time = timestamp.timestamp() - (60 - i)
                points.append({
                    "measurement": "resource_utilization",
                    "tags": {
                        "device": device_name,
                        "resource": resource_name
                    },
                    "time": int(point_time * 1e9),
                    "fields": {
                        "usage_percent": float(value)
                    }
                })

        # Global counters (current values)
        for counter_name, counter_data in metrics['global_counters'].items():
            points.append({
                "measurement": "global_counters",
                "tags": {
                    "device": device_name,
                    "counter": counter_name,
                    "category": counter_data['category'],
                    "aspect": counter_data['aspect'],
                    "severity": counter_data['severity'],
                    "dataplane": counter_data['dataplane']
                },
                "time": int(timestamp.timestamp() * 1e9),
                "fields": {
                    "value": counter_data['value'],
                    "rate": counter_data['rate'],
                    "description": counter_data['description']
                }
            })

        if points:
            try:
                self.influx_client.write_points(points)
                self.logger.info(f"Stored {len(points)} metrics for device {device_name}")
            except Exception as e:
                self.logger.error(f"Error storing metrics: {str(e)}")

    def collect_once(self):
        for device in self.config['paloalto']['devices']:
            self.logger.info(f"Collecting metrics from {device['name']}")
            metrics = self._get_metrics(device)

            # Collect global counters
            global_counters = self._get_global_counters(device)
            metrics['global_counters'] = global_counters

            total_metrics = (len(metrics['cpu_load_average']) + len(metrics['cpu_load_maximum']) +
                           len(metrics['tasks']) + len(metrics['resources']) + len(metrics['global_counters']))

            if total_metrics > 0:
                self._store_metrics(device['name'], metrics)
            else:
                self.logger.warning(f"No metrics collected from {device['name']}")

    def run(self):
        interval = self.config['collector']['interval_seconds']
        self.logger.info(f"Starting collector with {interval}s interval")

        while True:
            try:
                start_time = time.time()
                self.collect_once()

                elapsed = time.time() - start_time
                sleep_time = max(0, interval - elapsed)

                if sleep_time > 0:
                    time.sleep(sleep_time)

            except KeyboardInterrupt:
                self.logger.info("Collector stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error in main loop: {str(e)}")
                time.sleep(interval)


def main():
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = "config/config.yaml"

    collector = PaloAltoCollector(config_path)
    collector.run()


if __name__ == "__main__":
    main()