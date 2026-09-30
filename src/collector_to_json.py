#!/usr/bin/env python3

import json
import time
import yaml
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, Any
import requests
import urllib3
from pathlib import Path
import sys

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class PaloAltoJsonCollector:
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self._setup_logging()
        self.json_file = self.config.get('output', {}).get('json_file', 'data/metrics.jsonl')
        Path(self.json_file).parent.mkdir(parents=True, exist_ok=True)

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

    def _get_metrics(self, device: Dict) -> Dict[str, Dict]:
        url = f"https://{device['host']}:{device.get('port', 443)}/api/"

        params = {
            'type': 'op',
            'cmd': '<show><running><resource-monitor><second><last>60</last></second></resource-monitor></running></show>',
            'key': device['api_key']
        }

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
                'resources': {}
            }

            for dp in root.findall(".//data-processors/*"):
                dp_name = dp.tag

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
            return {'cpu_load_average': {}, 'cpu_load_maximum': {}, 'tasks': {}, 'resources': {}}

    def _get_global_counters(self, device: Dict) -> Dict[str, Any]:
        url = f"https://{device['host']}:{device.get('port', 443)}/api/"

        params = {
            'type': 'op',
            'cmd': '<show><counter><global></global></counter></show>',
            'key': device['api_key']
        }

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

            dp_elem = root.find('.//dp')
            dp_name = dp_elem.text if dp_elem is not None else 'dp0'

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
                    global_counters[counter_name] = {
                        'value': int(value_elem.text) if value_elem.text else 0,
                        'rate': int(rate_elem.text) if rate_elem is not None and rate_elem.text else 0,
                        'category': category_elem.text if category_elem is not None else 'unknown',
                        'aspect': aspect_elem.text if aspect_elem is not None else 'unknown',
                        'severity': severity_elem.text if severity_elem is not None else 'info',
                        'description': desc_elem.text if desc_elem is not None else '',
                        'dataplane': dp_name
                    }

            self.logger.debug(f"Collected {len(global_counters)} global counters from {device['name']}")
            return global_counters

        except Exception as e:
            self.logger.error(f"Error collecting global counters from {device['name']}: {str(e)}")
            return {}

    def _append_to_json(self, device_name: str, metrics: Dict):
        record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'device': device_name,
            'metrics': metrics
        }

        line = json.dumps(record, ensure_ascii=False) + '\n'

        with open(self.json_file, 'a') as f:
            f.write(line)
            f.flush()

        self.logger.info(f"Appended metrics for {device_name} to {self.json_file}")

    def collect_once(self):
        for device in self.config['paloalto']['devices']:
            self.logger.info(f"Collecting metrics from {device['name']}")
            metrics = self._get_metrics(device)

            global_counters = self._get_global_counters(device)
            metrics['global_counters'] = global_counters

            total_metrics = (len(metrics['cpu_load_average']) + len(metrics['cpu_load_maximum']) +
                           len(metrics['tasks']) + len(metrics['resources']) + len(metrics['global_counters']))

            if total_metrics > 0:
                self._append_to_json(device['name'], metrics)
            else:
                self.logger.warning(f"No metrics collected from {device['name']}")

    def run(self):
        interval = self.config['collector']['interval_seconds']
        self.logger.info(f"Starting JSON collector with {interval}s interval")
        self.logger.info(f"Output file: {self.json_file}")

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

    collector = PaloAltoJsonCollector(config_path)
    collector.run()


if __name__ == "__main__":
    main()
