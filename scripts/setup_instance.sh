#!/bin/bash
set -e

# ------------------------------------------------------------------
# Setup a new PaloAlto-Monitoring instance
# Generates passwords and creates all configuration files
# ------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

generate_password() {
    tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24
}

echo "========================================="
echo "  PaloAlto Monitoring - Instance Setup"
echo "========================================="
echo

# --- Instance name ---
read -rp "Instance name: " INSTANCE_NAME
if [ -z "$INSTANCE_NAME" ]; then
    echo "Error: instance name is required."
    exit 1
fi

# Docker Compose project name must be lowercase
PROJECT_NAME="paloalto-$(echo "$INSTANCE_NAME" | tr '[:upper:]' '[:lower:]')"

# --- Ports ---
read -rp "InfluxDB port [8086]: " INFLUXDB_PORT
INFLUXDB_PORT="${INFLUXDB_PORT:-8086}"

read -rp "Grafana port [3000]: " GRAFANA_PORT
GRAFANA_PORT="${GRAFANA_PORT:-3000}"

# --- Generate passwords ---
INFLUXDB_ADMIN_PASSWORD="$(generate_password)"
INFLUXDB_USER_PASSWORD="$(generate_password)"
GRAFANA_ADMIN_PASSWORD="$(generate_password)"

echo
echo "Generating configuration for instance: $INSTANCE_NAME"
echo "  InfluxDB port: $INFLUXDB_PORT"
echo "  Grafana port:  $GRAFANA_PORT"
echo

# --- Create directories ---
CONFIG_DIR="$PROJECT_DIR/config-${INSTANCE_NAME}"
LOGS_DIR="$PROJECT_DIR/logs-${INSTANCE_NAME}"
DATA_DIR="$PROJECT_DIR/data"

mkdir -p "$CONFIG_DIR" "$LOGS_DIR" "$DATA_DIR"

# --- Generate .env file ---
ENV_FILE="$PROJECT_DIR/docker/.env.${INSTANCE_NAME}"
cat > "$ENV_FILE" << EOF
# Instance: ${INSTANCE_NAME}
# Generated on $(date -Iseconds)
COMPOSE_PROJECT_NAME=${PROJECT_NAME}

INFLUXDB_PORT=${INFLUXDB_PORT}
GRAFANA_PORT=${GRAFANA_PORT}

INFLUXDB_DB=paloalto_monitoring
INFLUXDB_ADMIN_USER=admin
INFLUXDB_ADMIN_PASSWORD=${INFLUXDB_ADMIN_PASSWORD}
INFLUXDB_USER=collector
INFLUXDB_USER_PASSWORD=${INFLUXDB_USER_PASSWORD}

GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}

CONFIG_PATH=../config-${INSTANCE_NAME}
LOGS_PATH=../logs-${INSTANCE_NAME}
DASHBOARDS_PATH=../dashboards

GRAFANA_DATASOURCE=./grafana-datasource-${INSTANCE_NAME}.yaml
EOF

echo "[OK] Created $ENV_FILE"

# --- Generate Grafana datasource ---
DATASOURCE_FILE="$PROJECT_DIR/docker/grafana-datasource-${INSTANCE_NAME}.yaml"
cat > "$DATASOURCE_FILE" << EOF
apiVersion: 1

datasources:
  - name: InfluxDB
    type: influxdb
    access: proxy
    url: http://influxdb:8086
    database: paloalto_monitoring
    user: collector
    secureJsonData:
      password: ${INFLUXDB_USER_PASSWORD}
    isDefault: true
    editable: true
EOF

echo "[OK] Created $DATASOURCE_FILE"

# --- Generate config.yaml (for Docker collector) ---
cat > "$CONFIG_DIR/config.yaml" << EOF
# Configuration for instance: ${INSTANCE_NAME}
# Generated on $(date -Iseconds)

paloalto:
  devices:
    # Add your devices here
    # Direct access:
    #   - name: "fw-01"
    #     host: "10.0.1.10"
    #     port: 443
    #     api_key: "YOUR_API_KEY"
    #     verify_ssl: false
    #
    # Via Panorama:
    #   - name: "fw-01"
    #     host: "panorama.example.com"
    #     port: 443
    #     api_key: "PANORAMA_API_KEY"
    #     target: "SERIAL_NUMBER"
    #     verify_ssl: false

influxdb:
  host: "influxdb"
  port: 8086
  database: "paloalto_monitoring"
  username: "admin"
  password: "${INFLUXDB_ADMIN_PASSWORD}"
  retention_policy: "30d"

collector:
  interval_seconds: 60
  timeout_seconds: 30
  retry_count: 3
  retry_delay_seconds: 5

output:
  json_file: "data/metrics.jsonl"

logging:
  level: "INFO"
  file: "logs/collector.log"
  max_size_mb: 100
  backup_count: 10
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
EOF

echo "[OK] Created $CONFIG_DIR/config.yaml"

# --- Generate standalone config (for json_to_influxdb.py outside Docker) ---
cat > "$CONFIG_DIR/standalone.yaml" << EOF
# Standalone configuration for instance: ${INSTANCE_NAME}
# Use this with scripts running OUTSIDE Docker (json_to_influxdb.py, collector_to_json.py)
# Generated on $(date -Iseconds)

paloalto:
  devices: []

influxdb:
  host: "localhost"
  port: ${INFLUXDB_PORT}
  database: "paloalto_monitoring"
  username: "admin"
  password: "${INFLUXDB_ADMIN_PASSWORD}"
  retention_policy: "30d"

collector:
  interval_seconds: 60
  timeout_seconds: 30
  retry_count: 3
  retry_delay_seconds: 5

output:
  json_file: "data/metrics.jsonl"

logging:
  level: "INFO"
  file: "logs-${INSTANCE_NAME}/collector.log"
  max_size_mb: 100
  backup_count: 10
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
EOF

echo "[OK] Created $CONFIG_DIR/standalone.yaml"

# --- Summary ---
echo
echo "========================================="
echo "  Instance '$INSTANCE_NAME' ready!"
echo "========================================="
echo
echo "  Credentials:"
echo "    InfluxDB admin:     admin / ${INFLUXDB_ADMIN_PASSWORD}"
echo "    InfluxDB collector: collector / ${INFLUXDB_USER_PASSWORD}"
echo "    Grafana admin:      admin / ${GRAFANA_ADMIN_PASSWORD}"
echo
echo "  Start the stack:"
echo "    cd docker && docker compose --env-file .env.${INSTANCE_NAME} up -d"
echo
echo "  Standalone ingestion:"
echo "    python src/json_to_influxdb.py --config config-${INSTANCE_NAME}/standalone.yaml --once"
echo
echo "  Access:"
echo "    Grafana:  http://localhost:${GRAFANA_PORT}"
echo "    InfluxDB: http://localhost:${INFLUXDB_PORT}"
echo
echo "  IMPORTANT: Edit config-${INSTANCE_NAME}/config.yaml to add your firewall devices."
echo
