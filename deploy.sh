#!/bin/bash

# deploy.sh — Deploy Day Three to Cloud Run (asia-south1, idempotent)
# Usage:
#   ./deploy.sh          Deploy if auth is active; otherwise print setup instructions
#   ./deploy.sh --dry-run  Print all commands that would run without executing

set -e

GCLOUD="/opt/homebrew/share/google-cloud-sdk/bin/gcloud"
SERVICE_NAME="day-three"
REGION="asia-south1"
DRY_RUN=false

# Parse arguments
for arg in "$@"; do
  case $arg in
    --dry-run)
      DRY_RUN=true
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

# Check gcloud auth: active account required (skip for --dry-run)
if [ "$DRY_RUN" = false ]; then
  AUTH_STATUS=$($GCLOUD auth list 2>&1)
  if echo "$AUTH_STATUS" | grep -q "No credentialed accounts"; then
    echo "gcloud auth login && gcloud auth application-default login" >&2
    exit 2
  fi
fi

# Source .env.local; extract vars needed for deploy
if [ ! -f .env.local ]; then
  echo "Error: .env.local not found" >&2
  exit 1
fi

# Read env vars from .env.local (GEMINI_API_KEY, GEMINI_MODEL, GCP_PROJECT)
# Never echo GEMINI_API_KEY; read it once and use it in commands
GEMINI_API_KEY=""
GEMINI_MODEL=""
GCP_PROJECT=""
while IFS='=' read -r key value; do
  # Skip comments and empty lines
  [[ $key == \#* ]] && continue
  [[ -z $key ]] && continue
  value="${value%\"}"
  value="${value#\"}"
  case "$key" in
    GEMINI_API_KEY) GEMINI_API_KEY="$value" ;;
    GEMINI_MODEL) GEMINI_MODEL="$value" ;;
    GCP_PROJECT) GCP_PROJECT="$value" ;;
  esac
done < .env.local

# Set defaults from gcloud config if not in .env.local
if [ -z "$GCP_PROJECT" ]; then
  GCP_PROJECT=$($GCLOUD config get project 2>/dev/null || echo "")
fi

if [ -z "$GEMINI_MODEL" ]; then
  GEMINI_MODEL="gemini-3.5-flash"
fi

if [ -z "$GCP_PROJECT" ]; then
  echo "Error: GCP_PROJECT not set in .env.local or gcloud config" >&2
  exit 1
fi

# Helper to run or print commands (mask the API key in dry-run output)
run_cmd() {
  local cmd="$@"
  local masked_cmd="$cmd"

  if [ -n "$GEMINI_API_KEY" ]; then
    masked_cmd="${cmd//GEMINI_API_KEY=$GEMINI_API_KEY/GEMINI_API_KEY=***MASKED***}"
  fi

  if [ "$DRY_RUN" = true ]; then
    echo "$masked_cmd"
  else
    "$@"
  fi
}

echo "Deploying $SERVICE_NAME to Cloud Run ($REGION)"

# Set project
run_cmd $GCLOUD config set project "$GCP_PROJECT"

# Enable required APIs
echo "Enabling APIs..."
run_cmd $GCLOUD services enable run.googleapis.com
run_cmd $GCLOUD services enable cloudbuild.googleapis.com
run_cmd $GCLOUD services enable artifactregistry.googleapis.com
run_cmd $GCLOUD services enable firestore.googleapis.com
run_cmd $GCLOUD services enable aiplatform.googleapis.com

# Create Firestore database if it doesn't exist (skip if --dry-run)
if [ "$DRY_RUN" = false ]; then
  FS_DB=$($GCLOUD firestore databases list --format="value(name)" 2>/dev/null | head -1 || echo "")
  if [ -z "$FS_DB" ]; then
    echo "Creating Firestore database..."
    $GCLOUD firestore databases create --location=$REGION
  fi
fi

# Deploy to Cloud Run
echo "Deploying to Cloud Run..."
run_cmd $GCLOUD run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 2 \
  --memory 512Mi \
  --set-env-vars "STORE=firestore,GEMINI_MODEL=$GEMINI_MODEL,GEMINI_API_KEY=$GEMINI_API_KEY,GCP_PROJECT=$GCP_PROJECT"

# Dry-run stops here; don't curl
if [ "$DRY_RUN" = true ]; then
  echo "—— Dry-run complete; no actual deployment ——"
  exit 0
fi

# Wait a moment for the service to be fully deployed
sleep 3

# Get the service URL
echo "Fetching service URL..."
SERVICE_URL=$($GCLOUD run services describe "$SERVICE_NAME" --region "$REGION" --format="value(status.url)")

if [ -z "$SERVICE_URL" ]; then
  echo "Error: Could not fetch service URL" >&2
  exit 1
fi

echo "Service deployed: $SERVICE_URL"

# Curl /api/health and print response
echo "Checking health endpoint..."
HEALTH_RESPONSE=$(curl -s "$SERVICE_URL/api/health" || echo "{\"error\": \"failed to reach endpoint\"}")
echo "Health response:"
echo "$HEALTH_RESPONSE"

echo ""
echo "✓ Deployment complete. Live URL: $SERVICE_URL"
