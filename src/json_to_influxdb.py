#!/usr/bin/env python3

import json
import fcntl
import yaml
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List
from influxdb import InfluxDBClient
from pathlib import Path


class JsonToInfluxDB:
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self._setup_logging()
        self.json_file = self.config.get('output', {}).get('json_file', 'data/metrics.jsonl')
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

    def _build_points(self, record: Dict) -> List[Dict]:
        points = []
        device_name = record['device']
        timestamp = datetime.fromisoformat(record['timestamp'])
        metrics = record['metrics']

        # CPU Load Average (time series data)
        for cpu_name, values in metrics.get('cpu_load_average', {}).items():
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
        for cpu_name, values in metrics.get('cpu_load_maximum', {}).items():
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
        for task_name, value in metrics.get('tasks', {}).items():
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
        for resource_name, values in metrics.get('resources', {}).items():
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
        for counter_name, counter_data in metrics.get('global_counters', {}).items():
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

        return points

    def _read_and_clear(self) -> List[Dict]:
        """Read all records from the JSONL file and clear it atomically."""
        json_path = Path(self.json_file)

        if not json_path.exists() or json_path.stat().st_size == 0:
            return []

        records = []

        with open(self.json_file, 'r+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"Skipping malformed JSON at line {line_num}: {e}")

                # Truncate after successful read
                f.seek(0)
                f.truncate()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

        return records

    def ingest_once(self) -> int:
        """Read JSONL file, ingest into InfluxDB, clear file. Returns number of records processed."""
        records = self._read_and_clear()

        if not records:
            self.logger.info("No records to ingest")
            return 0

        total_points = 0

        for record in records:
            try:
                points = self._build_points(record)
                if points:
                    self.influx_client.write_points(points)
                    total_points += len(points)
                    self.logger.info(f"Ingested {len(points)} points for device {record['device']}")
            except Exception as e:
                self.logger.error(f"Error ingesting record for {record.get('device', 'unknown')}: {str(e)}")

        self.logger.info(f"Ingestion complete: {len(records)} records, {total_points} points total")
        return len(records)

    def run(self, interval: int = 10):
        """Run in continuous mode, checking for new data at the given interval (seconds)."""
        self.logger.info(f"Starting InfluxDB ingester with {interval}s interval")
        self.logger.info(f"Watching file: {self.json_file}")

        while True:
            try:
                self.ingest_once()
                time.sleep(interval)
            except KeyboardInterrupt:
                self.logger.info("Ingester stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error in main loop: {str(e)}")
                time.sleep(interval)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Ingest PaloAlto metrics from JSONL into InfluxDB')
    parser.add_argument('--config', default='config/config.yaml', help='Path to config file')
    parser.add_argument('--once', action='store_true', help='Run once then exit (default: continuous loop)')
    parser.add_argument('--interval', type=int, default=10, help='Check interval in seconds for continuous mode (default: 10)')

    args = parser.parse_args()

    ingester = JsonToInfluxDB(args.config)

    if args.once:
        ingester.ingest_once()
    else:
        ingester.run(interval=args.interval)


if __name__ == "__main__":
    main()
