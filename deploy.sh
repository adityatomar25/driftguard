#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# deploy.sh – Build images & deploy DriftGuard to Kubernetes
# ──────────────────────────────────────────────────────────────
# Usage:
#   ./deploy.sh                  # default: local (minikube/kind/docker-desktop)
#   ./deploy.sh --context kind   # specify kubectl context
#   ./deploy.sh --registry ghcr.io/adityatomar25  # push to a remote registry
#   ./deploy.sh --teardown       # delete everything
# ──────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY=""
CONTEXT=""
TEARDOWN=false
TAG="latest"

# ── Parse args ────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --registry)  REGISTRY="$2"; shift 2 ;;
    --context)   CONTEXT="$2";  shift 2 ;;
    --tag)       TAG="$2";      shift 2 ;;
    --teardown)  TEARDOWN=true; shift   ;;
    *)           echo "Unknown flag: $1"; exit 1 ;;
  esac
done

KUBECTL="kubectl"
[[ -n "$CONTEXT" ]] && KUBECTL="kubectl --context $CONTEXT"

# ── Teardown ──────────────────────────────────────────────────
if $TEARDOWN; then
  echo "🗑️  Tearing down DriftGuard…"
  $KUBECTL delete -k "$SCRIPT_DIR/k8s/base" --ignore-not-found
  echo "✅ Done."
  exit 0
fi

# ── Image names ───────────────────────────────────────────────
API_IMAGE="driftguard-api:${TAG}"
FRONTEND_IMAGE="driftguard-frontend:${TAG}"

if [[ -n "$REGISTRY" ]]; then
  API_IMAGE="${REGISTRY}/driftguard-api:${TAG}"
  FRONTEND_IMAGE="${REGISTRY}/driftguard-frontend:${TAG}"
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " DriftGuard → Kubernetes Deployment"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " API image:      $API_IMAGE"
echo " Frontend image: $FRONTEND_IMAGE"
echo " Context:        ${CONTEXT:-<current>}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Step 1: Build Docker images ───────────────────────────────
echo ""
echo "🐳 Building API image…"
docker build -t "$API_IMAGE" -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"

echo ""
echo "🐳 Building Frontend image…"
docker build -t "$FRONTEND_IMAGE" -f "$SCRIPT_DIR/frontend/Dockerfile" "$SCRIPT_DIR/frontend"

# ── Step 2: Push (only if registry is set) ────────────────────
if [[ -n "$REGISTRY" ]]; then
  echo ""
  echo "📤 Pushing images to $REGISTRY …"
  docker push "$API_IMAGE"
  docker push "$FRONTEND_IMAGE"
fi

# ── Step 3: Load images into local cluster (if minikube/kind) ─
if command -v minikube &>/dev/null && minikube status &>/dev/null 2>&1; then
  echo ""
  echo "📦 Loading images into Minikube…"
  minikube image load "$API_IMAGE"
  minikube image load "$FRONTEND_IMAGE"
elif command -v kind &>/dev/null; then
  CLUSTER_NAME="${KIND_CLUSTER_NAME:-kind}"
  echo ""
  echo "📦 Loading images into Kind cluster ($CLUSTER_NAME)…"
  kind load docker-image "$API_IMAGE" --name "$CLUSTER_NAME"
  kind load docker-image "$FRONTEND_IMAGE" --name "$CLUSTER_NAME"
fi

# ── Step 4: Apply Kubernetes manifests ────────────────────────
echo ""
echo "🚀 Applying Kubernetes manifests…"
$KUBECTL apply -k "$SCRIPT_DIR/k8s/base"

# ── Step 5: Wait for rollout ──────────────────────────────────
echo ""
echo "⏳ Waiting for API deployment…"
$KUBECTL rollout status deployment/driftguard-api -n driftguard --timeout=120s

echo "⏳ Waiting for Frontend deployment…"
$KUBECTL rollout status deployment/driftguard-frontend -n driftguard --timeout=120s

# ── Done ──────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ✅ DriftGuard deployed successfully!"
echo ""
echo " Access the dashboard:"
echo "   kubectl port-forward svc/driftguard-frontend -n driftguard 3000:80"
echo "   → http://localhost:3000"
echo ""
echo " Access the API:"
echo "   kubectl port-forward svc/driftguard-api -n driftguard 8000:8000"
echo "   → http://localhost:8000/docs"
echo ""
echo " Check scheduler jobs:"
echo "   kubectl get cronjobs -n driftguard"
echo "   kubectl get jobs -n driftguard"
echo ""
echo " View logs:"
echo "   kubectl logs -n driftguard -l app.kubernetes.io/name=api -f"
echo "   kubectl logs -n driftguard -l app.kubernetes.io/name=scheduler"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
