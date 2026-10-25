#!/usr/bin/env bash
# Deploy StudyPilot to Cloud Run (API + frontend in one service).
#
#   PROJECT_ID=my-project BUCKET=my-bucket ./deploy/gcp.sh setup    # once: APIs, bucket, service account, secrets
#   PROJECT_ID=my-project ./deploy/gcp.sh deploy                    # every release
#
# Before `setup`, have ready: a Neon connection string and a Gemini API key (Google AI Studio).
set -euo pipefail

PROJECT_ID=${PROJECT_ID:?set PROJECT_ID}
REGION=${REGION:-us-central1}   # us-central1/us-east1/us-west1 keep Cloud Storage inside its free tier
SERVICE=${SERVICE:-study-copilot}
SA="$SERVICE@$PROJECT_ID.iam.gserviceaccount.com"
gcloud config set project "$PROJECT_ID" >/dev/null

secret() {  # secret NAME  (reads the value from stdin)
  if gcloud secrets describe "$1" >/dev/null 2>&1; then
    gcloud secrets versions add "$1" --data-file=-
  else
    gcloud secrets create "$1" --replication-policy=automatic --data-file=-
  fi
  gcloud secrets add-iam-policy-binding "$1" --member="serviceAccount:$SA" \
    --role=roles/secretmanager.secretAccessor >/dev/null
}

setup() {
  BUCKET=${BUCKET:?set BUCKET}
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com storage.googleapis.com

  gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
    gcloud iam service-accounts create "$SERVICE" --display-name="StudyPilot runtime"

  gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 || \
    gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access \
      --public-access-prevention
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" \
    --role=roles/storage.objectAdmin >/dev/null

  read -rsp "Neon connection string (postgresql://...): " db; echo
  printf %s "$db" | secret database-url
  read -rsp "Gemini API key: " key; echo
  printf %s "$key" | secret google-api-key
  python3 -c "import secrets; print(secrets.token_urlsafe(48), end='')" | secret secret-key

  # HMAC key so the app can use Cloud Storage through the S3 API
  hmac=$(gcloud storage hmac create "$SA" --format="value(metadata.accessId,secret)")
  printf %s "$(cut -f1 <<<"$hmac")" | secret s3-access-key-id
  printf %s "$(cut -f2 <<<"$hmac")" | secret s3-secret-access-key
  echo "Setup done. Copy deploy/env.example.yaml to deploy/env.yaml, set S3_BUCKET=$BUCKET, then run: $0 deploy"
}

deploy() {
  [[ -f deploy/env.yaml ]] || { echo "Missing deploy/env.yaml (copy deploy/env.example.yaml)"; exit 1; }
  # --no-cpu-throttling: background ingestion keeps running after the upload request returns.
  # --max-instances 1: in-process jobs are resumed on startup, which is only safe with one instance.
  gcloud run deploy "$SERVICE" --source . --region "$REGION" --service-account "$SA" \
    --allow-unauthenticated --no-cpu-throttling --min-instances 0 --max-instances 1 \
    --cpu 1 --memory 2Gi --timeout 900 --concurrency 40 \
    --env-vars-file deploy/env.yaml \
    --set-secrets DATABASE_URL=database-url:latest,SECRET_KEY=secret-key:latest,GOOGLE_API_KEY=google-api-key:latest,S3_ACCESS_KEY_ID=s3-access-key-id:latest,S3_SECRET_ACCESS_KEY=s3-secret-access-key:latest
  gcloud run services describe "$SERVICE" --region "$REGION" --format="value(status.url)"
}

"${1:-deploy}"
