# snaPDF — Documentation Log

A living document of every step and decision made in this project, explained in plain English.
Updated throughout the build.

---

## Table of Contents
1. [Key Decisions](#key-decisions)
2. [Infrastructure (Phase 0 — Bootstrap)](#phase-0--bootstrap)
3. [Infrastructure (Phase 1 — Modules + Deploy)](#phase-1--infrastructure-modules--deploy)
4. [App](#app)
5. [CI/CD Workflow](#cicd-workflow)
6. [GitOps](#gitops)
7. [Secrets](#secrets)
8. [Bug Fixes](#bug-fixes)

---

## Key Decisions

> These are the big architectural choices made during the project and the reasoning behind each one.

### 1. Terragrunt over plain Terraform
**Decision:** Use Terragrunt as a wrapper around Terraform.
**Why:** We have two environments (dev and prod). Without Terragrunt, every module would need its own backend config, provider block, and region setting — duplicated for every environment. Terragrunt lets us define those once in a root `terragrunt.hcl` and inherit them everywhere. Less repetition = fewer mistakes.

### 2. S3 native locking instead of DynamoDB
**Decision:** Use `use_lockfile = true` in the S3 backend config (Terraform 1.10+) instead of a DynamoDB table.
**Why:** DynamoDB locking requires creating and managing a separate AWS resource. S3 native locking does the same thing with a `.tflock` file in the same bucket — no extra resource needed. We still created the DynamoDB table from the old approach, but the active lock mechanism is S3-native.

### 3. t3.medium nodes for EKS
**Decision:** Use `t3.medium` EC2 instances (2 vCPU, 4GB RAM) for the EKS node group, 2 nodes desired.
**Why:** Started with t3.small (2GB RAM) but hit memory pressure running 4 addon pods + 4 app pods concurrently. t3.medium doubles the RAM per node, giving comfortable headroom. Started with 3x t3.small as an interim workaround while the AWS account was restricted to Free Tier instance types — once the account was upgraded, reverted to 2x t3.medium which is the right balance of cost and capacity.

### 4. Two SQS queues (signed + free) instead of one
**Decision:** Create two separate SQS queues — one for signed (paying) users and one for free users.
**Why:** Priority processing. Signed users get their PDFs processed by a KEDA-scaled worker that spins up more pods under load. Free users get a single always-on worker that processes at a steady pace. One queue would mean both user types compete equally — defeating the priority logic.

### 5. KEDA only on the signed queue
**Decision:** KEDA ScaledObject watches only the signed queue, not the free queue.
**Why:** KEDA scales the signed worker from 0 to 3 pods based on queue depth. The free worker stays at exactly 1 pod always. This demonstrates the key concept: signed users get burst capacity, free users get guaranteed-but-limited throughput. Scaling both queues the same way would remove the distinction.

### 6. Two separate worker Deployments
**Decision:** `signed-worker` and `free-worker` are separate Kubernetes Deployments.
**Why:** They need different scaling behavior (KEDA vs fixed), different queue URLs as environment variables, and potentially different resource limits in the future. Same Docker image, different config.

### 7. Word-to-PDF conversion using LibreOffice
**Decision:** The app accepts `.docx` uploads and converts them to PDF using LibreOffice in headless mode (`libreoffice --headless --convert-to pdf`), stores the result in S3, and saves metadata to RDS.
**Why:** LibreOffice handles real Word files perfectly and runs without a GUI. The alternative (WeasyPrint) only converts HTML — not useful for a document converter. LibreOffice adds ~300MB to the image but is the production-standard approach for `.docx` → PDF.

### 8. ECR over GitHub Container Registry (GHCR)
**Decision:** Store Docker images in AWS ECR, not GHCR.
**Why:** ECR lives in the same AWS account as the cluster. EKS can pull from ECR without any extra credentials — the node's IAM role already has access. GHCR would require creating and managing a Kubernetes image pull secret.

### 9. ArgoCD exposed via LoadBalancer
**Decision:** ArgoCD server is exposed as a `LoadBalancer` service type, not `ClusterIP` or `NodePort`.
**Why:** LoadBalancer creates a real AWS load balancer with a public DNS name, making the ArgoCD UI reachable from a browser. For a demo/interview this is the simplest approach. In production you'd put it behind an Ingress with TLS.

### 10. No Route 53 or CloudFront
**Decision:** Skip DNS and CDN for now.
**Why:** Route 53 requires a registered domain (~$12/year) and is only needed for a custom URL like `snapdf.com`. CloudFront is a CDN for static assets — this project serves a dynamic API, so caching at the edge adds no value. The ALB URL works fine for a demo.

### 11. Destroy everything when not working
**Decision:** Run `terragrunt run-all destroy` at the end of each session.
**Why:** EKS costs $73/month for the control plane alone, even with 0 nodes running. Keeping it on overnight for no reason wastes money. `terragrunt run-all apply` rebuilds everything in ~40 minutes when needed.

### 12. Global module for cross-environment resources
**Decision:** Created an `infra/global/` directory (not inside `environments/dev` or `prod`) for ECR and the API key secret.
**Why:** ECR is shared — both dev and prod pull images from the same repository. The API key secret is also account-wide. Putting these inside an environment directory would suggest they belong to only that environment.

### 14. Two separate DB tables (signed_jobs + free_jobs)
**Decision:** Signed users' jobs are stored in `signed_jobs` (includes `username` column), free users' jobs in `free_jobs` (no username).
**Why:** Different data shapes per user type. Signed jobs carry identity (username) which is meaningful for auditing and per-user history. Free jobs are anonymous. One table with a nullable `username` column would work, but two tables makes the schema intention clear.

### 15. Two-layer ingress: ALB + Nginx
**Decision:** Use AWS ALB (via ALB Controller) at the edge and Nginx Ingress Controller inside the cluster.
**Why:** ALB handles AWS-level concerns (SSL termination, WAF, DDoS). Nginx handles cluster-level routing (path rules, rate limiting, rewrites). One shared ALB serves all HTTP services — cheaper than one LoadBalancer per service. Workers are never exposed over HTTP.

### 16. One generic Helm chart for all services
**Decision:** One chart at `charts/service/` reused for api, workers, and auth. Features toggled via values.
**Why:** Avoids duplicating Deployment/Service/Ingress templates per service. All services share the same structure — only the values differ. Adding a new service = add a values file, no new chart needed.

### 17. ApplicationSet over App of Apps
**Decision:** Use ArgoCD ApplicationSet to generate apps per service per environment.
**Why:** App of Apps requires manually writing one Application YAML per service. ApplicationSet generates them from a template automatically — adding a new service or environment means adding one values file, not touching the ArgoCD config.

### 13. `recovery_window_in_days = 0` for Secrets Manager
**Decision:** Set the recovery window to 0 on the API key secret.
**Why:** By default AWS holds deleted secrets for 30 days (recovery period). With Terraform, if you run `destroy` you want the secret gone immediately — otherwise the next `apply` fails because a secret with that name already "exists" in recovery. Setting `0` allows immediate deletion.

---

## Phase 0 — Bootstrap

### Tool Installation
- **What:** Installed git, AWS CLI, kubectl, terraform, terragrunt, helm on Windows.
- **Why:** These are the core tools for the entire project. Without them nothing can be built or deployed.
- **How:** git/aws/kubectl were already present. terraform and helm installed via `winget`, then copied to `C:\Windows\System32`. terragrunt downloaded as a single `.exe` from the official GitHub release and placed in `System32`.
- **Tool roles:**
  | Tool | Role |
  |------|------|
  | `git` | Version control — GitHub Actions uses git SHA to tag Docker images |
  | `aws cli` | Talks to AWS from the terminal — creating resources, authenticating kubectl |
  | `kubectl` | Kubernetes CLI — inspect pods, nodes, services, ArgoCD status |
  | `terraform` | IaC tool — provisions AWS resources from `.tf` files |
  | `terragrunt` | Wrapper around Terraform — removes config repetition between dev and prod |
  | `helm` | Kubernetes package manager — installs ArgoCD, KEDA, ESO, ALB controller |

### AWS CLI Configuration
- **What:** Ran `aws configure` to authenticate the CLI.
- **Why:** Every AWS command needs to know which account to talk to and with what permissions.
- **Security decision:** Created a dedicated IAM user (`admin`) instead of root access keys. Root keys can never be restricted — one leak = entire AWS account compromised. IAM user keys can be revoked at any time.
- **Verified with:** `aws sts get-caller-identity` → Account `086241318869`, user `admin`.

### S3 Bucket for Terraform State
- **What:** Created `snapdf-tf-state-086241318869` in `us-east-1` with versioning enabled.
- **Why:** Terraform state must live somewhere safe and shared. Local state only exists on your laptop — lose it, and Terraform loses track of all infrastructure. S3 keeps it safe and accessible from any machine.
- **Why versioning:** A corrupted state file (from a failed apply mid-run) can be restored from the previous S3 version.
- **Why account ID in bucket name:** S3 bucket names are globally unique across all AWS accounts worldwide.

### DynamoDB Table for State Locking
- **What:** Created `snapdf-tf-locks` table in `us-east-1`.
- **Why:** Without locking, two Terraform runs starting at the same time would both write to the state file and corrupt it. DynamoDB acts as a distributed lock — one run writes a lock entry, any other run waits until it's released.
- **Note:** We now use S3 native locking (`use_lockfile = true`) — the DynamoDB table was created early but is no longer the active lock mechanism.

### ECR Repository
- **What:** Created `snapdf-app` ECR repository in `us-east-1`.
- **URI:** `086241318869.dkr.ecr.us-east-1.amazonaws.com/snapdf-app`
- **Why:** ECR is the bridge between CI and the cluster. GitHub Actions builds the Docker image and pushes it here. EKS pulls from here when deploying. Images are tagged by git SHA (e.g. `:a3f9c12`) so every deployment is traceable to an exact commit.

### GitHub Workflow Setup
- **What:** Created issue + PR templates, branch naming convention, authenticated `gh` CLI.
- **Convention:** Branch names follow `type/description` format (e.g. `feature/vpc-module`, `fix/iam-role`).
- **Why:** Every change has a paper trail — issue (the problem) → branch (the work) → PR (the solution). This is standard practice in real engineering teams and makes the project history readable.

---

## Phase 1 — Infrastructure Modules + Deploy

### Module Structure
All reusable Terraform code lives in `infra/modules/`. Environment-specific configuration lives in `infra/environments/dev/` and `infra/environments/prod/`. Each environment folder has a subfolder per module (e.g. `environments/dev/vpc/terragrunt.hcl`) that points to the shared module and passes environment-specific inputs.

### Modules Written

#### `vpc`
Creates the network layer: VPC, 3 tiers of subnets (public/private/database), Internet Gateway, NAT Gateway, route tables, and a DB subnet group.
- **Public subnets** — ALB and NAT Gateway live here (internet-facing)
- **Private subnets** — EKS worker nodes live here (no direct internet access)
- **Database subnets** — RDS lives here (no internet access at all)
- **NAT Gateway** — lets private subnet resources (pods) reach the internet for pulling images, without exposing them

#### `eks`
Creates the Kubernetes control plane and worker nodes.
- Control plane is fully managed by AWS — we don't manage the API server
- Node group: t3.small, min=1, max=3, desired=2
- Also creates the OIDC provider needed for IRSA (pods assuming IAM roles)

#### `iam`
Creates 4 IAM roles, each scoped to a specific Kubernetes service account via IRSA:
- **ALB controller role** — permission to create/update/delete AWS load balancers
- **ESO role** — permission to read secrets from AWS Secrets Manager
- **KEDA role** — permission to read SQS queue depth (`sqs:GetQueueAttributes`)
- **Worker role** — permission to read/delete messages from both SQS queues + read/write S3

IRSA (IAM Roles for Service Accounts) means each pod gets exactly the permissions it needs, and nothing else. No shared credentials, no overly broad roles.

#### `rds`
Creates a PostgreSQL 15 instance in the database subnet.
- Stores: PDF job metadata (user ID, S3 key, status, timestamps)
- Not publicly accessible — only reachable from within the VPC
- Password stored in AWS Secrets Manager, synced into Kubernetes by ESO

#### `sqs`
Creates two queues:
- `snapdf-dev-signed` — for signed (paying) users, KEDA-watched
- `snapdf-dev-free` — for free users, processed by 1 steady worker
- Both have 60s visibility timeout (message reappears for retry if worker crashes) and 1 hour retention

#### `s3`
Creates a private S3 bucket for storing generated PDFs.
- Bucket name includes account ID for global uniqueness
- All public access blocked — PDFs are served via presigned URLs (temporary, expiring links)

#### `global`
Contains resources shared across all environments:
- ECR repository (one repo, both dev and prod pull from it)
- Secrets Manager secret slot for the API key (value set manually after apply)

#### `addons`
Installs 4 Helm charts onto the EKS cluster:
- **ALB Ingress Controller** — watches Ingress resources, creates AWS ALBs
- **External Secrets Operator (ESO)** — syncs Secrets Manager values into K8s secrets
- **ArgoCD** — GitOps CD, watches the gitops repo and deploys changes automatically
- **KEDA** — watches ScaledObject resources, scales signed-worker based on SQS depth

### Deploy Order (dev)
Must apply in this exact order due to dependency chain:

| Step | Module | Depends On |
|------|--------|------------|
| 1 | vpc | nothing |
| 2 | eks | vpc (subnet IDs) |
| 3 | sqs | nothing |
| 4 | s3 | nothing |
| 5 | iam | eks (OIDC ARN) + sqs (queue ARNs) + s3 (bucket ARN) |
| 6 | rds | vpc (subnet group) + eks (node security group) |
| 7 | addons | eks (endpoint + CA cert) + iam (role ARNs) + vpc (VPC ID) |
| 8 | global | nothing (ECR + secret slot, no cross-module deps) |

---

## App

### Hello World (test deployment)
- **What:** Minimal Flask app with `/` (HTML page) and `/health` (JSON `{"status":"ok"}`)
- **Why:** Before building the full PDF app, we deploy a simple page to verify the entire pipeline works end-to-end: image build → ECR push → EKS deployment → ALB → browser.
- **Files:** `app/app.py`, `app/requirements.txt`, `app/Dockerfile`

### Full PDF Converter App (Phase 2)
Three services share one Docker image, started with different commands in Kubernetes:

**API (`app.py`)**
- `GET /` — web UI with file upload form. User uploads `.docx` + optional API key + username.
- `POST /convert` — validates API key, uploads `.docx` to S3 (`uploads/<job_id>.docx`), puts a message in the signed or free SQS queue, returns `job_id`.
- `GET /jobs/<job_id>` — queries RDS for job status. If done, returns a presigned S3 URL (expires in 1 hour) to download the PDF.

**Worker (`worker.py`)**
- Same code for both signed and free workers — controlled by `QUEUE_TYPE` env var.
- On startup: creates `signed_jobs` and `free_jobs` tables in RDS if they don't exist.
- Loop: polls SQS (long polling, 20s wait), downloads `.docx` from S3, runs LibreOffice to convert, uploads PDF to S3 (`outputs/<job_id>.pdf`), updates job row to `done`, deletes SQS message.
- On failure: marks job as `failed` in DB, still deletes the SQS message (no infinite retry).

**Dockerfile (multi-stage)**
- Stage 1 (builder): installs Python packages into `/install` prefix.
- Stage 2 (runtime): installs LibreOffice via apt, copies Python packages from builder, copies `app.py` and `worker.py`. Default CMD starts the API.

**DB Tables**
- `free_jobs`: `job_id`, `s3_key`, `status`, `created_at`
- `signed_jobs`: `job_id`, `username`, `s3_key`, `status`, `created_at`

**Manual deploy (temporary)**
- Used `kubectl apply` with a raw Deployment + LoadBalancer Service to verify the app works before Helm/ArgoCD is set up.
- File: `deploy-dev.yaml` in the repo root (not committed — temporary).

---

## CI/CD Workflow

### Phase 2 CI Pipeline (replaced in Phase 3)

The original pipeline was a single workflow file (`.github/workflows/ci.yml`) that triggered on every push to `main`. It built one shared Docker image containing all services, pushed it to a single ECR repo (`snapdf-app`), then directly restarted Kubernetes pods using `kubectl rollout restart`. This was a working first version but had two problems — every push rebuilt everything even if only one service changed, and CI was directly touching the cluster instead of going through GitOps.

---

### Phase 3 CI Pipeline (current)

In Phase 3 the CI was completely rearchitected. The single workflow was replaced with three separate workflows, one per microservice.

#### Why separate workflows?

Each microservice now has its own dedicated workflow file:
- `.github/workflows/ci-api.yml`
- `.github/workflows/ci-worker.yml`
- `.github/workflows/ci-auth.yml`

Each workflow only triggers when its own directory changes:
```yaml
on:
  push:
    paths:
      - 'api/**'   # only this workflow cares about api/ changes
```

This means pushing a bug fix to `api/` only rebuilds the api image. The worker and auth images stay untouched. In Phase 2, every push rebuilt all services even if only one line changed.

#### What each workflow does

Every workflow follows the same sequence:

| Step | What it does |
|------|-------------|
| Checkout | Clones the repo onto GitHub's server |
| AWS auth (OIDC) | Keyless authentication — GitHub proves its identity, AWS issues temporary credentials |
| ECR login | Authenticates Docker to ECR using those credentials |
| Lint | Runs `flake8` — stops the pipeline if any code style errors |
| Unit tests | Runs `pytest` — stops the pipeline if any test fails |
| Build + push | Builds the Docker image, tags it with the git SHA and `:latest`, pushes to that service's ECR repo |
| Update gitops | Clones `snaPDF-gitops`, updates the image tag in the values file, pushes back |

The pipeline stops at any failing step — a broken test means no image gets built, no deployment happens.

#### Separate ECR repos per service

Each service now has its own ECR repository:
- `snapdf-api` — Flask web server image (~200MB, no LibreOffice)
- `snapdf-worker` — Worker image (~700MB, includes LibreOffice)
- `snapdf-auth` — Auth service image (~150MB, placeholder for now)

Previously one shared `snapdf-app` repo held everything. Separate repos mean each service has its own image history — you can see exactly which commits changed which service, and roll back one service independently of the others.

#### The GitOps handoff — key difference from Phase 2

In Phase 2, CI directly restarted pods:
```
CI → kubectl rollout restart → cluster
```

In Phase 3, CI never touches the cluster. Instead it updates a values file in the gitops repo:
```
CI → updates environments/dev/api-values.yaml (new image tag) → git push
ArgoCD sees the change → runs helm upgrade → cluster updated
```

CI's job ends at the git push. ArgoCD takes over from there. This separation means the cluster's desired state always lives in git — you can see exactly what version is deployed by reading the values file.

#### How environments work

The repo has three long-lived branches, one per environment:
```
main     → dev environment
staging  → staging environment
prod     → prod environment
```

The same workflow file handles all three environments by checking which branch triggered it:
```
Push to main    → workflow runs → updates environments/dev/api-values.yaml
Push to staging → workflow runs → updates environments/staging/api-values.yaml
Push to prod    → workflow runs → updates environments/prod/api-values.yaml
```

**Day to day — you only touch `main`:**
Write code, push to `main`, CI runs, dev gets updated automatically. You never write code directly to `staging` or `prod`.

**Promoting to staging:**
When dev is verified and you want to move the same code to staging, you merge `main` into `staging`:
```bash
git checkout staging
git merge main
git push origin staging
```
CI triggers on the `staging` branch, updates `environments/staging/api-values.yaml`, ArgoCD deploys to staging automatically.

**Promoting to prod:**
When staging is verified, merge `staging` into `prod`:
```bash
git checkout prod
git merge staging
git push origin prod
```
CI triggers, updates `environments/prod/api-values.yaml`. ArgoCD sees the change but does **not deploy automatically** — someone must click Sync in the ArgoCD UI to approve the production deployment.

**The full promotion flow:**
```
write code → push to main → dev ✅
                ↓
         git merge main → staging → staging ✅
                ↓
         git merge staging → prod → prod (manual approval in ArgoCD UI)
```

You never skip a step — prod always has exactly what staging had, staging always has exactly what dev had. This means if something works in staging, you know with confidence it will work in prod.

#### Unit tests

Each service has a `tests/` directory with pytest unit tests. Tests run in CI before the image is built — a failing test blocks the entire pipeline.

Tests use mocks to replace real AWS calls (SQS, S3) and the database so they run in CI without any infrastructure:

- `api/tests/test_app.py` — tests all Flask endpoints: file validation, queue routing (signed vs free), job status responses
- `worker/tests/test_worker.py` — tests the `process()` function: happy path (insert pending → convert → mark done), failure path (S3 error → mark failed → still delete SQS message)
- `auth/tests/test_main.py` — placeholder, real tests added when auth code is implemented

#### Microservice restructure

The app directory was reorganised from one flat folder into separate microservice directories:

```
Before (Phase 2):        After (Phase 3):
app/                     api/
  app.py                   app.py
  worker.py                requirements.txt
  Dockerfile               Dockerfile
  requirements.txt         tests/
                             test_app.py
                         worker/
                           worker.py
                           requirements.txt
                           Dockerfile
                           tests/
                             test_worker.py
                         auth/
                           main.py          ← placeholder
                           requirements.txt
                           Dockerfile
                           tests/
                             test_main.py
```

Each service has its own `requirements.txt` with only what it needs — the worker no longer has Flask as a dependency since it never serves HTTP traffic.

---

## GitOps

### Three-Repo Architecture
The project is split across three Git repositories, each with a clear owner:

| Repo | Owner | Contains |
|------|-------|----------|
| `snaPDF` | Developers | App code, Dockerfile, CI pipeline |
| `snaPDF-infra` | Platform team | Terraform modules, Terragrunt configs |
| `snaPDF-gitops` | ArgoCD | Helm charts, environment values, ArgoCD apps |

This separation is intentional. App developers should never need to touch infra. ArgoCD only watches the gitops repo — so it can't accidentally deploy untested code from the app repo.

### Traffic Flow — Two-Layer Ingress (ALB + Nginx)
```
Internet
    ↓
AWS ALB  ← created by ALB Controller from an Ingress resource
    ↓         (handles SSL termination, AWS WAF, DDoS protection)
Nginx pod ← runs inside the cluster, installed via ArgoCD
    ↓         (handles path-based routing, rate limiting, rewrites)
api-service or auth-service
```

**Why two layers:**
- The ALB (AWS-native) is the internet-facing entry point. It handles SSL, WAF rules, and AWS Shield — things that need to happen at the AWS level before traffic enters the cluster.
- Nginx (cluster-native) handles smart routing: `/api/*` → api pods, `/auth/*` → auth pods. ALB alone can do path routing, but Nginx gives more control (rate limiting, header rewriting, auth delegation) without AWS vendor lock-in on routing rules.
- Workers (free-worker, signed-worker) are never exposed — they only listen to SQS queues, not HTTP.

**Why ALB controller is in Terraform (not ArgoCD):**
The ALB controller must exist before anything else can get internet traffic. ArgoCD itself might need network access to start. Installing infra-level prerequisites via ArgoCD creates a chicken-and-egg problem. Rule: if it needs to exist before the cluster can do anything, Terraform owns it.

### gitops Repo Structure
```
snaPDF-gitops/
├── apps/
│   ├── services-appset.yaml   ← generates one ArgoCD app per service per env
│   ├── eso-appset.yaml        ← generates ExternalSecret resources per env
│   └── nginx-app.yaml         ← installs Nginx Ingress Controller
├── charts/
│   └── service/               ← one generic chart reused for api, workers, auth
│       ├── Chart.yaml
│       ├── values.yaml        ← defaults
│       └── templates/
│           ├── deployment.yaml
│           ├── service.yaml
│           ├── ingress-nginx.yaml   ← if ingress.enabled=true (api, auth only)
│           ├── scaledobject.yaml    ← if keda.enabled=true (signed-worker only)
│           ├── hpa.yaml             ← if hpa.enabled=true (api only)
│           └── externalsecret.yaml  ← if eso.enabled=true
└── environments/
    ├── dev/
    │   ├── api-values.yaml
    │   ├── free-worker-values.yaml
    │   └── signed-worker-values.yaml
    └── prod/
        └── (same structure)
```

### One Generic Helm Chart
All services (api, free-worker, signed-worker, auth) use the same chart at `charts/service/`. Each service gets its own values file in `environments/{env}/`. Features are toggled on/off per service:

| Feature | api | free-worker | signed-worker | auth |
|---------|-----|-------------|---------------|------|
| Ingress (Nginx) | ✅ | ❌ | ❌ | ✅ |
| HPA (CPU scaling) | ✅ | ❌ | ❌ | ✅ |
| KEDA (SQS scaling) | ❌ | ❌ | ✅ | ❌ |
| ExternalSecret (ESO) | ✅ | ✅ | ✅ | ✅ |

### ApplicationSet vs App of Apps
We use **ApplicationSet** (not App of Apps). The difference:
- **App of Apps** — one parent ArgoCD Application points to a folder of other Application YAMLs. Simple but static.
- **ApplicationSet** — generates ArgoCD Applications dynamically from a template + a list of inputs (e.g. environments × services). One ApplicationSet generates 6 apps (3 services × 2 envs) automatically.

`services-appset.yaml` generates one ArgoCD Application per service per environment, each pointing at `charts/service/` with the correct values file from `environments/{env}/{service}-values.yaml`.

### ESO Resources in gitops
The ESO **controller** lives in Terraform (addon). The ESO **resources** live in the gitops repo:
- `ClusterSecretStore` — tells ESO how to connect to AWS Secrets Manager (which region, which IAM role)
- `ExternalSecret` — tells ESO which secret to fetch and what to name the resulting Kubernetes Secret

These are app-level config (not infra), so ArgoCD manages them. `eso-appset.yaml` generates ExternalSecret resources per environment.

### ArgoCD RBAC — AppProject split (added 01/07/2026)

Previously every one of the 12 Applications used ArgoCD's built-in `project: default` — completely unrestricted, no isolation between dev/staging and prod. Fixed by adding `apps/appprojects.yaml` (two `AppProject` objects) and wiring `services-appset.yaml`'s two existing generators to them:

- **`non-prod`** — covers `dev` and `staging` namespaces on the local cluster, no extra restrictions, still auto-syncs exactly as before.
- **`prod`** — covers the `production` namespace on the (future) prod cluster, with a `syncWindows` deny-rule (`manualSync: true`, effectively permanent) that blocks **all** automated syncing at the project level. This is stronger than just leaving `syncPolicy.automated` off on individual prod Applications — even if a prod values file accidentally set auto-sync, the `AppProject` itself overrides it. No prod deploy can happen without a human manually clicking Sync.

There are two distinct things people call "ArgoCD RBAC": `AppProject` (restricts what a group of Applications can do — which repos, which clusters/namespaces, sync policy — enforced regardless of who's asking) and `argocd-rbac-cm` (restricts what logged-in *human users* can click, requires real user accounts/SSO to be meaningful). Only `AppProject` was implemented here — for a solo-operator project, it's the one that actually protects prod from accidents; the user-level RBAC layer only becomes meaningful once multiple real people with different trust levels are involved.

**Where the split is enforced:** `apps/services-appset.yaml` already had two separate generator blocks (dev/staging vs. prod) from Phase 4 — each generator's own `template.spec.project` now points at `non-prod` or `prod` respectively, reusing that existing structure with no new mechanism needed.

Verified live: `kubectl get application api-dev -n argocd -o jsonpath='{.spec.project}'` → `non-prod`; same command on `api-prod` → `prod`.

### Phase 4 Design Decisions

#### Where does the root ArgoCD Application live?
The root Application is the one-time bootstrap that tells ArgoCD "watch the `apps/` folder in snaPDF-gitops and deploy everything you find there." It lives in **snaPDF-infra** (`bootstrap/root-app.yaml`), not in the gitops repo.

Why: if it lived in the gitops repo, ArgoCD would need to be watching the gitops repo before it could read the file that tells it to watch the gitops repo — a chicken-and-egg problem. The infra repo is where we bootstrap the cluster; the root Application is part of that bootstrap. It is applied once with `kubectl apply -f bootstrap/root-app.yaml` after `terragrunt apply`.

#### ApplicationSet vs Application — which files use which?
| File | Kind | Why |
|---|---|---|
| `nginx-app.yaml` | `Application` | One Nginx install, one cluster — no generation needed |
| `eso-appset.yaml` | `ApplicationSet` | One ClusterSecretStore needed per cluster (dev + prod) — generator stamps it out for each |
| `services-appset.yaml` | `ApplicationSet` | One app per service per environment — generator produces all combinations |

An **Application** is a single ArgoCD deployment. An **ApplicationSet** generates multiple Applications from a template using a generator (list, git directory, cluster, etc.).

#### Single ArgoCD instance vs one per cluster
We run **one shared ArgoCD instance** on the dev cluster that manages both dev and prod.

- **Single instance (our choice):** One ArgoCD installation on dev. Prod cluster is registered as a remote destination. One UI, one set of ApplicationSets, less operational overhead. The ApplicationSet list generator can target both clusters from one place. Standard choice for small teams and demos.
- **One per cluster:** Each cluster runs its own ArgoCD. More isolation — prod ArgoCD going down doesn't affect dev. Required in regulated industries (finance, healthcare) where the dev cluster must not hold credentials for prod. Higher operational cost.

For an interview assessment, single instance is the right call — it directly demonstrates the multi-cluster ApplicationSet pattern, which is more impressive than two isolated installs.

#### Where should cluster addons live — Terraform or ArgoCD?

**Option A — All addons in Terraform (ALB controller, ESO, KEDA, Nginx, ArgoCD)**
Terraform installs everything cluster-level. ArgoCD manages only the application services. Clean rule: *Terraform owns the cluster, ArgoCD owns the apps.*

**Option B — Terraform installs ArgoCD only, ArgoCD manages everything else**
Pure GitOps — every addon change goes through a git push + ArgoCD sync. Nginx, ESO, KEDA are ArgoCD Applications in the gitops repo.

**The problem with Option B:** ALB controller, ESO, and KEDA all need an IAM role ARN injected at install time (via IRSA annotation on their service account). Those ARNs come from Terraform's IAM module outputs. ArgoCD has no way to read Terraform outputs — creating a dependency: Terraform knows the ARN, ArgoCD needs it, but they don't talk to each other.

**How to solve Option B if you want it:** The ARNs in this project are deterministic — we know the account ID (`086241318869`) and the role naming convention (`snapdf-dev-<name>`). So the full ARN for ESO is always `arn:aws:iam::086241318869:role/snapdf-dev-eso`. You can hardcode these in the gitops values files without fragility — they only change if you rename the roles or switch accounts, both of which require intentional changes anyway.

**Decision:** Option A — keep all addons in Terraform, ArgoCD manages only app services. Consistent, simpler, and easy to explain. A hybrid (some addons in Terraform, some in ArgoCD) would be inconsistent with no clean rule for what goes where.

---

### Root ArgoCD Application (`infra/bootstrap/root-app.yaml`)

The root Application is the one-time bootstrap that starts the entire GitOps chain. Applied once with `kubectl apply` after the cluster is up — never touched again.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/ilaycohen12/snaPDF-gitops.git
    targetRevision: HEAD
    path: apps
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

| Field | What it does |
|---|---|
| `kind: Application` | Single Application — not an ApplicationSet. One root that spawns everything else |
| `name: root` | The name shown in the ArgoCD UI |
| `namespace: argocd` | This Application object lives in the argocd namespace, where ArgoCD looks for things to manage |
| `finalizers` | When you delete the root app, ArgoCD cascades the deletion to all child apps. Without this, deleting root leaves all child ApplicationSets as orphans |
| `path: apps` | Points at the `apps/` folder in snaPDF-gitops — ArgoCD finds `eso-appset.yaml` and `services-appset.yaml` there and deploys them |
| `destination.server` | Deploy the Application objects themselves to the local cluster where ArgoCD is running |
| `destination.namespace: argocd` | The ApplicationSets get created in the argocd namespace |
| `syncPolicy: automated` | ArgoCD watches `apps/` and syncs automatically on every push |

### services-appset.yaml — Git Directory Generator

Uses two Git generators (not a list) so services are discovered automatically from the folder structure. Adding a new service = create a new folder, no YAML editing needed.

- **Generator 1** — discovers `environments/dev/*` and `environments/staging/*`, sets destination server to `https://kubernetes.default.svc` (dev cluster, in-cluster)
- **Generator 2** — discovers `environments/prod/*`, sets destination server to the prod cluster endpoint

ArgoCD path variables extracted from the folder path `environments/{env}/{service}`:
- `{{path.basename}}` → service name (e.g. `api`, `signed-worker`)
- `{{path[1]}}` → environment name (e.g. `dev`, `prod`) — used as both the namespace and app name suffix
- `{{path}}` → full path used to build the values file reference: `/{{path}}/values.yaml`

Generated app names follow the pattern `{service}-{env}` (e.g. `api-dev`, `signed-worker-prod`). 12 Applications total: 4 services × 3 environments.

### eso-appset.yaml — ClusterSecretStore per Cluster

Uses the `clusters: {}` generator which automatically targets every cluster registered in ArgoCD. When the prod cluster is registered in Step 11, ArgoCD deploys the ClusterSecretStore to prod automatically — no config change needed.

The ClusterSecretStore (`bootstrap/eso/clustersecretstore.yaml`) tells ESO:
- Use AWS Secrets Manager in `us-east-1`
- Authenticate using the `external-secrets` ServiceAccount (which has the IRSA annotation with the ESO IAM role)

ESO's own pods handle the AWS authentication — app pods never call Secrets Manager directly. They just read the Kubernetes Secret that ESO created.

### GitOps Deployment Flow (Phase 4 target)
```
Developer pushes code to snaPDF repo
    ↓
GitHub Actions CI: lint → build → push image to ECR
    ↓
CI updates image tag in snaPDF-gitops/environments/dev/api-values.yaml
    ↓
ArgoCD detects git change in snaPDF-gitops
    ↓
ArgoCD runs helm upgrade with new values
    ↓
New pods roll out in dev cluster
```
No manual `kubectl` in production. Git is the single source of truth.

### Full Bootstrap-to-Pod Flow (detailed — how the ApplicationSets themselves get applied)

The flow above skips one layer: how do `services-appset.yaml` and `eso-appset.yaml` themselves ever get onto the cluster in the first place? Nothing auto-applies them until ArgoCD exists and knows to watch for them — a genuine chicken-and-egg problem. Here's the full chain, one layer at a time:

```
STEP 0 — ONE TIME ONLY, manual, from the infra repo
────────────────────────────────────────────────────
  you run: kubectl apply -f infra/bootstrap/root-app.yaml
      ↓
  creates ArgoCD Application "root"
  "root" is told: watch folder apps/ in the gitops repo, forever


STEP 1 — "root" auto-syncs, creates the 2 factories
────────────────────────────────────────────────────
  root Application
      ↓ applies apps/services-appset.yaml
          → generates 12 Applications (4 services × 3 envs)
      ↓ applies apps/eso-appset.yaml
          → generates 1 ClusterSecretStore deployment per registered cluster
          (currently 1 — "eso-in-cluster" — since only the local cluster is
           registered with ArgoCD; a 2nd will appear automatically the moment
           prod is registered via `argocd cluster add`, no code change needed)


STEP 2 — each of the 12 Applications renders itself
────────────────────────────────────────────────────
  one Application, e.g. "api-dev"
      ↓ takes the shared blueprint:  charts/service/templates/*.yaml
      ↓ fills it in with:           environments/dev/api/values.yaml
      ↓ produces real objects, applies them into the "dev" namespace


STEP 3 — those objects reach out to AWS resources built elsewhere
────────────────────────────────────────────────────
  Deployment's image tag        ──▶  built + pushed by the snaPDF (app) repo's CI
  ServiceAccount's role-arn     ──▶  created by ProjectView-infra, "iam" module
  ScaledObject's queue URL      ──▶  created by ProjectView-infra, "sqs" module
  ExternalSecret's secret key   ──▶  exists in AWS Secrets Manager (referenced, not created, by either repo)
```

Each step only exists because the step above it created it — nothing skips a layer. **Step 0 is the only manual step in this entire system** — see "Automating the root bootstrap" below for how to remove even that.

### Automating the root bootstrap (removing Step 0's manual `kubectl apply`)

Today, standing up a brand-new cluster (e.g. prod) requires remembering to run `kubectl apply -f infra/bootstrap/root-app.yaml` by hand after Terraform finishes — everything after that point is automatic, but that one step isn't.

**The fix:** add a `kubernetes_manifest` resource to the `addons` Terraform module that applies `root-app.yaml`'s content directly, with `depends_on = [helm_release.argocd]` so it only runs once ArgoCD's CRDs actually exist. This makes `terragrunt apply` alone fully stand up a working GitOps loop — no manual step, ever, including for prod.

**The tradeoff:** this slightly blurs the project's clean rule ("Terraform owns the cluster, ArgoCD owns the apps") since Terraform would now be creating one ArgoCD-level object directly. This is a widely-accepted exception specifically for bootstrapping — not something to generalize to other ArgoCD objects. Not yet implemented as of 01/07/2026 — worth doing before the prod apply (Phase 4 Step 11), so that step doesn't require a manual follow-up.

### ResourceQuota per namespace via new `env-scoped` chart (02/07/2026)
Requirements doc (4.1) requires a ResourceQuota per namespace (non-optional, unlike NetworkPolicy). Rather than adding a `ResourceQuota` template into the existing `charts/service` chart — which would make one arbitrary service's Application "own" a namespace-wide object, a fragile hidden coupling — added a new generic chart, `charts/env-scoped`, for objects scoped to the whole environment/namespace rather than to one service. This mirrors the existing precedent of `ClusterSecretStore` getting its own `eso-appset.yaml` + `bootstrap/eso/` path instead of being bundled into `services-appset.yaml`.

Structure:
- `charts/env-scoped/templates/resourcequota.yaml` — the object defined once, gated behind `resourceQuota.enabled` (defaults `false` in the chart's own `values.yaml`, so a missing/incomplete values file fails safe instead of rendering a `ResourceQuota` with blank quantities)
- `environments/{dev,staging,production}/env-scoped-values.yaml` — one small values file per environment, sitting next to (not inside) each environment's per-service subfolders
- `apps/env-scoped-appset.yaml` — new ApplicationSet, same `git.directories` generator pattern as `services-appset.yaml` but one level shallower (`environments/dev`, `environments/staging`, `environments/production` themselves, not their service subfolders), so it generates exactly one Application per environment

Quota numbers were sized from each environment's actual configured worst case (HPA/KEDA max replicas × per-pod resource limits already set in each service's values.yaml), plus ~10-15% headroom for a rolling deployment briefly running old+new pod together:

| Env | requests (cpu/mem) | limits (cpu/mem) | pods | worst-case limits sum it's covering |
|---|---|---|---|---|
| dev | 1500m / 2048Mi | 3600m / 4608Mi | 16 | 3400m / 4352Mi |
| staging | 2000m / 2560Mi | 4800m / 6144Mi | 16 | 4400m / 5632Mi |
| production | 12000m / 12288Mi | 24000m / 24576Mi | 40 | 21000m / 21504Mi |

Note: dev + staging share one 2×t3.medium cluster, so their quotas summed together exceed that cluster's actual physical capacity — this is intentional and normal (the quota's job is capping each namespace relative to its own declared workload, not perfectly bin-packing shared node capacity; real node capacity is a separate, harder backstop that would leave pods `Pending` if actually exceeded). Production's numbers should be revisited once its real node group sizing is decided (infra issue #20, not yet applied).

Chart renders verified locally with `helm template` against all 3 values files before pushing. Not yet verified live — dev cluster is currently destroyed. Closes `snaPDF-gitops` issue #6.

This chart is meant to be the general home for any future namespace-scoped (not per-service) object — e.g. if `LimitRange` or `NetworkPolicy` gets picked up later, it should be added as another conditional template in this same chart with a new section in each environment's `env-scoped-values.yaml`, not a new chart+appset per object type.

---

## Secrets

### How secrets flow from AWS to pods

1. **AWS Secrets Manager** stores the actual secret values (DB password, JWT secret)
2. **ESO ClusterSecretStore** tells ESO how to connect to Secrets Manager (which IAM role to use)
3. **ExternalSecret** (one per service) tells ESO which secrets to pull and what to name the resulting K8s Secret
4. **Kubernetes Secret** is created by ESO — a native K8s secret in the same namespace as the pods
5. **Pod** receives the secrets as environment variables via `envFrom: - secretRef:`

The app code reads `os.environ["DB_HOST"]` — it has no idea secrets came from Secrets Manager. ESO is the bridge.

### Secret names in Secrets Manager

| Secret path | Contents | Used by |
|---|---|---|
| `snapdf/db-credentials` | JSON: `{"host":"...","username":"...","password":"..."}` | api, auth, both workers |
| `snapdf/jwt-secret` | Plain string — the JWT signing key | api, auth |

The DB credentials secret is stored as JSON so ESO can extract individual fields using the `property` field in the ExternalSecret `remoteRef`. Example: `property: host` extracts just the host value from the JSON into a K8s Secret key named `DB_HOST`.

---

## Phase 4 — GitOps (ArgoCD) — Completed

### What was built

The full GitOps flow is running. Here is what ArgoCD manages:

- **dev namespace** — api-dev, auth-dev, free-worker-dev, signed-worker-dev
- **staging namespace** — api-staging, auth-staging, free-worker-staging, signed-worker-staging

ArgoCD polls the snaPDF-gitops repo every 3 minutes and applies any changes automatically.

### End-to-end app flow (working as of 30/06/2026)

```
1. User visits /auth → signs up → JWT issued → redirected to /api?token=...
2. User uploads .docx → POST /api/convert → JWT validated
3. File uploaded to S3 (uploads/<job_id>.docx)
4. Job message sent to SQS (signed queue for authenticated users, free queue otherwise)
5. Worker pod picks up message → downloads .docx from S3 → converts to PDF via LibreOffice
6. PDF uploaded to S3 (outputs/<job_id>.pdf)
7. Job marked done in RDS
8. User polls GET /api/jobs/<job_id> → receives presigned S3 URL → downloads PDF
```

### Path-based ingress routing

Both services (api, auth) are served from a single ALB URL on different paths:
- `/api/*` → api pods
- `/auth/*` → auth pods

Nginx ingress uses `rewrite-target` to strip the prefix before forwarding to the pod:
```yaml
nginx.ingress.kubernetes.io/rewrite-target: /$2
nginx.ingress.kubernetes.io/use-regex: "true"
path: /api(/|$)(.*)
pathType: ImplementationSpecific
```
Without rewrite, Flask would receive `/api/convert` and return 404 (it only knows `/convert`). The rewrite strips `/api` so Flask receives `/convert`.

**Important:** URLs hardcoded in the app's JavaScript (e.g. `fetch('/convert', ...)`) must use the full public path (`fetch('/api/convert', ...)`), not the Flask-internal path. The rewrite only happens server-side in nginx — the browser does not see it.

### Staging vs dev path conflict

Both dev and staging environments use the same nginx ingress controller. Since both use the same paths (`/api`, `/auth`), nginx can only route to one of them — whichever ingress object it sees first "wins." This caused the staging pod (running an old image) to intercept traffic meant for dev.

**Fix:** Keep staging image tags pinned to the same fixed SHA as dev, so even if staging intercepts traffic, the user sees the correct version. Long-term solution is host-based routing (different subdomains per env) which requires a real domain name.

---

## Bug Fixes

### Bug 1 — `required_version` invalid in Terragrunt `terraform` block
- **Error:** `Unsupported argument` on line 37 of `infra/terragrunt.hcl`
- **Cause:** In Terragrunt, the `terraform {}` block only accepts `source`, `extra_arguments`, and hooks. `required_version` is a Terraform-native keyword — it belongs in a `.tf` file, not in a Terragrunt config.
- **Fix:** Moved `required_version = ">= 1.10.0"` into the `generate "provider"` block contents so Terragrunt writes it into the auto-generated `provider.tf` inside each module.

### Bug 2 — `remote_state` had no `generate` block
- **Error:** `Found remote_state settings but no backend block in the Terraform code`
- **Cause:** The `remote_state` block tells Terragrunt where to store state, but without a `generate` attribute Terragrunt doesn't know where to write the backend config file. Each module was missing a `backend.tf`.
- **Fix:** Added `generate = { path = "backend.tf", if_exists = "overwrite" }` to the `remote_state` block. Terragrunt now auto-creates `backend.tf` in every module before running.

### Bug 3 — Helm provider not declared in `required_providers`
- **Error:** `Blocks of type "kubernetes" are not expected here` in `addons/main.tf`
- **Cause:** The Helm provider uses a `kubernetes {}` nested block for cluster authentication. Without declaring the Helm provider in `required_providers`, Terraform doesn't know its schema and rejects the block.
- **Fix:** Created `infra/modules/addons/versions.tf` declaring `hashicorp/helm ~> 3.0` (bumped from `~> 2.0` after the lock file showed version 3.2.0 was cached).

### Bug 4 — Helm provider version constraint conflicted with lock file
- **Error:** `locked provider hashicorp/helm 3.2.0 does not match configured version constraint ~> 2.0`
- **Cause:** The lock file (created by a previous Terraform init) had Helm provider 3.2.0, but `versions.tf` said `~> 2.0`. These are incompatible — Terraform refuses to run.
- **Fix:** Updated the constraint to `~> 3.0` to match what was already locked.

### Bug 6 — Helm provider v3 breaking changes
- **Error:** Multiple errors: `kubernetes` block unsupported, `set {}` blocks unsupported, cluster unreachable
- **Cause:** The Helm provider jumped from 2.x to 3.x in the cached lock file. Version 3 removed the `kubernetes {}` nested block inside `provider "helm"` and changed `set {}` blocks to list syntax. Switching to a separate `kubernetes` provider also didn't work because Helm v3 doesn't automatically inherit it.
- **Fix:** Pinned the Helm provider back to `~> 2.0` in `versions.tf`, restored the `kubernetes {}` block inside `provider "helm"`, and restored `set {}` block syntax. Ran `terragrunt init -upgrade` to downgrade from 3.2.0 to latest 2.x.

### Bug 7 — Helm releases timing out on t3.small nodes
- **Error:** `context deadline exceeded` on ArgoCD helm release
- **Cause:** Default Terraform Helm release timeout is 5 minutes. ArgoCD takes longer to fully start on small nodes.
- **Fix:** Added `wait = false` to all helm releases so Terraform submits the install and doesn't wait for pod readiness. We verify pods manually with `kubectl get pods -A` afterward.

### Bug 8 — Namespaces stuck in Terminating state
- **Error:** `unable to create new content in namespace argocd because it is being terminated`
- **Cause:** Kubernetes namespace deletion is not instant — it waits for all resources and finalizers to clean up. KEDA registers a custom API group (`external.metrics.k8s.io/v1beta1`) and when KEDA was deleted mid-install, the stale API registration blocked namespace deletion indefinitely.
- **Fix:** Used `kubectl replace --raw /api/v1/namespaces/<name>/finalize` to forcefully clear the finalizers from all three stuck namespaces (argocd, external-secrets, keda).

### Bug 9 — ALB controller missing EC2 permissions
- **Error:** `not authorized to perform: ec2:CreateSecurityGroup` on the ALB controller role
- **Cause:** Our custom IAM policy for the ALB controller only had `ec2:Describe*` (read-only). The controller also needs to create/delete security groups, authorize ingress/egress rules, and manage tags — all write operations we hadn't included.
- **Fix:** Replaced the minimal policy with the full official AWS Load Balancer Controller policy, which includes all required EC2, ELB, WAF, Shield, and ACM permissions. Then re-applied the IAM module with `terragrunt apply`.

### Bug 10 — Load balancer created as internal instead of internet-facing
- **Error:** Browser couldn't reach the app — `ERR_CONNECTION_TIMED_OUT`
- **Cause:** When you create a `type: LoadBalancer` service in EKS, the ALB controller defaults to `internal` scheme — meaning the load balancer is only reachable from inside the VPC, not from the internet.
- **Fix:** Added the annotation `service.beta.kubernetes.io/aws-load-balancer-scheme=internet-facing` to the service. Annotations are key-value metadata on Kubernetes resources that tools like the ALB controller read to change their behavior. The public subnets already had the `kubernetes.io/role/elb=1` tag so the controller knew which subnets to use for the public-facing LB.
- **Lesson:** Always annotate LoadBalancer services with the scheme explicitly — never rely on the default.

### Bug 11 — Pod using node IAM role instead of worker role (AccessDenied on S3)
- **Error:** `AccessDenied` when calling `s3:PutObject` — the assumed role was `snapdf-dev-nodes-eks-node-group-...` (the EC2 node role), not the worker role.
- **Cause:** When a pod runs without a ServiceAccount annotated with an IAM role, it falls back to the IAM role of the EC2 node it's running on. The node role only has permissions to join the cluster and pull images — no S3 or SQS access.
- **Fix:** Created a Kubernetes ServiceAccount (`pdf-worker-sa`) in the `dev` namespace annotated with `eks.amazonaws.com/role-arn: arn:aws:iam::086241318869:role/snapdf-dev-worker`. Updated the Deployment to use `serviceAccountName: pdf-worker-sa`. AWS then injects temporary credentials for the worker role into the pod via a projected token volume.
- **Lesson:** Always attach a ServiceAccount with the correct IAM role to every pod that needs AWS access. Never rely on the node role for application-level permissions — it violates least-privilege and gives every pod on that node the same access.

### Bug 12 — Wrong ServiceAccount name in IAM trust policy
- **Error:** `AccessDenied` on `sts:AssumeRoleWithWebIdentity`
- **Cause:** The IAM trust policy for the worker role was locked to `system:serviceaccount:default:worker`. Our ServiceAccount was named `pdf-worker-sa` in the `dev` namespace. The two didn't match so AWS refused to issue credentials.
- **Fix:** Updated the trust policy in `infra/modules/iam/main.tf` to `system:serviceaccount:dev:pdf-worker-sa` and re-applied the IAM module.
- **Lesson:** The trust policy on an IRSA role must exactly match the namespace AND name of the Kubernetes ServiceAccount. One character off = access denied.

### Bug 13 — `terragrunt run-all destroy` fails repeatedly on VPC deletion
- **Root causes (multiple, each required a separate fix):**
  1. **ENIs blocking subnet deletion** — The ALB controller and ArgoCD create AWS load balancers when services are deployed. When the EKS cluster is destroyed, those load balancers and their network interfaces (ENIs) remain in the VPC subnets. Terraform cannot delete subnets with active ENIs.
  2. **Leftover security groups** — EKS and the ALB controller create security groups inside the VPC that Terraform doesn't manage. These block VPC deletion.
  3. **DNS failure mid-destroy** — After a long destroy run (~20 min), Windows temporarily loses DNS resolution at the VPC deletion stage, causing `no such host` errors on EC2 API calls. This also left stuck state locks.
  4. **State lock stuck after crash** — When DNS fails, Terraform cannot release the state lock it holds, so the next run errors with "state already locked".
- **Fix:** Replaced the manual `terragrunt run-all destroy` command with `destroy.ps1` which runs these steps before Terraform touches the VPC:
  1. Delete all Kubernetes services and ingresses in every namespace (triggers ALB controller to delete AWS load balancers)
  2. Poll until all load balancers in the VPC are actually gone
  3. Detach and delete all ENIs in the VPC
  4. Delete all non-default security groups in the VPC
  5. Delete all subnets manually
  6. Run `terragrunt run-all destroy --lock=false` (`--lock=false` prevents stuck locks if DNS fails again)
- **Usage:** Always use `.\destroy.ps1` from the repo root instead of running terragrunt directly. Pass `-SkipK8s` if the cluster is already gone.

### Bug 13 — Missing `sqs:SendMessage` permission
- **Error:** `AccessDenied` on `sqs:SendMessage`
- **Cause:** The worker IAM policy had `sqs:ReceiveMessage`, `sqs:DeleteMessage`, and `sqs:GetQueueAttributes` but we forgot `sqs:SendMessage` — the permission the API needs to put messages into the queue.
- **Fix:** Added `sqs:SendMessage` to the worker policy in `infra/modules/iam/main.tf` and re-applied.
- **Lesson:** IAM permissions are discovered one at a time as each line of code runs. Always think through every AWS API call the app makes and map it to a permission.

### Bug 14 — RDS rejecting non-SSL connections
- **Error:** `FATAL: no pg_hba.conf entry for host ... no encryption`
- **Cause:** AWS RDS PostgreSQL enforces SSL connections by default. psycopg2 was connecting without SSL — RDS rejected it at the TCP handshake level before even checking the password.
- **Fix:** Added `sslmode="require"` to the `psycopg2.connect()` call in both `app.py` and `worker.py`.
- **Lesson:** Always use SSL when connecting to RDS. In production this would be enforced by a parameter group — in code, always pass `sslmode="require"`.

### Bug 15 — Wrong DB password (missing character)
- **Error:** `FATAL: password authentication failed for user "dbadmin"`
- **Cause:** When we copied the RDS password from Secrets Manager output, the last character (`t`) was cut off. The password in `deploy-dev.yaml` was `...Y(` instead of `...Y(t`.
- **Fix:** Re-fetched the password from Secrets Manager, spotted the missing character, updated `deploy-dev.yaml`.
- **Lesson:** This is exactly why we use External Secrets Operator — ESO pulls the latest secret value from Secrets Manager automatically. Hardcoding secrets in YAML means any rotation or typo breaks the app and requires a manual fix.

### Bug 16 — EKS node group stuck in CREATE_FAILED (Free Tier restriction)
- **Error:** `InvalidParameterCombination: Instance type t3.medium is not eligible for the Free Tier`
- **Cause:** AWS billing-level restriction — not an IAM or quota issue. The account had a Free Tier restriction that blocked Auto Scaling Groups from launching non-Free-Tier instance types. t3.micro and t3.small are Free Tier eligible; t3.medium is not.
- **Fix:** Upgraded the AWS account plan to remove the Free Tier instance restriction. Also had to manually delete the stuck CREATE_FAILED node group via `aws eks delete-nodegroup` before Terraform could recreate it.
- **Lesson:** Free Tier restrictions operate at the billing level, invisible to IAM/SCP policies. A quota increase does not help — the account plan itself must be upgraded.

### Bug 17 — ESO not extracting individual fields from JSON secret
- **Error:** `key host does not exist in secret snapdf/db-credentials`
- **Cause:** Two problems combined. First, the secret in Secrets Manager was stored as invalid JSON (`{host:...,username:...}` — unquoted keys). ESO requires valid JSON to use the `property` field. Second, the Helm chart ExternalSecret template didn't include the `property` field at all — it was defined in values but never rendered.
- **Fix:** (1) Updated the secret in Secrets Manager to valid JSON `{"host":"...","username":"...","password":"..."}` using Bash (PowerShell stripped the quotes). (2) Added `{{- if .property }}` conditional rendering to the ExternalSecret template.
- **Lesson:** ESO's `property` field only works with valid JSON. PowerShell's argument parsing strips quotes from JSON strings passed to the AWS CLI — always use Bash for this.

### Bug 18 — Pods not receiving secrets from ESO (missing envFrom)
- **Error:** `KeyError: 'DB_HOST'` — Python could not find the env var despite ESO creating the Secret
- **Cause:** The Helm chart deployment template had no `envFrom` block. ESO was creating the Kubernetes Secret correctly, but nothing mounted it into the pod as environment variables.
- **Fix:** Added `envFrom: - secretRef:` to the deployment template, conditional on `eso.enabled` and secrets being defined.
- **Lesson:** ESO creates a Kubernetes Secret — it doesn't automatically inject it into pods. The pod spec must explicitly reference the secret via `envFrom` or `env.valueFrom.secretKeyRef`.

### Bug 19 — IRSA trust policy service account name mismatch
- **Error:** `AccessDenied: Not authorized to perform: sts:AssumeRoleWithWebIdentity`
- **Cause:** The IAM trust policy for the worker role referenced `pdf-worker-sa` (the old service account name from Phase 2). The Helm chart creates service accounts named `free-worker-dev-sa` and `signed-worker-dev-sa`. The names didn't match so AWS refused to issue credentials.
- **Fix:** Updated the trust policy to use `StringLike` with a wildcard: `system:serviceaccount:dev:*-worker-*`. This covers all current and future worker service account names without needing exact matches.
- **Lesson:** IRSA requires an exact match between the trust policy's service account reference and the actual K8s ServiceAccount name + namespace. Use `StringLike` with wildcards when service account names follow a pattern.

### Bug 20 — Ingress returning 404 (missing rewrite-target)
- **Error:** Visiting `/api` in browser returned Flask 404
- **Cause:** The Nginx ingress had no `rewrite-target` annotation. Nginx forwarded the full path `/api` to Flask. Flask only knows the route `/` — it has no route called `/api` — so it returned 404.
- **Fix:** Added `nginx.ingress.kubernetes.io/rewrite-target: /$2` with `use-regex: true` and `pathType: ImplementationSpecific`, with path pattern `/api(/|$)(.*)`. Nginx now strips the `/api` prefix before forwarding to Flask.
- **Lesson:** When using path-based routing (one ALB serving multiple services at `/api`, `/auth`, etc.), the ingress must strip the prefix before the request reaches the app. The app only knows its own internal routes.

### Bug 21 — JavaScript fetch calls used wrong paths after ingress path routing
- **Error:** Clicking "Convert" caused the page to reload (form submitted as GET) instead of uploading
- **Cause:** The Flask page served JavaScript that called `fetch('/convert', ...)` and `fetch('/jobs/' + jobId)` — absolute paths without the `/api` prefix. The browser sent these to the ALB as `/convert` and `/jobs/...` which didn't match any ingress rule (404). When `fetch` got a 404 HTML response and tried to parse it as JSON, it threw an exception — and because there was no try/catch, the event listener crashed silently, leaving the form to submit normally (page reload).
- **Fix:** Changed all fetch calls in the Flask HTML template to use the full public paths: `/api/convert` and `/api/jobs/...`. Also changed HTML form `action` attributes in auth to use `/auth/login` and `/auth/signup`.
- **Lesson:** After adding an ingress prefix, update every URL in the app's frontend code. The rewrite only happens inside nginx — the browser always sees the full public path.

### Bug 22 — Curly quotes in Python source files breaking JavaScript
- **Error:** JS syntax error in browser — convert button did nothing; form submitted as page reload
- **Cause:** Python source files (app.py, main.py) had curly/smart quotes (`"` `"` `'` `'`) and a UTF-8 BOM, likely introduced by a text editor or copy-paste. Python itself was fine (curly quotes are valid inside string literals), but the quotes were embedded in JavaScript code inside the HTML template strings. Browsers parse JS strictly — curly single quotes are not valid string delimiters in JavaScript, causing a SyntaxError that silently killed the entire script block.
- **Fix:** Wrote a Python script to replace all curly quotes with straight ASCII equivalents, removed the BOM, and replaced any broken f-strings that had their `?` characters eaten by the replacement.
- **Lesson:** Always use ASCII straight quotes in code. Smart quotes look identical in most editors but break parsers. Add `<meta charset="UTF-8">` to all HTML pages to ensure the browser interprets the encoding correctly.

### Bug 23 — ArgoCD Services missing after being deployed (Terraform state showed no drift)
- **Error:** Every ArgoCD Application showed `SYNC: Unknown`, `root` app was `Degraded`. Digging into the `root` app's status showed: `dial tcp: lookup argocd-repo-server on 172.20.0.10:53: no such host`.
- **Cause:** `kubectl get svc -n argocd` returned zero Services, even though all 7 ArgoCD pods (server, repo-server, redis, dex, controller, applicationset-controller, notifications-controller) were `Running`. A Kubernetes Service is what gives a pod a stable DNS name (`argocd-repo-server`) — without it, other pods can't find it, hence the DNS lookup failure. The Helm release itself (`helm list -n argocd` → `argocd`, `deployed`, revision 1) looked completely healthy — Terraform's `helm_release` resource only tracks the release metadata (chart, version, values), not the individual Kubernetes objects (Services, Deployments) that the chart creates. So the 5 Services had been deleted from the cluster by something outside Terraform/Helm's knowledge, but neither Terraform nor Helm had any record of it — `terraform plan` showed **zero drift** because it never compares live cluster objects, only its own release bookkeeping.
- **Fix:** Since Terraform can't detect or repair drift inside a Helm release's child objects, the fix was to force Terraform to fully replace the resource: `terragrunt apply -replace=helm_release.argocd` (run from `infra/environments/dev/addons`). This runs `helm uninstall` (removing all stale/broken objects) followed by a fresh `helm install`, recreating all 5 Services correctly. Confirmed fixed: `kubectl get svc -n argocd` showed all 5 Services back, and all ArgoCD Applications returned to `Synced`/`Healthy` within a minute.
- **Why this didn't touch the app:** `helm_release.argocd` only manages resources in the `argocd` namespace (the control plane). The actual app Deployments in `dev`/`staging` namespaces are plain Kubernetes objects that ArgoCD had already applied in a previous sync — they kept running the whole time, completely independent of whether ArgoCD's own pods were healthy.
- **Why the CRDs survived:** `helm uninstall` printed a warning that it kept `applications.argoproj.io`, `applicationsets.argoproj.io`, and `appprojects.argoproj.io` CRDs "due to the resource policy" — Helm never deletes CRDs on uninstall by default, specifically to avoid deleting all custom resources (like every ArgoCD Application) that depend on them.
- **Lesson:** `terraform plan`/`apply` cannot detect drift in the individual Kubernetes objects that a `helm_release` resource creates — it only diffs release metadata (chart version, values). If something deletes a resource from inside a Helm release out-of-band, the only reliable Terraform-native fix is `-replace` on that `helm_release` resource, which forces a clean `helm uninstall` + `helm install`.

### Bug 24 — KEDA never actually authenticated to AWS (signed-worker stuck at 1 replica, ignoring 0-3 range)
- **Symptom:** `signed-worker-dev` always showed exactly 1 running pod, even with an empty queue and zero conversions requested — completely ignoring the ScaledObject's `minReplicaCount: 0`.
- **Root cause, part 1 (Terraform → wrong values path):** `infra/modules/addons/main.tf` set the keda `helm_release` with:
  ```
  set { name = "serviceAccount.operator.annotations.eks\\.amazonaws\\.com/role-arn" ... }
  ```
  This key doesn't exist anywhere in the actual `kedacore/keda` chart schema (confirmed by pulling the chart source: `helm pull kedacore/keda --version 2.13.1 --untar`). Helm's `set` never validates against a schema — an unrecognized key is silently accepted and simply never read by any template, so it does nothing. The chart's real path for AWS IRSA (confirmed in `templates/serviceaccount.yaml`) is `podIdentity.aws.irsa.enabled: true` + `podIdentity.aws.irsa.roleArn: <arn>`. Result: the `keda-operator` ServiceAccount had zero IAM role annotation since the day this addon was first installed — nobody noticed because KEDA's own aws-sqs-queue scaler failure just quietly kept the Deployment at whatever `replicas` count was already there (1), instead of erroring loudly in a way that showed up anywhere but `kubectl describe scaledobject` events.
- **Root cause, part 2 (missing `identityOwner`):** Even with IAM fixed, `charts/service/templates/scaledobject.yaml` (in `snaPDF-gitops`) never set `identityOwner` on the trigger. KEDA's `aws-sqs-queue` scaler defaults to `identityOwner: pod`, meaning it authenticates using the *scaled workload's own* pod identity (`signed-worker-dev-sa`, the broad `snapdf-dev-worker` role) — not the deliberately narrow, read-only `snapdf-dev-keda` role your IAM module created specifically for queue-depth metrics. Added `identityOwner: operator` to the trigger metadata so KEDA explicitly uses the operator's own identity — matching the original least-privilege design (a scoped role for metrics, a separate broader role for actual job processing).
- **Root cause, part 3 (stale pod, easy to miss):** After fixing both of the above, the ScaledObject still failed — this time with `AccessDenied ... assumed-role/snapdf-dev-nodes-eks-node-group-...` (the raw EC2 node role, not KEDA's IRSA role at all). IRSA works via a mutating admission webhook that injects `AWS_ROLE_ARN` + a projected token volume into a pod **only at pod-creation time**. The `keda-operator` pod had been running for 12 hours, since before its ServiceAccount had any role annotation — so it never got those credentials injected, and its AWS SDK silently fell back to the EC2 instance's own node role (which has no SQS permissions at all). Fix: `kubectl rollout restart deployment keda-operator -n keda` to force a fresh pod, which then correctly picked up `AWS_ROLE_ARN=arn:aws:iam::086241318869:role/snapdf-dev-keda` in its container spec.
- **Fix summary:**
  1. `infra/modules/addons/main.tf` — replaced the dead `serviceAccount.operator.annotations...` set block with `podIdentity.aws.irsa.enabled` + `podIdentity.aws.irsa.roleArn`, applied via `terragrunt apply` (clean in-place `helm upgrade`, confirmed via `terragrunt plan` first — 0 to add, 1 to change, 0 to destroy).
  2. `snaPDF-gitops/charts/service/templates/scaledobject.yaml` — added `identityOwner: operator`, committed and pushed; ArgoCD auto-synced within its normal 3-minute poll window.
  3. Restarted the `keda-operator` Deployment so its pod picked up the newly-annotated ServiceAccount.
- **Verified:** `kubectl describe scaledobject signed-worker-dev -n dev` shows `Ready: True`, `Active: False`, and a `KEDAScaleTargetDeactivated ... from 1 to 0` event — `signed-worker-dev` is now genuinely absent from `kubectl get pods -n dev` at idle, scaling 0→N only when the signed SQS queue actually has messages.
- **Lesson:** Helm `set` values are not type- or schema-checked — a typo'd or wrong path fails silently and looks identical to "working" until you check the actual rendered object on the cluster. And any IRSA fix that only changes a ServiceAccount's annotations requires restarting the pods that use it — the injection only happens once, at pod creation.

### Bug 25 — worker IAM role's Terraform file didn't match its live trust policy (silent revert risk)
- **Discovery context:** found while tracing IAM/IRSA for learning purposes, not from an active failure — the app was working fine at the time.
- **Symptom:** `infra/modules/iam/main.tf`'s `aws_iam_role "worker"` still had the narrow, single-SA trust policy from before Bug 19 (`StringEquals: system:serviceaccount:dev:pdf-worker-sa` — a service account name that hasn't existed since the Phase 3 microservice split). But `aws iam get-role --role-name snapdf-dev-worker` showed the *live* role already had the correct, wider `StringLike` wildcard policy (`dev:*-worker-*`, `staging:*-worker-*`, plus explicit `api-dev-sa`/`auth-dev-sa` entries) — i.e. Bug 19's fix.
- **Cause:** Bug 19 was fixed directly against the live role at some point (or from a version of this file that was never committed), but the fix never made it back into `main.tf`. Terraform's state and the live IAM role agreed with each other, but the file (and therefore git) disagreed with both.
- **Why this was dangerous, not just untidy:** if `terragrunt apply` (or `run-all apply`) is ever re-run on the `iam` module — e.g. a full environment rebuild — Terraform would treat the file as the source of truth and silently **revert the live trust policy back to the old, narrow one**, breaking IRSA for `api-dev-sa`, `auth-dev-sa`, and both workers all over again, reproducing Bug 19 with no code change being the trigger.
- **Fix:** Updated `main.tf`'s `worker` role `assume_role_policy` to use `StringLike` with the exact same wildcard/explicit-SA list already live in AWS. Verified with `terragrunt plan` → `No changes. Your infrastructure matches the configuration.` — confirms the fix only aligned the file with reality; no actual AWS resource was touched.
- **Lesson:** a `terraform plan` showing "no changes" only proves the *file* and *live resource* agree at that moment — it says nothing about whether a fix that happened outside of a normal `apply` (console edit, one-off CLI command, or an uncommitted local change) ever made it into git. Any manual/live fix to Terraform-managed infrastructure must be mirrored back into the `.tf` file in the same sitting, or it becomes a landmine for the next `apply`.

### Bug 26 — orphaned NLB + target group from pre-rename manual test deployment
- **Discovery context:** found while explaining `deploy-dev.yaml` during the learning session — not an active failure, the app was working fine.
- **Symptom:** `aws elbv2 describe-load-balancers` showed 3 NLBs, not the expected 2 (Nginx + ArgoCD). The third, `k8s-dev-pdfapi-e95f7c3ea2`, was tagged `elbv2.k8s.aws/cluster: projectview-dev` — a cluster name that hasn't existed since the project rename (ProjectView → snaPDF, 29/06/2026); the current cluster is `snapdf-dev`.
- **Cause:** `deploy-dev.yaml` (committed in `67c8a61`, Phase 2) was a raw, hand-written manifest — 3 Deployments + one `pdf-api` Service of `type: LoadBalancer` — applied directly via `kubectl` on the old `projectview-dev` cluster, before Helm/ArgoCD existed, to smoke-test the app manually. When that old cluster was later renamed/rebuilt as `snapdf-dev`, the Kubernetes-side Service disappeared with it, but the AWS-side NLB + target group it had created were never cleaned up — nothing manages them anymore, since their owning cluster is gone and Terraform never created them in the first place.
- **Fix:** deleted directly via AWS CLI (`aws elbv2 delete-load-balancer`, then `aws elbv2 delete-target-group` for the now-unattached target group) — not via Terraform, since no Terraform state ever tracked this resource. Verified only the 2 legitimate NLBs (`ingress-nginx-controller`, `argocd-server`) remain. Also removed `deploy-dev.yaml` from the repo entirely (superseded by Helm/ArgoCD since Phase 3, and it additionally had a plaintext DB password + API key committed in its history — a live example of the exact problem ESO/Secrets Manager solves, even though that specific old RDS instance no longer exists).
- **Lesson:** any raw `kubectl apply` of a `type: LoadBalancer` Service creates a real, billed AWS resource that outlives the Kubernetes object if the *cluster itself* is later destroyed/renamed out from under it — Terraform only tracks resources it created, so anything applied manually falls outside its visibility permanently unless someone notices and cleans it up by hand.

### Bug 27 — ESO Services missing (same root cause as Bug 23, recurred for a different Helm release)
- **Discovery context:** found while force-syncing all 4 dev Applications after adding the ConfigMap template — `free-worker-dev`'s sync got stuck `OutOfSync`/`Running` indefinitely.
- **Symptom:** `status.operationState.message` showed `failed calling webhook "validate.externalsecret.external-secrets.io" ... service "external-secrets-webhook" not found`. `kubectl get svc -n external-secrets` returned nothing — same exact class of drift as Bug 23 (ArgoCD), just on the `eso` Helm release this time. The `external-secrets-cert-controller` pod was also stuck `0/1` Ready as a downstream symptom.
- **Cause:** identical to Bug 23 — `helm_release` only tracks release metadata, not the individual Kubernetes objects (Services) a chart creates. The ESO chart's Services had vanished from the cluster at some point with neither Terraform nor Helm ever noticing.
- **Fix:** same remedy as Bug 23 — `terragrunt apply -replace=helm_release.eso` from `infra/environments/dev/addons`. Confirmed via plan first (1 to add, 0 to change, 1 to destroy), then applied. All 3 ESO pods came back healthy (including `cert-controller`, previously stuck), `external-secrets-webhook` Service recreated, and `free-worker-dev`'s stuck sync completed immediately afterward.
- **Lesson:** this is the *second* time this exact class of drift has hit a different Helm-managed addon (ArgoCD, then ESO) in the same project. Worth periodically checking `kubectl get svc -A` against what each Terraform-managed Helm release is supposed to create, rather than waiting to notice only when something downstream breaks.

### ConfigMap added to the generic chart (01/07/2026)
Requirements doc (section 6) lists `ConfigMap` as one of the chart's minimum required resources — previously missing. Added `templates/configmap.yaml` (renders `.Values.env` into a real ConfigMap, only if non-empty), and switched `deployment.yaml`'s plain env vars from an inline `env:` block to `envFrom: - configMapRef:` — same pattern already used for the ExternalSecret's `envFrom: - secretRef:`. Verified live: all 4 dev services (`api-dev`, `auth-dev`, `free-worker-dev`, `signed-worker-dev`) got a matching `-config` ConfigMap, and pods correctly received their env vars through it after a rollout. Closes snaPDF-gitops issue #5.

### Namespace rename: `prod` → `production` (01/07/2026)
Requirements doc (4.2) names the prod namespace explicitly as `production`, not `prod`. Fixed by renaming `snaPDF-gitops/environments/prod/` → `environments/production/` — since `services-appset.yaml`'s ApplicationSet derives both the Application name and the target namespace directly from the folder path (`{{path[1]}}`), this alone changed the generated namespace with zero ApplicationSet code changes (just updated the generator's `directories.path` from `environments/prod/*` to `environments/production/*` to match).

**Hidden dependency found and fixed:** all 3 CI workflows (`ci-api.yml`, `ci-auth.yml`, `ci-worker.yml`) hardcode `ENV="prod"` when building the path `environments/$ENV/...` for the gitops handoff step. Left unfixed, every prod-branch pipeline run would have silently written to a `environments/prod/` folder that no longer existed (or worse, recreated it, causing two parallel, diverging environments). Updated all 3 to `ENV="production"`. The git branch itself (`prod`) was deliberately left unchanged — the spec only names the *namespace*, not the branch, and renaming a long-lived branch is a bigger, unrelated disruption.

Verified live: old `api-prod`/`auth-prod`/`free-worker-prod`/`signed-worker-prod` Applications were pruned automatically, replaced by `api-production`/`auth-production`/`free-worker-production`/`signed-worker-production`, each correctly targeting the `production` namespace and the `prod` AppProject. Closes snaPDF-gitops issue #2.

### Per-environment resource requests/limits added (01/07/2026)
Requirements doc (6) requires environment-specific overrides for resource limits/requests. Previously every service in every environment silently used the chart's one fixed default. Added a `resources:` block to all 12 environment values files, tiered dev < staging < production, and api/auth (lightweight Flask) < workers (heavier, run LibreOffice conversions):

| Env | api / auth | workers |
|---|---|---|
| dev | req 100m/128Mi, limit 300m/384Mi | req 150m/192Mi, limit 400m/512Mi |
| staging | req 150m/192Mi, limit 400m/512Mi | req 200m/256Mi, limit 500m/640Mi |
| production | req 250m/256Mi, limit 500m/512Mi | req 500m/512Mi, limit 1000m/1Gi |

Dev/staging numbers stay conservative since both share the same 2×t3.medium dev cluster alongside ~15 addon pods; production gets real headroom since it will run on its own separate cluster. Verified live — new dev pods picked up the correct values after rollout. Closes snaPDF-gitops issue #3.

**Related gaps noticed while doing this (not yet fixed, filed separately):** `environments/production/auth/values.yaml` has no `serviceAccount.roleArn` set at all (would deploy with zero IAM permissions), and `environments/production/signed-worker/values.yaml` has no `queueURL` set (would hit the exact same broken-KEDA-auth failure as Bug 24, since KEDA can't watch an empty queue URL). Both would only surface once prod is actually applied — worth checking before that happens.

### Production values files completed — except secrets (01/07/2026)
While adding resource limits, noticed all 4 `environments/production/*/values.yaml` files were effectively empty stubs: `env: {}`, `eso: enabled: true` with no `secrets:` list, `auth` missing `serviceAccount.roleArn` entirely, `signed-worker` missing `queueURL`. Left as-is, every prod pod would crash-loop immediately on the first required env var lookup (`os.environ["DB_HOST"]` etc.) — `env: {}` and empty `eso.secrets` together meant *both* guards in `deployment.yaml`'s `envFrom` (`gt (len .Values.env) 0` and `and .Values.eso.enabled (gt (len .Values.eso.secrets) 0)`) were false, so nothing at all would have been injected.

**Fixed now** (deterministic, doesn't depend on prod existing yet): `env:` vars (DB_NAME, SQS queue URLs, S3 bucket — all follow the same `${cluster_name}-*` naming Terraform will create), `auth`'s `serviceAccount.roleArn`, `signed-worker`'s `keda.queueURL`.

**Deliberately left blocked** (see snaPDF-infra issue #21): every service's `eso.secrets` list stays empty. `snapdf/db-credentials` and `snapdf/jwt-secret` are not Terraform-managed anywhere (confirmed — no `aws_secretsmanager_secret` resource for either path in any `.tf` file; both were created by hand, per Bugs 15/17). Reusing them for prod would be wrong two different ways: `db-credentials` holds *dev's* specific RDS host/password (prod gets its own separate RDS instance); `jwt-secret` is one shared signing key (reusing it means a dev-minted JWT would also be valid in prod — a security isolation issue, not just a data-correctness one).

**⚠️ Do not start the "apply prod" work (infra issue #20) without first resolving infra issue #21 (prod-specific secrets) — every prod pod will crash-loop without it.**

### Bug 28 — orphaned EC2 instance blocked subnet deletion during destroy (02/07/2026)
- **Symptom:** during a routine `destroy.ps1` run, `module.vpc.aws_subnet.private[0]` sat "Still destroying..." for over 9 minutes — long past the point every other resource in that destroy run had finished, and long past what a subnet deletion normally takes.
- **Cause:** the `eks` module had already reported `Destroy complete! Resources: 40 destroyed` (including the managed node group) — but one EC2 instance (`t3.medium`, matching the node's instance type, with **no tags at all**) was still `running`, holding an ENI (`eni-01521c9f3e048ad25`) attached in that subnet. AWS subnets can't be deleted while any ENI is still attached — this is the same underlying issue as Bug 13, just from a different source (an orphaned ASG instance that outlived its own node group resource, rather than a load-balancer-created ENI).
- **Fix:** identified the stray instance via `aws ec2 describe-network-interfaces --filters "Name=subnet-id,Values=<subnet-id>"`, confirmed it was untagged and `running` (not something legitimate), and terminated it directly with `aws ec2 terminate-instances`. The subnet's `terraform destroy` retry loop picked up the change automatically once the instance actually finished shutting down (~1-2 min after termination) and completed normally — no Terraform state manipulation needed.
- **Lesson:** `destroy.ps1`'s pre-cleanup steps (delete LBs, delete ENIs, delete security groups, delete subnets) run once, before `terragrunt run-all destroy` starts — they don't re-check mid-destroy. If any single instance in the node group's ASG is slow to actually terminate (vs. the node group *resource* being marked destroyed by Terraform), it can silently outlive the cleanup steps and block subnet deletion later in the run. Worth checking `aws ec2 describe-network-interfaces` on any subnet stuck destroying for more than a minute or two, rather than assuming it'll resolve on its own.

### Bug 5 — IAM applied before SQS and S3
- **Error:** `Unknown variable` on `dependency.sqs.outputs.signed_queue_arn` in `dev/iam/terragrunt.hcl`
- **Cause:** The IAM module references SQS and S3 dependency outputs. When those modules haven't been applied yet, their state files don't exist in S3, so Terragrunt can't resolve the outputs.
- **Fix:** Apply SQS and S3 before IAM. The `mock_outputs` in the dependency blocks only work for `plan` and `validate`, not for `apply`.

### Bug 29 — dev's root bootstrap was never re-applied after today's destroy/recreate, and its DB password went stale (02/07/2026)
- **Symptom:** while verifying `gitops #4` (per-environment ingress hosts) against a live cluster, found dev's ArgoCD had **zero** Applications registered — identical to prod's situation, which had been (correctly) flagged as expected. Dev had no such reason to be empty; `kubectl get pods -n dev` / `-n staging` both returned nothing.
- **Cause:** when dev was destroyed and recreated earlier today (during the `terragrunt run-all apply` that also unexpectedly brought up prod), the one manual step — `kubectl apply -f infra/bootstrap/root-app.yaml` — was never re-run against the new dev cluster. Every gitops commit made today (ResourceQuota, prod secrets wiring, ingress hosts) was correctly sitting in git and validated locally with `helm template`, but none of it had actually reached a live pod.
- **Fix, part 1:** applied `infra/bootstrap/root-app.yaml` to dev. All `-dev` and `-staging` Applications came up `Synced/Healthy` within ~20s.
- **Second bug surfaced immediately:** `free-worker-dev` and `free-worker-staging` crash-looped with `psycopg2.OperationalError: ... password authentication failed for user "dbadmin"`. Cause: dev's RDS instance was also destroyed and recreated today, and `manage_master_user_password = true` makes AWS generate a **brand-new** random password every time the instance is created — it does not persist across a destroy/recreate cycle. The manually-maintained consolidated secret `snapdf/db-credentials` (which ESO actually syncs into the cluster) still held the *old* password from before the destroy.
- **Fix, part 2:** re-ran the same repackaging steps used for `infra #21`'s prod secrets — pulled the current password from RDS's own AWS-managed secret (via the `rds` module's `db_master_user_secret_arn` output) and wrote it into `snapdf/db-credentials` with `aws secretsmanager put-secret-value` (never printed to any terminal output). Forced ESO to pick it up immediately with `kubectl annotate externalsecret <name> force-sync=$(date +%s) --overwrite` on all 4 dev + 4 staging ExternalSecrets (otherwise it would've waited for the 1h `refreshInterval`), then `kubectl rollout restart deployment free-worker-dev/-staging`.
- **Missed on the first pass, caught via manual UI testing:** only restarted `free-worker` initially, since it was the only one crash-looping (it connects to Postgres at startup, so a bad password fails immediately and visibly). `api-dev`/`auth-dev` stayed `Running` the whole time — they only connect to the DB lazily, per-request — so they silently kept using the stale password for every real request (`/login` → `500`, `/jobs/<id>` status checks → `500`) until manual testing surfaced it (login going to "Internal Server Error", free-tier status stuck on "Checking status..."). Fixed by also restarting `api-dev`/`auth-dev`/`api-staging`/`auth-staging`. **Lesson: a Deployment showing `Running` only means the process didn't crash — it says nothing about whether every code path inside it still works.** After rotating any credential a running service depends on, restart every deployment that uses it, not just the ones already visibly broken.
- **Lesson:** any `manage_master_user_password = true` RDS instance needs its downstream consolidated secret (`snapdf/db-credentials`, `snapdf-prod/db-credentials`) treated as **derived, not durable** — it must be regenerated from the RDS-managed secret after every destroy/recreate of that specific RDS instance, the same way this was done fresh for prod in `infra #21`. Worth automating this relationship in Terraform eventually (e.g. a script or a small `aws_secretsmanager_secret_version` wired directly to the RDS module's output) rather than a manual step that's easy to forget.
- **Verified live:** `curl -H "Host: dev.snapdf.bond" http://dev.snapdf.bond/api/` → `200`; the same with an unrelated/wrong `Host` header on the identical load balancer → `404`, confirming host-based routing (not just path matching) is genuinely working. Closes `snaPDF-gitops` issue #4.
- **New gap found and filed separately (`snaPDF-infra #23`):** dev's ArgoCD, once bootstrapped, also generates `-production` Applications (`Unknown/Unknown` status, harmless only because the destination is still the placeholder `<prod-cluster-endpoint>` string) — because `services-appset.yaml` and `env-scoped-appset.yaml` aren't cluster-scoped and both clusters' root Applications point at the same shared `apps/` folder. This must be fixed before prod's own root bootstrap is applied, or prod's ArgoCD would symmetrically try to create dev/staging resources inside the prod cluster itself.

### Infra #23 fix — split `apps/` into `apps/dev` and `apps/prod` (02/07/2026)
Since ArgoCD's `root` Application can only point at one path, and both clusters' `root` pointed at the same shared `apps/` folder, each cluster's ArgoCD was reading generator rules meant for the *other* cluster too. Fixed by splitting every file in `apps/` into `apps/dev/*` and `apps/prod/*`, each with a single generator block (no more per-file dev-vs-prod branching), and pointing each cluster's `root-app.yaml` at only its own folder. As a side benefit, the `<prod-cluster-endpoint>` placeholder disappeared entirely — every destination is now simply `https://kubernetes.default.svc`, correctly resolving to "whichever cluster this ArgoCD actually runs on" since each cluster now only ever manages itself.

**Verified live:** re-applied dev's `root` (picked up `apps/dev`) — all `-dev`/`-staging` Applications stayed `Synced/Healthy` with zero disruption, and the previously-present `-production` (`Unknown/Unknown`) entries vanished entirely. Applied prod's `root` for the very first time (`root-app-prod.yaml`, `apps/prod`) — generated only `-production` Applications, confirming the fix works symmetrically in both directions. Closes `snaPDF-infra #23`.

### Bug 30 — prod's node group too small, and worker IAM trust policy hardcoded to dev/staging (02/07/2026)
Once prod's root bootstrap actually deployed real app pods, two more problems surfaced (previously invisible since prod had zero Applications until today):

- **Symptom 1:** all 5 prod app pods stuck `Pending` — `0/2 nodes are available: 2 Too many pods`. **Cause:** prod's node group was still on `t3.small` (`infra/environments/prod/env.hcl`), which only allows 11 pods per node — already fully consumed by addon pods (ArgoCD, ALB controller, ESO, KEDA, Nginx, CoreDNS, etc.) before any app pod could even be scheduled. Dev hit this exact issue earlier in the project and was upgraded to `t3.medium` (commit `260e4d9`); prod was never given the same fix. **Fix:** changed `node_instance_type` to `t3.medium` for prod, `terragrunt apply` on `environments/prod/eks` (1 node group replaced, 0 data loss — RDS/S3/secrets untouched).
- **Symptom 2:** once nodes had room, `free-worker-production` still crash-looped: `AccessDenied ... Not authorized to perform sts:AssumeRoleWithWebIdentity`. **Cause:** `infra/modules/iam`'s `worker` role trust policy hardcoded `system:serviceaccount:dev:*` / `staging:*` patterns unconditionally — this module is shared between dev's and prod's `iam` terragrunt configs, but nobody had parameterized it by environment, so prod's worker role trusted dev/staging service accounts and nothing in `production` at all. `api-production`/`auth-production` looked fine only because they hadn't touched AWS yet (lazy connections); `free-worker-production` fails at startup, surfacing it immediately. **Fix:** added a new `app_namespaces` variable, generate the trust policy's `StringLike` list via a `for` loop over it instead of hardcoding — dev passes `["dev", "staging"]` (verified byte-identical output via `terraform plan` → `No changes`), prod passes `["production"]`.
- **Lesson:** because prod's root bootstrap was deliberately held back all session (correctly, pending `infra #21`/`#23`), prod-specific infra bugs like this one had no way to surface until the exact moment it finally went live — worth remembering that "nothing has deployed into prod yet" doesn't mean "prod's config is known-good," only "untested."
- **Verified live:** all 5 prod app pods `Running`, `curl http://prod.snapdf.bond/api/` and `/auth/` both `200`, KEDA `ScaledObject` for `signed-worker-production` shows `READY: True`.

### Bug 31 — staging silently shared every AWS resource with dev (02/07/2026)
Discovered while manually testing signed-PDF conversion through staging: KEDA scaled up `signed-worker-dev` for a job actually submitted through staging, and separately, `signed-worker-staging` stayed active far longer than expected. Root cause: staging was never given its own AWS resources at all — checked every AWS-facing value in `environments/staging/*/values.yaml` against dev's and found identical values everywhere except the already-fixed ingress hosts:

| Resource | Staging's config | Real state |
|---|---|---|
| SQS queues | `snapdf-dev-signed`/`free` | literally dev's queues — both `signed-worker-dev` and `signed-worker-staging` independently watch the same queue depth, so a single message could trigger both to scale up, racing to consume it |
| S3 bucket | `snapdf-dev-pdfs-...` | staging's converted PDFs land in dev's bucket |
| Database | `snapdf/db-credentials`, `DB_NAME: snapdf` | staging and dev share the literal same database and tables — not just the same RDS instance |
| JWT secret | `snapdf/jwt-secret` | a token issued by dev's auth is valid on staging's auth and vice versa |
| `signed-worker` `cooldownPeriod` | never set | defaults to the chart's `300` (5 min), unlike dev's explicit `15` — made staging's worker look "stuck" when it was just slow to deactivate |

**Fix, infra layer:** refactored `infra/modules/sqs` and `infra/modules/s3` from a single hardcoded resource per module to a `for_each` over a new `app_namespaces` variable (same pattern as `Bug 30`'s IAM fix) — dev now creates one signed+free queue pair and one bucket *per* namespace (`dev`, `staging`), prod still creates just one (kept as `app_namespaces = ["prod"]`, not `["production"]`, specifically to preserve the existing resource names already live in AWS — only the `iam` module's `app_namespaces` needs to literally match the k8s namespace name, since that's what feeds the trust-policy `StringLike` condition; `sqs`/`s3` naming is just a string with no such requirement). `infra/modules/iam`'s `signed_queue_arn`/`free_queue_arn`/`bucket_arn` variables became `_arns` lists, and the KEDA/worker policies' `Resource` blocks now list every queue/bucket the cluster's namespaces use instead of just one.

**Terraform refactoring detail worth remembering:** converting a plain resource to a `for_each`'d one changes its address in state (`aws_sqs_queue.signed` → `aws_sqs_queue.signed["dev"]`) even when the underlying AWS object (same name, same ARN) doesn't change at all — `terraform plan` showed this as a destroy+recreate of the *existing* dev/prod queues and bucket the first time. Fixed by running `terragrunt state mv 'aws_sqs_queue.signed' 'aws_sqs_queue.signed["dev"]'` (and the equivalent for `free`, and both `s3` resources, for both dev and prod) *before* applying — this just relabels the existing state entry to the new address without touching the real AWS resource, so the subsequent plan showed only genuinely new resources (`2 to add, 0 to change, 0 to destroy` for dev; `0 to add, 0 to change, 0 to destroy`, output-shape-only, for prod).

**Fix, secrets + database:** created `snapdf-staging/jwt-secret` (fresh, isolated key, same approach as prod's in `infra #21`) via AWS CLI. For the database, rather than a whole 3rd RDS instance (real ongoing cost, not justified for a demo), created a second **logical database** — `snapdf_staging` — on the *same* existing `snapdf-dev-rds` instance, run via `kubectl exec` into `api-dev`'s existing pod (`psycopg2`, already available, already has DB credentials mounted) since the RDS instance itself isn't reachable from outside the VPC. Postgres treats separate databases as fully isolated by default, and the app's own `init_db()` created a fresh, independent set of tables in it automatically — zero app code changes needed, only `DB_NAME` changed in staging's values files. `DB_HOST`/`DB_USER`/`DB_PASSWORD` stay pointed at the same `snapdf/db-credentials` secret, since it's genuinely the same server and admin user — only the database name differs now.

**Fix, gitops:** updated all 4 staging values files (`api`, `auth`, `signed-worker`, `free-worker`) to point at the new queues/bucket/secret/database, plus added the missing `cooldownPeriod: 15`.

**Verified live:** forced an ArgoCD refresh + `kubectl rollout restart` (ConfigMap/Secret changes don't auto-restart already-running pods), confirmed the new pods actually have the new env vars (not just that ArgoCD showed `Synced`), confirmed `free-worker-staging` connects successfully to `snapdf_staging` with zero restarts, and confirmed KEDA's `signed-worker-staging` ScaledObject shows `READY: True` watching `s0-aws-sqs-snapdf-staging-signed` specifically (not dev's queue).

### Bug 32 — `t3.medium`'s 17-pod ceiling was an IP address limit, not a CPU limit (02/07/2026)
While testing `signed-worker-dev`/`signed-worker-production` scaling, found pods stuck `Pending` with `0/2 nodes are available: 1 Insufficient cpu, 1 Too many pods` — two *different* nodes failing for two *different* reasons. Investigated the actual numbers rather than assuming: one node had spare CPU (24% used) but was at its hard `17`-pod ceiling; the other had spare pod slots (9/17) but only 80m CPU free. Neither node alone had both a free pod slot and enough CPU, even though the cluster as a whole was only ~73% utilized — a fragmentation problem, not a true capacity shortage.

**Root cause of the 17-pod ceiling specifically:** AWS's VPC CNI gives every pod its own real IP, borrowed one-at-a-time from the node's ENIs — `t3.medium` supports 3 ENIs × 6 IPs each, giving `(3×(6-1))+2 = 17`. This is a hard networking limit, unrelated to CPU/memory, and a bigger instance type doesn't reliably fix it: `t3.medium` → `t3.large` raises the IP ceiling (more ENIs) but leaves CPU exactly as constrained (both are 2 vCPU in the `t3` family).

**Fix:** enabled AWS VPC CNI "prefix delegation" (`ENABLE_PREFIX_DELEGATION=true`), which hands out IPs in blocks of 16 instead of one at a time — raises the ceiling from 17 to over 100 per node. Deliberately capped it back down to a chosen `maxPods: 35` (not the raw maximum) via kubelet config, sized for near-term headroom (Karpenter, Prometheus/Grafana) without over-provisioning. Also formally brought the VPC CNI under Terraform management for the first time (`cluster_addons = { vpc-cni = {...} }` in `infra/modules/eks`) — it had been running as an untracked AWS default the whole project.

**Implementation snag:** the `max-pods` override (`cloudinit_pre_nodeadm`, injecting a `nodeadm` `NodeConfig` document) silently produced zero effect on the first attempt — `terraform plan` showed the CNI addon being added but no launch template change at all. Cause: the `terraform-aws-modules/eks/aws` module only generates the newer `nodeadm`-format user data (required for `cloudinit_pre_nodeadm` to do anything) when `ami_type` is explicitly set to an `AL2023_*` value; left at its default (`null`), it silently falls back to the legacy `bootstrap.sh` format and ignores `cloudinit_pre_nodeadm` entirely, with no warning. Fixed by explicitly setting `ami_type = "AL2023_x86_64_STANDARD"` (matching what was already actually running) — after which `terraform plan` correctly showed the launch template gaining new `user_data` containing the `maxPods: 35` config.

**Applied to dev first, verified, then prod** (same module, same launch-template-replacement pattern as `Bug 30`'s node resize — AWS rolls each old node out one at a time as new ones join). **Verified live on both:** new nodes show `maxPods=35` (`kubectl get nodes -o jsonpath='...status.allocatable.pods'`), and on prod specifically, `signed-worker-production` — which had never successfully scheduled before this fix — came up `Running` immediately once room existed.

**One more gap caught during this test:** `signed-worker-production` took 5m50s to scale back down after finishing a job — same root cause as `Bug 31`'s staging fix, just never applied to production either: no `cooldownPeriod` set, defaulting to the chart's `300`. Added `cooldownPeriod: 15` to `environments/production/signed-worker/values.yaml`, matching dev and staging. Verified live via `kubectl get scaledobject signed-worker-production -o jsonpath='{.spec.cooldownPeriod}'` → `15`.

### Infra #18 — real ALB in front of Nginx, on dev and prod (02/07/2026)
Previously, Nginx's own `Service` was `type: LoadBalancer`, so Nginx created its own AWS NLB directly, while the separately-installed AWS Load Balancer Controller sat idle — the spec asks for both NGINX *and* real ALB integration as distinct deliverables, and only one was actually doing anything.

**Fix, done in two safe phases to avoid any downtime window:**
1. **Additive first:** pushed a new `Ingress` object (`nginx-alb`, `ingressClassName: alb`) to `apps/dev/` and `apps/prod/` in `snaPDF-gitops`, pointing at Nginx's Service. This made the ALB Controller provision a real ALB *alongside* the existing NLB — nothing about the old path was touched yet, both clusters kept serving traffic exactly as before while the new ALB came up and was confirmed reachable.
2. **Cutover, once the ALB was confirmed live:** updated `infra/modules/addons` — Nginx's `helm_release` now sets `controller.service.type = ClusterIP` (it stops requesting its own load balancer), and the Route53 CNAME data source switched from reading Nginx's *Service* status (`data.kubernetes_service`) to reading the new ALB *Ingress*'s status instead (`data.kubernetes_ingress_v1`) — the Service has no load balancer of its own to read a hostname from anymore.

Applied to dev first (`0 to add, 3 to change, 0 to destroy`: the helm release + the 2 `dev`/`staging` CNAME records), verified fully (curl 200s on both, DNS resolving to the ALB, old NLB confirmed gone via `aws elbv2 describe-load-balancers`), then the identical change to prod (`0 to add, 2 to change, 0 to destroy`). **Verified live on both:** traffic flow is now `Client → ALB → Nginx → pods`; only the 2 ArgoCD load balancers remain as `network`-type LBs, confirming no NLBs are left over from the app-facing path on either cluster.

This also unblocks `infra #19` (TLS) — a real ALB has an HTTPS listener to attach a certificate to; the NLB never supported that the same way.

### Phase 6 — Karpenter node autoscaling, dev proven working end-to-end (02/07/2026)
Replacing the fixed-shape managed node group's "add capacity" story — which required a human to notice a scheduling failure and manually run Terraform every time this project hit one, three separate times today (`Bug 30`, the CPU/pod-density fragmentation issue, and the `t3.xlarge`-vs-3rd-node decision) — with Karpenter, which watches for pods stuck `Pending` and provisions right-sized nodes on its own.

**Sequencing decision:** originally planned to shrink the managed node group first, then add Karpenter. Reversed after checking the actual numbers — dev's total CPU usage (1660m) barely fits one node's 1930m capacity, and prod's (2310m) already *exceeds* it. Shrinking first, before Karpenter exists to react, would have caused real, unrecoverable scheduling failures. Installed Karpenter fully and proved it works *before* touching the existing node group's size.

**Built, in order:**
1. Two new IAM roles in `infra/modules/iam` — a controller role (IRSA, scoped EC2/pricing/SSM read + tightly-scoped `iam:PassRole` to just the node role, not wildcard) and a node role (standard AWS-managed EKS worker policies) + its instance profile. Applied to both dev and prod.
2. Karpenter itself via Helm, added to `infra/modules/addons`, dev only for now.
3. Tagged dev's 2 private subnets with `karpenter.sh/discovery` (a new tag — existing tags like `Environment: dev` weren't precise enough, they also match the public/database subnets).
4. `EC2NodeClass` + `NodePool` manifests pushed to `snaPDF-gitops`'s `apps/dev/` — capped at `t3.micro`/`t3.small`/`t3.medium` only (all three share identical 2 vCPU, so the `6 vCPU` limit maps to *exactly* 3 nodes regardless of which size Karpenter picks), On-Demand only (no Spot interruption handling built yet).

**Hit and fixed one real bug during the first live test:** the `EC2NodeClass` initially failed validation (`spec.amiSelectorTerms: Required value`) — Karpenter's v1 API requires explicit AMI selection now, `amiFamily` alone isn't sufficient; fixed with `amiSelectorTerms: [{alias: al2023@latest}]`.

**Hit and fixed a second, more interesting bug:** the very first test node booted fine at the EC2/OS level (confirmed `running` in AWS) but its `NodeClaim` sat on `"Node not registered with cluster"` indefinitely. Cause: EKS requires an IAM role to be explicitly authorized before an EC2 instance using it can join as a node (via the `aws-auth` ConfigMap or an "access entry") — the managed node group's role gets this automatically as part of its own setup, but Karpenter's separately-created node role never went through that path. Fixed live via `aws eks create-access-entry --type EC2_LINUX`, then formalized into Terraform as an `aws_eks_access_entry` resource in `infra/modules/addons` (not `eks` or `iam` — `eks` can't depend on `iam`'s node-role output without creating a circular dependency, since `iam` already depends on `eks` for the OIDC provider) and imported the manually-created entry into state so it wasn't left as an undocumented manual change.

**Verified live, both directions:** deployed a test pod requesting more CPU than either existing node had free — watched Karpenter's logs react within ~3 seconds (found the pending pod, computed a `t3.micro` NodeClaim, launched it), watched the real EC2 instance boot and register (~2 min, mostly normal AWS boot time), and watched the pod actually run on it. Then deleted the test pod and watched Karpenter's consolidation cleanly terminate the now-empty node on its own — back to exactly 2 nodes, no manual cleanup needed.

Not yet done: the same full setup on prod, and shrinking the original managed node group now that Karpenter is proven reliable (deliberately deferred until prod is proven too).

## Workflow

### Issue tracker cleanup + v0.6.2 (02/07/2026)
The GitHub issue trackers across all 3 repos had accumulated 21 open issues from the original 26-27/06 planning pass (e.g. "Write Python Flask app," "Add EKS Terraform module," "Add KEDA to addons module") that were actually implemented weeks ago in Phases 0-3 but never closed. Verified each deliverable still exists in its repo (Dockerfiles, CI workflows, Terraform modules for VPC/EKS/addons/SQS/S3/IAM, Helm chart templates including ScaledObject/ExternalSecret/HPA) before closing, so the tracker now reflects actual remaining work rather than a mix of done-and-not-done items.

- Closed in `snaPDF`: #1, #2, #5-#16 (14 issues)
- Closed in `snaPDF-infra`: #4, #5, #11-#15 (7 issues)
- Left open (real remaining work): the 4 "IMPORTANT ISSUE" spec-compliance gaps per repo, plus `snaPDF-gitops` #4 and #6, plus `snaPDF-infra` #17

Tagged `v0.6.2` on `snaPDF` (version tags only ever go on the app repo, even when the work spans infra/gitops) to mark the tracker as trustworthy again before starting the next round of prod work.

### Scope decisions reversed on 3 remaining issues (02/07/2026)
Three issues originally scoped as "document the deviation, spec allows it" were reversed to "implement literally what the spec asks":

- **ArgoCD: one instance per cluster, not one shared instance.** Supersedes the "Final Architecture Decision" and "Single ArgoCD instance vs one per cluster" reasoning documented on 30/06/2026 — that reasoning is no longer the plan. Prod's `addons` module will install its own `helm_release.argocd` instead of prod being registered as a remote cluster inside dev's instance. Closed `snaPDF` issue #18 (doc-only version); replaced with `snaPDF-infra` issue #22 (actual deployment). Also removes the "register prod cluster with ArgoCD" item from the Phase 4 remaining-steps list.
- **TLS termination: implement it, not just write it down.** `snaPDF-infra` issue #19 now requires actually attaching a real ACM cert to the ALB's 443 listener and confirming HTTPS terminates there, not just documenting the intended strategy. Still hard-blocked on issue #18 (ALB in front of Nginx) existing first.
- **Rollback: exercise it once, not just describe it.** `snaPDF` issue #19 now requires actually shipping a change, then `git revert`-ing it and confirming ArgoCD auto-syncs back — proof it works, not just a paragraph asserting it would.

### Prod came up further than intended, and prod secrets created (02/07/2026)

**Discovery:** a `terragrunt run-all apply` meant to just bring dev back up (after the 02/07 destroy) also applied `environments/prod` in the same run, since both live under the same repo root. A transient DNS resolution blip hit `prod/rds` mid-run (`dial tcp: lookup ...: no such host` resolving the S3 state bucket) but terragrunt's retry succeeded 2 seconds later — confirmed live: `snapdf-prod` EKS cluster (2 nodes Ready), `snapdf-prod-rds` (available), and prod's `addons` module (ArgoCD, ALB controller, ESO, KEDA, Nginx — all pods Running) are now fully up. Refreshed local kubeconfig with both `snapdf-dev` and `snapdf-prod` contexts.

**Side effect — infra issue #22 satisfied for free:** the `addons` Terraform module has no per-environment gating on `helm_release.argocd`, so applying it for prod automatically gave prod its own independent ArgoCD instance (confirmed 7/7 pods Running, separate `argocd` namespace, separate cluster) — exactly what #22 asked for, with zero new code. Confirmed prod's ArgoCD has **zero** Applications registered (root bootstrap never applied there, per the still-open infra #17 gap) — so nothing has actually deployed into `production` yet. This is the safe state to be in before intentionally going live.

**Found while checking:** prod/rds's Terraform state was missing 2 outputs (`db_endpoint`, `db_master_user_secret_arn`) that dev's state already had, despite both using the same module code — re-ran `terraform apply` scoped to just `environments/prod/rds` (confirmed via `plan` first: 0 resources changed, output-only diff) to refresh them into state.

**Infra issue #21 closed:** with prod's RDS now live and its auto-managed master password secret ARN available, created:
- `snapdf-prod/db-credentials` — `{host, username, password}`, host from the rds module's `db_endpoint` output, username/password read directly from AWS's own `manage_master_user_password`-generated secret (never printed to any terminal output during creation)
- `snapdf-prod/jwt-secret` — a freshly generated, isolated 48-byte random key, deliberately not reused from dev's — satisfies the "genuinely separate signing key" option from #21's acceptance criteria

Wired both into `eso.secrets` for all 4 production services in `snaPDF-gitops` (commit `e7a0436`), verified with `helm template` against the real chart for all 4 services before pushing. Also found a leftover empty VPC (`projectview-dev`, pre-rename naming, no NAT gateway/ENIs — harmless, no ongoing cost) during this investigation, noted as minor cleanup debt.

**Also decided:** `gitops #4` (per-environment ingress hosts) will use a purchased domain + Route53 aliases instead of `sslip.io` — more representative of real production DNS practice per the spec's "production-grade" framing, and Route53 alias records self-heal if a load balancer is ever recreated (unlike a raw IP baked into an `sslip.io` hostname). Domain search in progress as of this writing.
