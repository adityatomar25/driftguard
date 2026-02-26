# 🛡️ DriftGuard

**Automated Infrastructure Drift Detection & Reconciliation**

DriftGuard continuously monitors infrastructure managed by Terraform, detects configuration drift, classifies it by risk, and automatically reconciles safe changes — while escalating risky ones for human review.

---

## Architecture

```
┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  Terraform   │────▶│  Detector   │────▶│  Classifier  │
│  (IaC)       │     │  plan+show  │     │  (YAML rules)│
└──────────────┘     └─────────────┘     └──────┬───────┘
                                                │
                                         ┌──────▼───────┐
                                         │   Decision   │
                                         │   Engine     │
                                         └──────┬───────┘
                                    ┌────────────┼────────────┐
                                    ▼            ▼            ▼
                             ┌──────────┐ ┌──────────┐ ┌──────────┐
                             │ Auto     │ │ Create   │ │  Alert   │
                             │ Apply    │ │ PR/Manual│ │  Only    │
                             └────┬─────┘ └──────────┘ └──────────┘
                                  ▼
                           ┌──────────┐
                           │ Verifier │
                           │ (no-diff)│
                           └──────────┘
```

## Project Structure

```
driftguard/
├── driftguard/            # Python backend
│   ├── __init__.py
│   ├── detector.py        # Terraform plan/show JSON parser
│   ├── classifier.py      # YAML rule-based drift classifier
│   ├── decision.py        # Environment-aware decision engine
│   ├── reconciler.py      # Safe auto-apply + PR creation
│   ├── verifier.py        # Post-reconciliation verification
│   ├── storage.py         # SQLite event store + audit log
│   ├── models.py          # SQLAlchemy models
│   ├── pipeline.py        # Full detect→classify→decide→reconcile→verify loop
│   ├── alerter.py         # Slack/console alerting
│   ├── api.py             # FastAPI REST API for dashboard
│   ├── cli.py             # CLI entry point
│   └── config.yml         # Classification rules
├── terraform/             # Local demo (Docker provider)
│   └── main.tf
├── terraform-aws/         # AWS cloud example
│   └── main.tf
├── frontend/              # React + Vite dashboard
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   └── index.css
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── tests/                 # Unit tests
│   ├── test_detector.py
│   ├── test_classifier.py
│   ├── test_decision.py
│   ├── test_storage.py
│   └── test_api.py
├── .github/workflows/ci.yml
├── requirements.txt
└── README.md
```

## Quick Start

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Local Demo (Docker)

**Prerequisites:** Terraform CLI, Docker running.

```bash
# Deploy baseline infrastructure
cd terraform
terraform init
terraform apply -auto-approve
cd ..

# Simulate drift: manually change the container
docker stop driftguard_demo
docker rm driftguard_demo
docker run -d --name driftguard_demo -p 8081:80 nginx:alpine

# Run DriftGuard pipeline
python -m driftguard.cli --tf-dir ./terraform --rules driftguard/config.yml -v
```

### 3. AWS Cloud Demo

**Prerequisites:** AWS CLI configured, valid credentials.

```bash
cd terraform-aws
# Edit backend config in main.tf (S3 bucket, DynamoDB table)
terraform init
terraform apply -auto-approve
cd ..

# Simulate drift: manually change a resource via AWS Console
# Then run DriftGuard
python -m driftguard.cli --tf-dir ./terraform-aws --rules driftguard/config.yml -v
```

### 4. Dashboard

```bash
# Start API server
uvicorn driftguard.api:app --reload --port 8000

# Start frontend (in another terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 to view the dashboard.

### 5. Run Tests

```bash
pytest tests/ -v
```

## Classification Rules

Edit `driftguard/config.yml` to customise drift classification:

```yaml
default: alert
risk_weights:
  resource_type:
    aws_instance: 7
    aws_security_group: 9
  action_type:
    delete: 10
    update: 4
  env:
    prod: 10
    dev: 2
require_approval:
  - aws_instance
  - aws_security_group
auto_reconcile:
  - docker_container
ignore:
  - aws_autoscaling_group
```

## CLI Options

```
python -m driftguard.cli \
  --tf-dir ./terraform \
  --rules driftguard/config.yml \
  --db sqlite:///driftguard.db \
  --dry-run \
  --verbose
```

| Flag                | Description                                |
| ------------------- | ------------------------------------------ |
| `--tf-dir`          | Path to Terraform working directory        |
| `--rules`           | Path to classification rules YAML          |
| `--db`              | Database URL (default: sqlite)             |
| `--dry-run`         | Preview actions without applying           |
| `--auto-apply-prod` | Allow auto-apply in production (dangerous) |
| `--skip-init`       | Skip terraform init                        |
| `-v`                | Verbose logging                            |

## API Endpoints

| Method | Path                          | Description              |
| ------ | ----------------------------- | ------------------------ |
| GET    | `/api/health`                 | Health check             |
| GET    | `/api/events`                 | List drift events        |
| GET    | `/api/events/{id}`            | Event detail             |
| POST   | `/api/events/{id}/action`     | Trigger action on event  |
| GET    | `/api/metrics`                | Summary counts           |
| GET    | `/api/audit`                  | Audit log entries        |

## License

MIT
