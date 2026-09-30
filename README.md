# Palo Alto Complete Monitoring

Complete monitoring solution for Palo Alto devices via API with multi-metrics collection, InfluxDB storage and Grafana visualization.

## Architecture

```
paloalto-monitoring/
├── src/                         # Python source code
│   ├── collector.py             # Integrated collector (API → InfluxDB)
│   ├── collector_to_json.py     # Decoupled collector (API → JSON Lines)
│   └── json_to_influxdb.py      # Decoupled ingester (JSON Lines → InfluxDB)
├── config/                      # Configuration
│   └── config.yaml.example      # Configuration example
├── config-client/               # Client-specific configuration (generated)
├── docker/                      # Docker configuration
│   ├── docker-compose.yml       # Monitoring stack (parameterized)
│   ├── .env                     # Default instance variables
│   └── .env.client              # Client instance variables
├── dashboards/                  # Grafana dashboards
│   ├── cpu-monitoring.json      # Basic CPU dashboard
│   └── paloalto-complete-monitoring.json # Complete dashboard
├── scripts/                     # Utility scripts
│   └── generate_api_key.py      # API key generation
├── data/                        # JSON Lines data (generated)
├── logs/                        # Logs (generated)
└── logs-client/                 # Client logs (generated)
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

### Decoupled mode
- **Collector → JSON**: Standalone script that fetches data and stores it in a JSON Lines file
- **JSON → InfluxDB**: Standalone script that reads the JSON Lines file and ingests into InfluxDB
- Intermediate JSON Lines format (`.jsonl`) for easy integration with external systems
- File locking for safe concurrent read/write

### Infrastructure
- InfluxDB storage with configurable retention policy (30d default)
- Complete Docker stack with healthchecks
- **Multi-instance support**: Run multiple isolated stacks in parallel (e.g. per-client)
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

### Starting with Docker (integrated mode)

```bash
cd docker
docker compose up -d
```

Accessible services:
- **Grafana**: http://localhost:3000
- **InfluxDB**: http://localhost:8086

Dashboards are automatically provisioned in the "Palo Alto Monitoring" folder.

### Decoupled mode (JSON Lines)

Use this mode when you need to separate data collection from InfluxDB ingestion (e.g. collecting on one machine, ingesting on another).

**1. Start the collector** (writes to `data/metrics.jsonl`):
```bash
pip install -r requirements.txt
python src/collector_to_json.py
```

**2. Start the ingester** (reads from `data/metrics.jsonl`, writes to InfluxDB):
```bash
# One-shot: ingest pending data and exit
python src/json_to_influxdb.py --once

# Continuous: check for new data every 10 seconds
python src/json_to_influxdb.py

# Custom interval
python src/json_to_influxdb.py --interval 30
```

Both scripts can run simultaneously. The ingester locks the file during read+truncate to prevent data corruption.

The JSON Lines file path is configurable in `config.yaml`:
```yaml
output:
  json_file: "data/metrics.jsonl"
```

### Multi-instance deployment

Run multiple isolated stacks in parallel (e.g. one per client) using environment files.

**Default instance** (uses `docker/.env`):
```bash
cd docker
docker compose up -d
```

**Client instance** (uses `docker/.env.client`):
```bash
cd docker
docker compose --env-file .env.client up -d
```

Each instance has its own:
- Ports (default: 8086/3000, client: 8087/3001)
- Docker volumes (isolated by `COMPOSE_PROJECT_NAME`)
- Configuration directory (`config/` vs `config-client/`)
- Log directory (`logs/` vs `logs-client/`)

**Manage instances independently:**
```bash
# Status
docker compose --env-file .env ps              # default
docker compose --env-file .env.client ps        # client

# Logs
docker compose --env-file .env.client logs -f

# Stop
docker compose --env-file .env.client down
```

**Create a new instance:**
1. Copy `docker/.env.client` to `docker/.env.newclient`
2. Adjust `COMPOSE_PROJECT_NAME`, ports, and passwords
3. Create a `config-newclient/config.yaml` with the target device(s)
4. Set `CONFIG_PATH=../config-newclient` and `LOGS_PATH=../logs-newclient` in the `.env` file
5. Launch: `docker compose --env-file .env.newclient up -d`

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

- API keys and credentials should not be committed (see `.gitignore`)
- Per-instance secrets are stored in `.env` files (gitignored) and `config-*/` directories (gitignored)
- Change all `CHANGE_ME_*` placeholders before deploying client instances
- Configure SSL/TLS for external connections

## Maintenance

### Logs
Logs are stored in `logs/collector.log` with automatic rotation.

### InfluxDB Backup
```bash
# Default instance
docker compose --env-file .env exec influxdb influxd backup /backup

# Client instance
docker compose --env-file .env.client exec influxdb influxd backup /backup
```

### Dashboard updates
Dashboards are automatically provisioned. To modify them:
1. Edit JSON files in `dashboards/`
2. Restart Grafana: `docker compose restart grafana`

### Complete rebuild
```bash
# Specify the env file for the target instance
docker compose --env-file .env down -v
docker compose --env-file .env build --no-cache
docker compose --env-file .env up -d
```

## Troubleshooting

### Common issues

- **API connection error**: Check API key and network connectivity
- **Missing data**: Check collector logs with `docker compose logs collector`
- **Empty dashboards**: Wait 1-2 minutes after first startup
- **Grafana permissions**: Docker volumes automatically manage permissions

### Service monitoring

```bash
# Container status (specify instance)
docker compose --env-file .env ps
docker compose --env-file .env.client ps

# Real-time logs
docker compose --env-file .env logs -f

# Specific service logs
docker compose --env-file .env logs collector
docker compose --env-file .env logs grafana
docker compose --env-file .env logs influxdb

# InfluxDB healthcheck
curl http://localhost:8086/ping   # default instance
curl http://localhost:8087/ping   # client instance
```

### Advanced configuration

- **Performance**: Adjust `interval_seconds` in config.yaml
- **Retention**: Modify `retention_policy` for more/less storage
- **Debug**: Change `level: "DEBUG"` in config.yaml for more details
- **Multi-devices**: Add entries in the `devices` section