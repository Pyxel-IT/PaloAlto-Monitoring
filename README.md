# Palo Alto Complete Monitoring

Complete monitoring solution for Palo Alto devices via API with multi-metrics collection, InfluxDB storage and Grafana visualization.

## Architecture

```
paloalto-monitoring/
├── src/                    # Python source code
│   └── collector.py        # Main collection script
├── config/                 # Configuration
│   └── config.yaml.example # Configuration example
├── docker/                 # Docker configuration
│   └── docker-compose.yml  # Monitoring stack
├── dashboards/             # Grafana dashboards
│   ├── cpu-monitoring.json # Basic CPU dashboard
│   └── paloalto-complete-monitoring.json # Complete dashboard
├── tests/                  # Unit tests
├── docs/                   # Documentation
├── scripts/                # Utility scripts
├── logs/                   # Logs (generated)
└── data/                   # Persistent data (generated)
    ├── influxdb/
    └── grafana/
```

## Features

### Complete metrics collection
- **CPU Load Average**: Average load per core and per dataplane (dp0, dp1, etc.)
- **CPU Load Maximum**: Peak utilization per core
- **Task Utilization**: System task usage (flow_lookup, flow_fastpath, etc.)
- **Resource Utilization**: Resource usage (session, packet buffer, etc.)
- **Global Counters**: Dataplane global counters (packets, sessions, errors, etc.)
- Automatic multi-dataplane support
- Collection every minute with 60-second history per metric

### Infrastructure
- InfluxDB storage with configurable retention policy (30d default)
- Complete Docker stack with healthchecks
- Multi-device support
- Auto-provisioned Grafana dashboards
- Error handling and automatic retry
- Rotating logs with configurable levels

## Installation

### Prerequisites

- Docker and Docker Compose
- Python 3.8+ (for local execution)
- Palo Alto API key with read permissions

### Configuration

1. Copy the example configuration file:
```bash
cp config/config.yaml.example config/config.yaml
```

2. Edit `config/config.yaml` with your parameters:
   - IP addresses and API keys of Palo Alto devices
   - InfluxDB credentials
   - Collection parameters

### Starting with Docker

```bash
cd docker
docker compose up -d
```

Accessible services:
- **Grafana**: http://localhost:3000 (admin/changeme)
- **InfluxDB**: http://localhost:8086

Dashboards are automatically provisioned in the "Palo Alto Monitoring" folder.

### Local execution (development)

```bash
pip install -r requirements.txt
python src/collector.py
```

## Palo Alto API

The collection uses two XML API endpoints:

### 1. Resource Monitor
```
GET /api/?type=op&cmd=<show><running><resource-monitor><second><last>60</last></second></resource-monitor></running></show>&key=API_KEY
```

**Response format**: XML containing for each dataplane:
- CPU Load Average/Maximum per core (60 values per second)
- Task utilization (instantaneous percentages)
- Resource utilization (60 values per second)

### 2. Global Counters
```
GET /api/?type=op&cmd=<show><counter><global></global></counter></show>&key=API_KEY
```

**Response format**: XML containing global counters:
- Packet counters (received, sent, errors)
- Session counters (allocated, freed, timeout)
- Security counters (drops, violations, logs)
- Counters by category: packet, session, flow, nat, ssl, etc.

**API key generation**:
```bash
python scripts/generate_api_key.py <FIREWALL_IP> <USERNAME>
```

## InfluxDB Data Structure

### Collected Measurements

1. **`cpu_load_average`** - CPU average load
   - **Tags**: `device`, `cpu` (format: dp0_cpu_0, dp1_cpu_2, etc.)
   - **Fields**: `usage_percent`

2. **`cpu_load_maximum`** - CPU peak load
   - **Tags**: `device`, `cpu`
   - **Fields**: `usage_percent`

3. **`task_utilization`** - System task utilization
   - **Tags**: `device`, `task` (format: dp0_flow_lookup, dp0_flow_fastpath, etc.)
   - **Fields**: `usage_percent`

4. **`resource_utilization`** - Resource utilization
   - **Tags**: `device`, `resource` (format: dp0_session, dp0_packet_buffer, etc.)
   - **Fields**: `usage_percent`

5. **`global_counters`** - Dataplane global counters
   - **Tags**: `device`, `counter`, `category`, `aspect`, `severity`, `dataplane`
   - **Fields**: `value` (total), `rate` (per second), `description`

### Retention Policy
- **Duration**: 30 days by default (configurable)
- **Granularity**: 1 second for raw data

## Grafana Dashboards

### Dashboard "Palo Alto Complete Monitoring" (recommended)

**Complete overview:**
- **CPU Load Average by Core**: Detailed time graph per core and dataplane
- **Global CPU Load Average**: Global average of all cores
- **Current CPU Usage by Core**: Real-time gauges per core
- **Task Utilization by Dataplane**: System task utilization
- **Resource Utilization by Dataplane**: Resource utilization
- **Normal Activity (Info)**: Normal packet and session counters (info severity)
- **Warning Events**: Warning events (warn severity)
- **Dropped Packets**: Packets dropped by policies (drop severity)
- **System Errors**: System and technical errors (error severity)

### Dashboard "Palo Alto CPU Monitoring" (basic)

**Simplified CPU view:**
- CPU time graph per core
- Current usage gauges
- Summary table per device

### Available variables
- **Device**: Filter by device (multi-selection support)
- **Time Range**: Configurable display period

## Security

- API keys should not be committed (see .gitignore)
- Use environment variables in production
- Configure SSL/TLS for external connections
- Change default passwords

## Maintenance

### Logs
Logs are stored in `logs/collector.log` with automatic rotation.

### InfluxDB Backup
```bash
docker exec paloalto-influxdb influxd backup /backup
```

### Dashboard updates
Dashboards are automatically provisioned. To modify them:
1. Edit JSON files in `dashboards/`
2. Restart Grafana: `docker compose restart grafana`

### Complete rebuild
```bash
docker compose down -v
docker compose build --no-cache
docker compose up -d
```

## Troubleshooting

### Common issues

- **API connection error**: Check API key and network connectivity
- **Missing data**: Check collector logs with `docker compose logs collector`
- **Empty dashboards**: Wait 1-2 minutes after first startup
- **Grafana permissions**: Docker volumes automatically manage permissions

### Service monitoring

```bash
# Container status
docker compose ps

# Real-time logs
docker compose logs -f

# Specific service logs
docker compose logs collector
docker compose logs grafana
docker compose logs influxdb

# InfluxDB healthcheck
curl http://localhost:8086/ping
```

### Advanced configuration

- **Performance**: Adjust `interval_seconds` in config.yaml
- **Retention**: Modify `retention_policy` for more/less storage
- **Debug**: Change `level: "DEBUG"` in config.yaml for more details
- **Multi-devices**: Add entries in the `devices` section