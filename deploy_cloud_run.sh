#!/bin/bash
set -euo pipefail

# Load secrets from .env file
if [ -f .env ]; then
  source .env
else
  echo "Error: .env file not found. Create one with JWT_SECRET, MEMCACHED_URL, GCP_PROJECT_ID, GCP_LOCATION, and CORE_API_BASE_URL."
  exit 1
fi

# Verify required variables
for var in JWT_SECRET MEMCACHED_URL GCP_PROJECT_ID GCP_LOCATION CORE_API_BASE_URL; do
  if [ -z "${!var:-}" ]; then
    echo "Error: $var is not set in .env"
    exit 1
  fi
done

gcloud run deploy sheetgo-agent-prototype \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "JWT_SECRET=${JWT_SECRET},MEMCACHED_URL=${MEMCACHED_URL},GCP_PROJECT_ID=${GCP_PROJECT_ID},GCP_LOCATION=${GCP_LOCATION},CORE_API_BASE_URL=${CORE_API_BASE_URL}" \
  --memory 1024Mi --min-instances 1 --no-cpu-throttling --cpu 2 --vpc-connector serveless-connector-2 --vpc-egress all-traffic --service-account testing-sheetgo-agent@sheetgo-dev.iam.gserviceaccount.com

capiscio validate https://sheetgo-agent-prototype-547238816572.us-central1.run.app/.well-known/agent.json --test-live