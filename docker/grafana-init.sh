#!/bin/bash

# Script d'initialisation Grafana
echo "Initialisation des dashboards Palo Alto..."

GRAFANA_USER="${GRAFANA_ADMIN_USER:-admin}"
GRAFANA_PASS="${GRAFANA_ADMIN_PASSWORD:-changeme}"

# Attendre que Grafana soit prêt
until curl -s http://grafana:3000/api/health > /dev/null; do
    echo "En attente de Grafana..."
    sleep 2
done

echo "Grafana est prêt !"

# Créer le dossier pour les dashboards si nécessaire
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Palo Alto Monitoring"
  }' \
  "http://${GRAFANA_USER}:${GRAFANA_PASS}@grafana:3000/api/folders"

echo "Dossier Palo Alto Monitoring créé ou existe déjà."
echo "Les dashboards seront automatiquement chargés depuis /etc/grafana/provisioning/dashboards/"
