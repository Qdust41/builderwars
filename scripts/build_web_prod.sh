#!/usr/bin/env bash
# Build apps/web for prod, reading the Cognito and AppSync ids from the deployed stacks.
# Needs AWS credentials that can describe the Builderwars-prod-* stacks (the GitHub deploy
# role can). The Web stack then uploads apps/web/dist on `cdk deploy`.
#
#   AWS_REGION=us-east-1 scripts/build_web_prod.sh
set -euo pipefail

region="${AWS_REGION:-us-east-1}"

output() {
  local value
  value=$(aws cloudformation describe-stacks --region "$region" --stack-name "Builderwars-prod-$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue | [0]" --output text)
  if [ -z "$value" ] || [ "$value" = "None" ]; then
    echo "error: output $2 missing from stack Builderwars-prod-$1 (deploy the backend first)" >&2
    exit 1
  fi
  printf '%s' "$value"
}

# The API is reached same-origin through CloudFront's /api/* behavior (stacks/web.py).
export VITE_API_BASE_URL=/api
export VITE_AUTH_MODE=cognito
export VITE_REALTIME_PROVIDER=appsync
VITE_COGNITO_USER_POOL_ID=$(output Identity UserPoolId)
VITE_COGNITO_CLIENT_ID=$(output Identity UserPoolClientId)
VITE_APPSYNC_EVENTS_HTTP_DNS=$(output Realtime EventsHttpDns)
VITE_APPSYNC_EVENTS_REALTIME_DNS=$(output Realtime EventsRealtimeDns)
export VITE_COGNITO_USER_POOL_ID VITE_COGNITO_CLIENT_ID
export VITE_APPSYNC_EVENTS_HTTP_DNS VITE_APPSYNC_EVENTS_REALTIME_DNS

cd "$(dirname "$0")/../apps/web"
npm ci
npm run build
echo "Built $(pwd)/dist"
