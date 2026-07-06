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

### Bug 35 — prod's `destroy.ps1` run failed on an unapplied IAM output (04/07/2026)
Ran `destroy.ps1 -Environment prod`; it errored immediately on the `addons` module: `addons/terragrunt.hcl:96` reads `dependency.iam.outputs.ebs_csi_role_arn`, but prod's actual deployed `iam` state didn't have that output. **Root cause:** the `ebs_csi` IAM role (added to `infra/modules/iam` for Phase 5/Prometheus PVC support) had been applied on dev but never on prod — code and prod's real state had drifted apart. This only surfaces on `destroy`, not `plan`/`apply`, because `mock_outputs_allowed_terraform_commands = ["validate", "plan"]` in the dependency block means destroy is forced to read the real (missing) output instead of falling back to the mock.

**Verified no damage:** despite the error, prod's cluster stayed `ACTIVE`, both nodes stayed `Ready`, and all 3 security groups / 5 ENIs / 3 subnets `destroy.ps1`'s pre-cleanup steps tried to delete were still intact — those `aws ec2 delete-*` calls had failed silently (suppressed via `2>$null`) against still-attached resources, so nothing was actually lost.

**Fix:** `cd infra/environments/prod/iam && terragrunt apply -target=aws_iam_role.ebs_csi -target=aws_iam_role_policy_attachment.ebs_csi` — created the 2 missing IAM resources for real, which populated `ebs_csi_role_arn`, then `destroy.ps1 -Environment prod -SkipK8s` completed cleanly end to end (RDS, addons×9, iam×23, s3×2, sqs×2, eks×43, vpc×24 — all destroyed, 0 errors). **This will recur on every future prod destroy** until prod's `iam` module gets a real full apply (or the addons dependency is made conditional) — currently just patched around, not fixed at the source.

### Bug 36 — orphaned ALB (+ its security groups) blocked dev's VPC teardown for over an hour (04/07/2026)
Same `destroy.ps1` session, dev environment: RDS/addons/iam/s3/sqs/eks all destroyed cleanly (43 EKS resources gone), but the final `vpc` module hung for 69+ minutes destroying subnets, then failed with `DependencyViolation: Network ... has some mapped public address(es)` on the Internet Gateway and `has dependencies and cannot be deleted` on two subnets.

**Root cause:** the AWS Load Balancer Controller's own pods run *inside* the EKS cluster it manages. `destroy.ps1`'s `addons` module has a `delete_load_balancers` hook that deletes the ingress-nginx Service and waits 90s for the ALB Controller to finish deleting the real AWS ALB — but 90s isn't reliably enough, and once the `eks` module destroys the cluster minutes later, the controller pod is gone and can never finish the AWS-side deletion it started. The ALB (`k8s-ingressn-nginxalb-...`) and its two ALB-Controller-created security groups (not Terraform-managed, so never in scope for cleanup) were left running indefinitely — exactly the failure mode already described in Bug 23's lesson ("a LB outlives the cluster it was created from"), just hitting the *ingress ALB* this time instead of a raw `type: LoadBalancer` Service.

**Fix (manual, one-time):** `aws elbv2 delete-load-balancer` on the orphaned ALB, then `aws ec2 delete-security-group` on the two leftover SGs (`k8s-ingressn-nginxalb-*`, `k8s-traffic-snapdf...`) once their ENIs released — after which retrying just `terragrunt destroy` in `infra/environments/dev/vpc` succeeded immediately (1 resource: the VPC itself).

**Not yet fixed at the source:** `destroy.ps1`'s ALB-deletion wait needs to be a real poll-until-gone (like Step 3 already does for LBs found via `elbv2 describe-load-balancers`), not a flat 90s sleep, and it needs to happen (and be confirmed complete) strictly *before* the `eks` module is allowed to destroy the cluster — right now `addons` and the ALB-triggering hook can finish "successfully" from Terraform's point of view while the real AWS deletion is still in flight.

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

### Phase 6 — Karpenter, prod done too (02/07/2026)
Repeated the identical sequence on prod: Helm install, subnet tagging, the `aws_eks_access_entry` fix (already known from dev, applied directly this time with zero rediscovery needed), and a prod-specific `NodePool`.

**Prod's NodePool deliberately sized differently from dev's, not just scaled up:** `t3.medium`/`t3.large`/`t3.xlarge` instead of dev's `t3.micro`/`t3.small`/`t3.medium` — prod's worker pods alone need up to 1GiB memory per pod, which doesn't leave realistic headroom on the smaller instance sizes once the per-node DaemonSets are accounted for. Limit set to `9 vCPU / 18GiB` (a deliberate, cost-conscious ceiling — not an attempt to cover prod's theoretical worst-case HPA/KEDA burst, which could reach ~21 vCPU if everything scaled to maximum simultaneously; this project doesn't need to provision for that).

One transient hiccup, unrelated to configuration: the first prod apply hit `http2: client connection lost` mid-install (same class of transient network blip seen earlier today with the S3 backend) — resolved with a plain retry, no code change needed.

**Verified live, both directions, on prod:** test pod requesting more CPU than either existing node had free → Karpenter provisioned a real `t3.medium` node within ~2 minutes → pod ran on it → pod deleted → Karpenter's logs showed it disrupt/taint/drain/delete the now-empty node within about a minute → back to exactly 2 nodes. Real prod app pods (`api`/`auth`/`free-worker`) confirmed undisturbed throughout.

Karpenter is now proven working identically on both clusters. Still not done: shrinking either cluster's original managed node group — deliberately held until a deliberate decision to do so, not automatic just because Karpenter works.

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

### Prod ArgoCD Services-missing, 3rd occurrence (03/07/2026)
Same root cause as Bugs 23/27: `argocd-server`'s Service was completely absent on prod (pod `Running`, no Service object at all — confirmed via `kubectl get svc -n argocd` showing 4 of the expected 5 services), even though `terragrunt plan -target=helm_release.argocd` reported `No changes` (Terraform only tracks Helm release metadata, never the child Kubernetes objects a chart renders). Fixed identically: `terragrunt apply -replace=helm_release.argocd` from `infra/environments/prod/addons` — forces `helm uninstall` + fresh `helm install`, CRDs preserved. Verified: `argocd-server` Service back as `LoadBalancer` with a real hostname, all 7 prod Applications `Synced`/`Healthy`. Third time this exact class of drift has hit an addon on this project — worth a periodic `kubectl get svc -A` sweep against every Terraform-managed Helm release rather than waiting to notice via a downstream symptom.

### Dev environment rebuilt from scratch (03/07/2026)
Ran `terragrunt run-all apply` on `infra/environments/dev` to bring dev back up after its 02/07 destroy (~35 min: VPC, EKS, RDS, SQS, S3, IAM all applied cleanly). The `addons` module failed on the first pass — `aws_route53_record.app` reads the live `nginx-alb` Ingress's load-balancer hostname via a `data "kubernetes_ingress_v1"` source, but that Ingress is gitops-managed (ArgoCD-applied), and ArgoCD's root bootstrap (`kubectl apply -f infra/bootstrap/root-app.yaml`) is a manual step Terraform never runs — the exact gap tracked as infra #17. On a fully fresh cluster this data source has nothing to read, and Terraform aborted the whole module before creating anything (not just the Route53 record).

**Fix, two phases:**
1. `terragrunt apply -target=helm_release.alb_controller -target=helm_release.eso -target=helm_release.argocd -target=helm_release.nginx -target=helm_release.keda -target=helm_release.karpenter -target=aws_eks_access_entry.karpenter_node` — brings up every addon except the two Route53 records, since none of the targeted resources depend on the Ingress data source.
2. Manually applied dev's root bootstrap, waited for the ALB Controller to actually provision real load balancers for both `nginx-alb` (Ingress) and `argocd-server` (Service), then re-ran a full `terragrunt apply` on `addons` — this time the data sources had real hostnames to read, and all 3 Route53 CNAMEs (`dev.`, `staging.`, `argocd-dev.snapdf.bond`) were created successfully.

**Two more post-recreate gaps surfaced once ArgoCD synced real app pods, both previously-known classes of "stale local state after RDS is destroyed/recreated" (Bug 29's lesson generalized):**
- **Stale password:** `snapdf/db-credentials` still held the previous RDS instance's auto-generated password. Confirmed by comparing it against the fresh instance's own AWS-managed secret (`rds!db-...`) — host matched (deterministic naming) but password didn't. Fixed via `aws secretsmanager put-secret-value` with the new password, then force-synced every ExternalSecret in `dev`/`staging` (`kubectl annotate externalsecret ... force-sync=$(date +%s) --overwrite`) and restarted all 4 deployments in both namespaces (not just the crashing one — `api`/`auth` connect lazily and would've silently kept using the stale password otherwise, same lesson as Bug 29).
- **Missing logical database:** even after the password fix, `free-worker-staging` kept crash-looping with a *new* error: `database "snapdf_staging" does not exist`. Bug 31's fix had created this as a second logical database on dev's RDS instance via a one-off `kubectl exec ... psycopg2` command — Terraform only manages the default `snapdf` database, so a from-scratch RDS instance never has it. Recreated it the same way (`CREATE DATABASE snapdf_staging` via `api-dev`'s pod, which already has DB credentials mounted), then restarted `free-worker-staging`.
- **Lesson:** any manual, one-off step performed directly against a specific RDS instance (password sync, `CREATE DATABASE`) is tied to that *instance*, not the Terraform config — it silently needs to be redone after every destroy/recreate of that instance, same as the ArgoCD root bootstrap needs redoing after every cluster recreate. None of these are automated yet.

**Verified live:** all 12 dev/staging ArgoCD Applications `Synced`/`Healthy`, `curl` 200 on `dev.snapdf.bond/api/`, `/auth/`, and `staging.snapdf.bond/api/`.

### Infra #19 — real TLS termination at the ALB (03/07/2026)
**Problem:** confirmed via `aws acm list-certificates` (empty) and the `nginx-alb` Ingress spec (HTTP rule only, no `tls:`/cert annotation) that every request to the app — including the `/login` POST carrying a username/password and the JWT returned afterward — travelled as plaintext HTTP. No certificate existed anywhere in the account, and the ALB Controller only ever provisions the listeners an Ingress actually asks for, so the ALB had only ever had a port-80 listener.

**Fix:**
1. Added `aws_acm_certificate` (domain `snapdf.bond` + SAN `*.snapdf.bond`, `validation_method = "DNS"`) to `infra/global/main.tf` — one wildcard cert covers every current/future subdomain, requested in us-east-1 to match the ALB's region. Added `aws_route53_record` for the DNS validation challenge and `aws_acm_certificate_validation` to block until ACM confirms issuance.
2. **Hit a real ACM quirk first:** requesting an apex domain + its wildcard SAN together, ACM often returns the *same* validation CNAME name for both — the first `for_each` (keyed by `domain_name`) tried to create that identical Route53 record twice, and the second attempt failed with `already exists`. Fixed by re-keying the `for_each` by `resource_record_name` instead, using Terraform's `for ... => {...}...` grouping syntax (the trailing `...`) to collapse duplicate keys into one resource, taking `each.value[0]` since the grouped values are identical.
3. Applied `infra/global` — cert issued and DNS-validated in under a minute once the record collision was fixed.
4. Added `alb.ingress.kubernetes.io/certificate-arn` (the new cert ARN), `listen-ports: '[{"HTTP":80},{"HTTPS":443}]'`, and `ssl-redirect: '443'` annotations to both `apps/dev/nginx-alb-ingress.yaml` and `apps/prod/nginx-alb-ingress.yaml` in `snaPDF-gitops`. Committed, pushed, force-refreshed both clusters' `root` Application to pick it up immediately instead of waiting for ArgoCD's normal poll window.

**Verified live, both dev and prod:** `aws elbv2 describe-listeners` shows both ALBs now have a 443/HTTPS listener alongside the original 80/HTTP one; `curl https://{dev,prod}.snapdf.bond/api/` returns `200` with a trusted cert (curl verifies the chain by default — no `-k`/insecure flag needed); `curl http://{dev,prod}.snapdf.bond/api/` now returns `301` redirecting to the `https://` equivalent instead of serving plaintext. Closes `snaPDF-infra` issue #19.

**Also decided:** `gitops #4` (per-environment ingress hosts) will use a purchased domain + Route53 aliases instead of `sslip.io` — more representative of real production DNS practice per the spec's "production-grade" framing, and Route53 alias records self-heal if a load balancer is ever recreated (unlike a raw IP baked into an `sslip.io` hostname). Domain search in progress as of this writing.

### snaPDF #19 — rollback drill, exercised live end-to-end (03/07/2026)
Originally scoped as documentation-only ("describe how rollback would work"), reversed to actually proving it, same pattern as TLS and prod-apply. Exercised entirely by hand against **dev** (not prod — prod is meant to move to manual-sync-only once its RBAC work lands, so an auto-sync rollback demo belongs on dev/staging).

**Steps actually run:**
1. Branched `chore/rollback-drill` off `snaPDF`'s `main`, changed one line in `auth/main.py` — the login page's submit button text (`Sign In` → a visibly broken string) — a purely cosmetic change with no functional risk and nothing in `auth/tests/` asserting on that string.
2. Opened and merged PR `snaPDF#24` into `main` via a normal merge commit (confirmed the merge strategy doesn't matter here — the commit that actually gets reverted later lives entirely in a different repo, `snaPDF-gitops`, created directly by CI, not by this PR).
3. Merge triggered `ci-auth.yml` only (path-filtered to `auth/`) — built and pushed a new image to ECR, then committed the new tag straight to `snaPDF-gitops` (`d40e8fc`, "ci: update auth image tag to 499e36355c... (dev)").
4. **Watched a real gap live:** `auth-dev`'s ArgoCD Application still showed `Synced`/`Healthy` for several minutes after `d40e8fc` landed — because "Synced" only means "matches the last commit ArgoCD has seen," and its default git-polling interval (`timeout.reconciliation`, 180s) hadn't ticked over yet. Confirmed directly by comparing the live pod's image SHA against the new tag in `values.yaml` — they didn't match yet. This exact gap is now filed as `snaPDF-infra#25` (GitHub → ArgoCD webhook for instant sync) rather than left as an unexamined assumption.
5. Once ArgoCD's poll caught up, `https://dev.snapdf.bond/auth/` visibly showed the broken button text — the "confirmed broken" checkpoint, seen in a real browser, not assumed from a green dashboard tile.
6. **The actual rollback:** `git revert d40e8fc --no-edit` in `snaPDF-gitops` → `d63d4bb` ("Revert \"ci: update auth image tag to 499e36355c...(dev)\""), pushed directly to `main` (no PR — matches how CI itself commits to this repo). `git revert` was used deliberately over `git reset`: it adds a new commit undoing the change rather than rewriting history on a branch other systems (ArgoCD, CI) actively read from.
7. Rather than wait out another poll cycle, forced ArgoCD to check immediately via the UI's Refresh button on `auth-dev` (equivalent CLI form: `kubectl patch application auth-dev -n argocd --type merge -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"normal"}}}'`) — since auto-sync was already enabled on the Application, the refresh alone was enough to trigger the sync back, no separate manual "Sync" click needed.
8. **Verified live:** `https://dev.snapdf.bond/auth/` showed the original "Sign In" button again — the full loop (ship → confirm broken → revert → confirm fixed) proven with zero `kubectl edit`/`apply` commands run against the cluster at any point; every state change flowed through a git commit.

**Lesson:** "rollback" in a GitOps setup isn't a feature you build — it's a direct consequence of the reconciliation loop already existing. The only genuinely new thing this drill produced was catching the poll-interval blind spot (`snaPDF-infra#25`), which wouldn't have surfaced from just writing the strategy down on paper. Closes `snaPDF` issue #19.

### Phase 5 — Prometheus + Grafana, dev fully working (03/07/2026)

**Goal:** real dashboards instead of only `kubectl`-driven verification. One chart, `kube-prometheus-stack` (Prometheus Operator, Prometheus server, Alertmanager, Grafana, node-exporter, kube-state-metrics), added to `infra/modules/addons`. Also wired KEDA's own scaler metrics into it (`prometheus.operator.enabled` + `prometheus.metricServer.enabled` on the existing `keda` release) so its scaling decisions are graphable.

**Bug 33 — no working StorageClass existed on this cluster.** Prometheus's pod sat `Pending` immediately: `unbound immediate PersistentVolumeClaims`. Nothing before this ever needed a `PersistentVolumeClaim` (RDS/S3 are both external to the cluster), so nobody had noticed that the cluster's default `gp2` StorageClass points at `kubernetes.io/aws-ebs` — Kubernetes's old in-tree EBS provisioner, removed from the platform years ago. Fixed by adding a real `aws-ebs-csi-driver` EKS addon (new IRSA role in `infra/modules/iam`, the addon itself placed in `infra/modules/addons` rather than the `eks` module — same circular-dependency reasoning as Karpenter's access entry) and a new `gp3` StorageClass using the actual working provisioner (`ebs.csi.aws.com`), marked default; `gp2` left alone, harmless. Verified live: PVC bound to a real EBS volume (`vol-01bbfc2a387c83eb8`, `us-east-1a`, attached to whichever node the Prometheus pod landed on), Prometheus `Running`.

**Grafana's admin password:** the chart's own default (`prom-operator`) is a fixed, publicly documented string — replaced with a real `random_password`, stored in Secrets Manager (`snapdf/grafana-admin-password`) the same way every other credential in this project is handled, passed to the chart via `set_sensitive` so it never appears in plan/apply output.

**Bug 34 — Grafana's Ingress never got a rule on the shared ALB (long debugging thread, root cause still unconfirmed for the original mechanism).** Tried to put Grafana on the same physical ALB as the app via `IngressGroup` (`alb.ingress.kubernetes.io/group.name`, matching the pattern already used for the app's own Ingress) instead of paying for a second load balancer. The app's rule worked; Grafana's never appeared on the real ALB, with zero errors anywhere. Ruled out, each with a real check, not a guess: RBAC (confirmed the controller could read/list the Ingress fine), annotation/class typos (byte-identical on both sides), a stale controller cache (full pod restart, no change), and an outdated controller version (upgraded `aws-load-balancer-controller` chart `1.7.1` → `1.17.1`, confirmed existing app traffic unaffected). The upgrade did surface one real, separate, worth-keeping bug: the newer controller calls `elasticloadbalancing:DescribeListenerAttributes`/`ModifyListenerAttributes`, which the existing IAM policy never granted — added both actions to `infra/modules/iam`'s `alb_controller` policy. Even with all of that fixed, Grafana's rule still never appeared on the shared ALB — true root cause inside the controller's `IngressGroup` merge logic was never found.

**The actual fix:** stopped trying to make the ALB controller merge two Ingresses directly, and used the pattern already sitting in this project's own `charts/service/templates/ingress-nginx.yaml` — the app's own `api`/`auth` Ingresses don't use `ingressClassName: alb` at all, they use `kubernetes.io/ingress.class: nginx`. The ALB only ever has **one** rule (`path: /*`, no host restriction) forwarding everything to Nginx; Nginx does all real host-based routing internally already. Gave Grafana's Ingress the same `nginx` class instead of `alb`, dropped the now-irrelevant `alb.ingress.kubernetes.io/*` annotations from both its Ingress and (since nothing needs to share a group with it anymore) from `nginx-alb-ingress.yaml` too.

**One more real gap this surfaced:** removing `group.name` caused the ALB Controller to recreate the load balancer under its original standalone name (`k8s-ingressn-nginxalb-fbd52a16a2`, abandoning the grouped `k8s-snapdfdev-...` one) — Terraform's `aws_route53_record` resources needed a fresh `apply` to pick up the new real hostname before anything resolved again. Also updated `aws_route53_record.grafana` to read its hostname from the existing `nginx_alb` data source (Grafana's Ingress no longer gets its own `status.loadBalancer` entry once it's Nginx-class, only ALB-class Ingresses do).

**Verified live:** `https://grafana-dev.snapdf.bond` → Grafana's login page (`200` after following its own `302` redirect), `https://dev.snapdf.bond/api/` and `https://staging.snapdf.bond/api/` both still `200` (confirming the change didn't disturb existing traffic), admin password confirmed working via Secrets Manager.

**Not yet done:** any of this on prod (IAM role, addon, gp3 class, chart, KEDA integration, Ingress — all Terraform/gitops changes exist for prod already, just not applied yet).

### Phase 5 — real business metrics + KEDA metrics, both root-caused (03/07/2026)

**postgres-exporter (users/conversions):** working end to end. Root cause of "no metrics showing" was a naming assumption error, not a real bug — the custom-query metrics don't get a `pg_` prefix like the exporter's built-in ones; they're exposed exactly as named in `queries.yaml` (e.g. `snapdf_users_total_count`), confirmed via `helm pull`-ing the chart and reading `templates/deployment.yaml` directly rather than guessing. Also hit and fixed a real Helm-values bug along the way: `extraArgs` needs to be nested under `config` in this chart (`config.extraArgs`) — a bare top-level `extraArgs` is silently accepted and does nothing, same "set doesn't validate" failure mode as Bug 24/34. Confirmed live: `snapdf_users_total_count` reads `0` (accurate — dev's DB is freshly rebuilt today, zero real signups yet). The two `GROUP BY status` queries (`free_jobs`/`signed_jobs` by status) correctly emit *zero series* right now — not broken, just no rows exist in those tables yet to group; they'll populate the moment a real conversion job is submitted.

**KEDA metrics — real root cause found, needs a fix next session:** after also fixing the ServiceMonitor's dual-key requirement (`prometheus.operator.enabled` AND `.serviceMonitor.enabled`, both needed together) and relaxing Prometheus's `serviceMonitorSelector` to `{}` (cluster-wide, since it defaulted to only matching ServiceMonitors labeled `release: kube-prometheus-stack` — a multi-tenant safeguard this single-tenant cluster doesn't need), KEDA's operator still only exposes `keda_build_info` — no scaler activity metrics at all. **Actual cause:** `kubectl get scaledobject -A` returns nothing — there are zero `ScaledObject` resources in the cluster right now, so KEDA has nothing to report metrics *about*. `signed-worker-dev`'s ArgoCD Application shows `OutOfSync` with the `ScaledObject` specifically marked `Missing` (every other resource in that Application — Deployment, Service, ConfigMap, ExternalSecret — is `Synced`/`Healthy`). Forced a hard refresh; not yet confirmed resolved before this session ended. **This means signed-worker is not currently being autoscaled by KEDA at all** — worth treating as a real bug to chase down next session (likely dropped during one of today's several KEDA Helm reinstalls), not just an observability gap.

**Also discovered, worth remembering:** repeatedly this session, a `terragrunt apply` reported success (exit 0, "Apply complete") while the actual Helm release in the cluster never changed — confirmed via `helm history` showing no new revision. Root cause not confirmed, but every occurrence coincided with the same class of transient error seen once before ("failed to download openapi... context deadline exceeded") earlier in the same apply run. Terraform's state ends up believing the change succeeded even though the cluster never received it — the fix each time was `-replace` on the specific resource to force a real re-sync. Worth treating "plan says no changes" with suspicion after any apply that logged an API timeout, rather than trusting it outright.

**End of session state:** dev's Grafana/Prometheus/postgres-exporter stack is genuinely working; the signed-worker `ScaledObject` gap and finishing the dashboard itself are the two open threads for next time. None of this has been applied to prod yet.

### Phase 5 — business/scaling dashboard built as code (04/07/2026, cluster down)

Built `apps/dev/grafana-dashboards.yaml` (and an identical `apps/prod/` copy, since the queries aren't environment-specific) in `snaPDF-gitops` — a `ConfigMap` in the `monitoring` namespace labeled `grafana_dashboard: "1"`. `kube-prometheus-stack`'s Grafana ships with a sidecar (enabled by default) that watches for exactly this label in its own namespace and auto-loads any `*.json` key it finds — no chart values changed, same "define once in git, ArgoCD applies it" pattern as everything else here rather than clicking through the Grafana UI.

Panels: total registered users (`snapdf_users_total_count`), free/signed jobs by status (`snapdf_free_jobs_by_status_count`/`snapdf_signed_jobs_by_status_count`, both confirmed as the real metric names from the prior session — no `pg_` prefix), and two KEDA panels (`keda_scaler_active`, `keda_scaler_metrics_value`, both filtered to `signed-worker`). Didn't duplicate node/pod/cluster health — `kube-prometheus-stack`'s bundled default dashboards already cover that.

**Not verified live** — done entirely from reading the chart/module source while both clusters are destroyed. The KEDA panels will read empty until the still-open `signed-worker-dev` `ScaledObject` gap above is actually resolved; the business-metric panels should work immediately once applied, same as they did before. First real test is the next time dev comes back up: confirm the dashboard appears in Grafana's UI under the sidecar's default folder, and that the business-metric panels render real data.

### Both dev and prod rebuilt from total zero simultaneously (04/07/2026)

First time both environments — VPC included — were destroyed and recreated at once, rather than one at a time. `terragrunt run-all apply` on each: VPC/EKS/IAM/RDS/S3/SQS all applied cleanly on both (~35-40 min each, run in parallel). The `addons` module failed on **both**, identically, on the first pass — same root cause as the 03/07 dev rebuild (`aws_route53_record.app`/`.grafana` reading a `nginx-alb` Ingress status that doesn't exist yet, since ArgoCD's root bootstrap is still a manual step, infra #17) — confirming this isn't a one-off, it's the expected failure mode for *any* from-zero rebuild until infra #17 is actually automated.

**Fix, same two-phase procedure as 03/07, extended to cover Phase 5/6's newer resources:**
1. `terragrunt apply -target=<everything except aws_route53_record.app/.grafana>` (16 targets: ALB controller, ESO, ArgoCD, Nginx, KEDA, Karpenter, EBS CSI addon, gp3 StorageClass, Grafana secret, kube-prometheus-stack, postgres-exporter + its queries ConfigMap, Karpenter's access entry) — succeeded on both, except `aws_route53_record.argocd` also failed on both: ArgoCD's own `LoadBalancer` Service hadn't had its AWS hostname populated yet, only ~40s after the Helm release finished (an NLB typically takes 1-3 min). Harmless, self-resolves once you wait and retry.
2. Bootstrapped ArgoCD's root Application by hand on each cluster, waited for the ALB Controller to actually provision real load balancers for `nginx-alb` (Ingress) and `argocd-server` (Service), then a final untargeted `terragrunt apply` on each `addons` module picked up all 3-4 remaining Route53 CNAMEs cleanly.

**Real mistake made mid-fix, caught and corrected:** applied `bootstrap/root-app.yaml` (hardcoded `path: apps/dev`) to **both** clusters instead of using the separate `bootstrap/root-app-prod.yaml` (`path: apps/prod`) for prod — missed that the two files exist separately (same class of "assumed the doc's old single-file procedure still applies" as this whole session started from). Consequence: prod's ArgoCD synced `apps/dev`'s `services-appset`/`env-scoped-appset` ApplicationSets and briefly ran real `dev`/`staging` namespaces with live pods, Services, and HPAs *inside the prod cluster* (some crash-looping — they couldn't reach dev's RDS across VPCs, which limited the blast radius but wasn't the reason it was safe).

**Fix:** applied the correct `root-app-prod.yaml` (same `metadata.name: root`, so `kubectl apply` updated the existing Application's `spec.source.path` in place from `apps/dev` to `apps/prod`). The ApplicationSet controller correctly regenerated `-production` Applications and started deleting the stale `-dev`/`-staging` ones — but they got stuck permanently `Terminating`: each one's `resources-finalizer.argocd.argoproj.io` blocks real deletion until ArgoCD can resolve the Application's `spec.project` ("non-prod") to know what it's allowed to prune, and that AppProject had already been pruned from the cluster (it only ever existed via `apps/dev/appprojects.yaml`, which prod's root no longer sources) — a genuine finalizer deadlock, not something that resolves itself. Fixed by manually stripping each stuck Application's `finalizers` (`kubectl patch ... --type merge -p '{"metadata":{"finalizers":[]}}'`) so the Application objects themselves could delete, then `kubectl delete namespace dev staging` directly on the prod cluster to guarantee the real leftover Deployments/Services/HPAs were actually gone rather than relying on ArgoCD's own (blocked) cascade. Verified clean: prod's ArgoCD now shows only `*-production` Applications, `prod`'s namespace list has no `dev`/`staging`, and a subsequent full `terragrunt apply` on prod's `addons` module didn't reintroduce anything.

**Separate bug, prod only: `snapdf-prod/db-credentials` was corrupted.** `helm_release.postgres_exporter`'s plan failed on `jsondecode(data.aws_secretsmanager_secret_version.db_credentials.secret_string)`: `invalid character '×' looking for beginning of value`. `aws secretsmanager get-secret-value` showed the actual raw string started with a UTF-8 byte-order-mark (`EF BB BF`) before the `{` — invisible in most terminals, fatal to a strict JSON parser. Likely came from a previous manual rebuild of this secret (per Bug 29's "derived, not durable" lesson) done via a Windows tool that defaults to UTF-8-with-BOM (e.g. PowerShell's `Out-File`/`Set-Content` without `-Encoding utf8` — noted as a known gotcha, not specific to this project). Separately, the password inside was also stale — didn't match this session's freshly-recreated RDS instance's own AWS-managed secret (host matched; deterministic RDS endpoint naming held again, same as Bug 29). **Fix:** rebuilt the JSON from scratch (`{"username":"dbadmin","host":"<current db_endpoint output>","password":"<current db_master_user_secret_arn's password>"}`), written via a plain UTF-8 file (no BOM) and pushed with `aws secretsmanager put-secret-value --secret-string file://...`. Confirmed via a hex dump (`xxd`) that the fixed value starts directly with `7b` (`{`), not the BOM's `ef bb bf`.

**Verified live, both dev and prod, after all of the above:** `curl` 200 on `{dev,staging,prod}.snapdf.bond/api/`; Grafana's login redirect (302) on `grafana-{dev,prod}.snapdf.bond`; ArgoCD's own self-signed-cert UI (200 with `curl -k`) on `argocd-{dev,prod}.snapdf.bond`.

**Lesson:** the from-zero-rebuild ordering gap (infra #17) isn't a rare edge case anymore — it's now been hit on 3 separate rebuilds (dev alone, then dev+prod together twice in one session). Worth actually prioritizing over the remaining spec-compliance gaps next, especially since the manual root-bootstrap step is also exactly what caused this session's cross-environment mixup — automating it removes both problems at once.

### infra #17 closed — ArgoCD root bootstrap automated, v0.8.1 (04/07/2026)

Acted on this session's own "lesson" above immediately. Added two resources to `infra/modules/addons/main.tf`:

- **`null_resource.argocd_root_bootstrap`** — inlines the root Application manifest via `yamlencode()` and picks `apps/dev` vs `apps/prod` by `var.env_name`, then applies it with `kubectl apply -f -` through a `local-exec` provisioner (`depends_on = [helm_release.argocd]`). Deliberately not the `kubernetes_manifest` resource — that needs to resolve the target CRD's schema at plan time, and ArgoCD's `Application` CRD is installed by `helm_release.argocd` in this same apply, so on a truly fresh cluster the schema doesn't exist yet when planning starts. Raw `kubectl` has no such restriction.
- **`null_resource.wait_for_load_balancers`** — polls (`kubectl get ingress`/`get svc`, 15s interval, 10min budget) until the ALB Controller has actually provisioned real hostnames for `nginx-alb` and `argocd-server`, before anything reads them. Same poll-don't-blind-sleep lesson already learned for LB *deletion* in Bug 34's destroy hook, applied to *creation* this time. Both existing `data` sources (`nginx_alb`, `argocd` service) now `depends_on` this resource.

Deleted `infra/bootstrap/root-app.yaml` and `root-app-prod.yaml` — the manifest content is now the single source of truth, inlined in Terraform, rather than two files a human could apply to the wrong cluster (exactly the mistake made two entries above).

**Verified end-to-end on both dev and prod:** `kubectl get application root -o jsonpath='{.spec.source.path}'` correctly returned `apps/dev` on dev and `apps/prod` on prod (the critical check, given the mixup above); both clusters' ArgoCD Application lists stayed correctly scoped throughout; `curl` 200/302 on both app and Grafana URLs before and after. `terragrunt run-all apply` now stands a brand-new cluster up fully unattended — no manual step, no risk of the wrong file, no race against ArgoCD/ALB timing.

### snaPDF #22 closed — signed-in badge now verifies the JWT signature (04/07/2026, PR #25)

**The bug:** the badge decoded the JWT payload directly in the browser — `JSON.parse(atob(token.split('.')[1]))` — with zero signature check. Anyone could craft a fake token in devtools (`header.{"sub":"attacker","tier":"signed"}.garbage`), put it in the URL, and the page would display "Signed in as attacker — Priority Queue". The comment in the code even acknowledged this was a deliberate shortcut ("no verification -- server verifies on submit"). The actual security boundary — which SQS queue a job gets routed to — was never at risk: `api/app.py`'s `decode_jwt()` (used by `/convert`) already verified signatures correctly. Only the cosmetic badge was spoofable.

**Fix:** `index()` now calls the existing, already-correct `decode_jwt()` before rendering the page, and passes the verified `username`/`tier` into the template as real server-side variables — the browser is handed the already-verified result, not the raw token to decode itself. A forged token now fails `decode_jwt()` server-side and falls back to the free-tier badge, identically to having no token at all. Also switched the username's rendering from string-concatenated `innerHTML` to a real DOM node + `textContent`, closing a minor adjacent XSS-shaped risk in the same line while already touching it.

**Verified:** 3 new tests added to `api/tests/test_app.py` — no token → free tier; a genuinely valid signed token → verified username/tier rendered; **a forged token (valid shape, wrong signing secret, same payload an attacker would craft) → completely ignored, falls back to free tier.** All 13 tests pass (10 existing + 3 new). PR `fix/jwt-signature-verification` (#25) merged — but see the "PR #25's CI silently failed to deploy" entry below; the fix wasn't actually live until several hours later.

### infra #24 closed — managed node group shrunk now that Karpenter is proven (04/07/2026)

Changed `infra/modules/eks/main.tf`'s `eks_managed_node_groups.default` from `min=1/max=3/desired=2` to `min=1/max=1/desired=1` on both dev and prod — this group is now just a fixed floor (somewhere for CoreDNS/the ALB Controller/Karpenter's own controller pod to run before Karpenter has provisioned anything itself), not a second source of elasticity alongside Karpenter's already-proven NodePool.

**Hit two real problems applying this, both instructive:**

1. **The `terraform-aws-modules/eks` module deliberately ignores `scaling_config[0].desired_size` via a `lifecycle { ignore_changes }` block** (so Terraform doesn't fight with runtime autoscaling decisions) — meaning `desired_size = 1` in code is silently a no-op against an *already-existing* node group; only `max_size` actually gets sent on `apply`. Since AWS's EKS API hard-rejects an update where current desired capacity would exceed the new max (`InvalidParameterException: desired capacity 2 can't be greater than max size 1` — it does **not** auto-clamp, unlike a raw ASG), the very first `apply` failed outright on both dev and prod. Fixed by calling `aws eks update-nodegroup-config --scaling-config minSize=1,maxSize=1,desiredSize=1` directly via the AWS CLI *first* (the officially-intended way to change `desired_size` for this module, per its own `ignore_changes`), then re-running `terragrunt apply` — which then saw zero drift and applied cleanly.
2. **Karpenter's own Helm chart defaults to 2 replicas with a hard pod anti-affinity + zone-spread topology constraint** — fine with 2+ nodes, but a genuine deadlock with exactly one fixed baseline node: Karpenter's 2nd replica could never find a second permanent node to land on (`kubectl describe pod` showed `FailedScheduling: didn't match pod topology spread constraints`), and since Karpenter is the very thing that would normally add more capacity to fix a Pending pod, it couldn't rescue itself. Fixed by explicitly setting `replicas = 1` on `helm_release.karpenter` — it doesn't need its own HA at this project's scale; losing it briefly only pauses new scheduling decisions, it doesn't affect already-running pods or nodes.

**Verified live on both clusters:** old node drained cleanly (`SchedulingDisabled` → terminated), Karpenter provisioned a temporary node to absorb the transition, zero stuck pods throughout, Karpenter itself settled back to exactly 1 pod `Running`, and `curl` 200/302/200 on app/Grafana/ArgoCD the whole time.

### infra #25 closed — GitHub → ArgoCD webhook for instant sync (04/07/2026)

**The gap** (found during the rollback drill, 03/07): ArgoCD only re-checks git on its default ~180s poll interval, so a push can sit unsynced for up to 3 minutes even with `syncPolicy.automated` on.

**Fix, two parts:**
1. **Terraform** (`infra/modules/addons/main.tf`): a `random_password` per environment, stored in Secrets Manager (`snapdf{,-prod}/argocd-webhook-secret`), wired into `helm_release.argocd` via `set_sensitive` on `configs.secret.githubSecret` — the exact key the `argo-cd` Helm chart uses to populate ArgoCD's own webhook-signature-validation secret.
2. **GitHub** (one-time, via `gh api repos/ilaycohen12/snaPDF-gitops/hooks`, not Terraform — a whole GitHub provider + PAT credential for one webhook per environment wasn't proportionate): registered two separate webhooks on `snaPDF-gitops` — `https://argocd-dev.snapdf.bond/api/webhook` and `https://argocd-prod.snapdf.bond/api/webhook` — since dev and prod run fully independent ArgoCD instances watching the same repo, a single webhook can only ever notify one of them.

**Verified:** triggered a manual ping on both (`gh api -X POST .../hooks/<id>/pings`), then checked `.../deliveries` — both show `status: OK, status_code: 200`, confirming ArgoCD actually validated the webhook signature and accepted the payload, not just that GitHub sent it.

### URL restructuring — api service moved to the root path; prod dropped its subdomain entirely (04/07/2026)

**The ask:** the api page required `/api` at the end of every URL with nothing serving the bare domain (a real 404) — the site should live at the root path everywhere, and prod specifically should be the bare apex domain (`snapdf.bond`), not `prod.snapdf.bond`. `/auth` stays as-is.

**What actually had to change, three repos:**
- **gitops**: `api`'s `ingress.path` → `/` on dev/staging/prod. Prod's `api` *and* `auth` Ingress `host` → `snapdf.bond` (dev/staging keep their env-prefixed hostnames). `auth`'s `API_URL` env var updated to match on all three (dev/staging just drop `/api`; prod drops both `/api` and the `prod.` prefix).
- **app**: the page's own client-side JS called `fetch('/api/convert')`/`fetch('/api/jobs/...')` as *absolute* paths — independent of wherever the page itself is served from, so these would 404 the moment the Ingress path changed. Fixed to `/convert`/`/jobs/...`.
- **infra**: a `CNAME` record can never exist at a domain's bare apex (a DNS spec rule, already the documented reason `prod.snapdf.bond` used a subdomain in the first place) — so `aws_route53_record.app` now treats an empty string in `var.app_hostnames` as "the bare apex," using a real `A`/ALIAS record (Route53's own apex-compatible extension) pointing at the ALB via its region's fixed canonical hosted-zone ID (`Z35SXDOTRQ7X7K` for us-east-1 — a stable AWS constant, unrelated to this project's own Route53 zone). Prod's `terragrunt.hcl` now passes `app_hostnames = [""]` instead of `["prod"]`.

**Two real deployment gaps found verifying this, both worth remembering:**

1. **PR #25's CI (the JWT fix, above) had silently failed to actually deploy.** `ci-api.yml` built and pushed the new image to ECR successfully, but its last step — committing the new tag into `snaPDF-gitops` — failed with `remote: fatal error in commit_refs` / `[remote rejected] main -> main`, almost certainly a push race against this session's own concurrent gitops commits. GitHub Actions reported the run as a clean failure (visible in `gh run list`), but nothing downstream ever surfaced it — dev kept running the pre-fix image for hours, `#22`'s fix merged but not live, until this session's own audit of recent CI runs caught it. Resolved for free once PR #26 (built from the same `main`, containing both fixes) ran and succeeded.
2. **Env var changes never reached already-running pods**, even after ArgoCD showed `Synced`. This chart wires `env:` values through a `ConfigMap` (`envFrom`, not inline literals) — updating the ConfigMap's data is a real, successful sync, but Kubernetes has no mechanism to notice and restart pods just because a ConfigMap they reference changed content (identical mechanism, and identical lesson, to why a `Secret` update doesn't reach running pods either — already documented in this project). Had to `kubectl rollout restart` `auth-dev`, `auth-staging`, `auth-production`, and `api-production` by hand to actually pick up the new `API_URL`/`AUTH_URL` values.

### Bug 37 — shared ingress template's rewrite regex silently broke every root-path service (04/07/2026)

**The symptom:** both free and signed doc conversions got permanently stuck on "Sending file..." in the UI, with no error ever shown, on dev, staging, and prod alike.

**Root cause:** `charts/service/templates/ingress-nginx.yaml` builds its nginx path regex as `{{ .Values.ingress.path }}(/|$)(.*)`. That works fine for a real prefix like `/auth` — `/auth(/|$)(.*)` correctly matches `/auth`, `/auth/`, `/auth/verify`, etc. But the URL restructuring above (same day) set every `api` service's `ingress.path` to `/`, which turns the exact same template into `/(/|$)(.*)` — a regex that only matches the bare root or `//...`, and nothing else. `/convert` and `/jobs/<id>` don't match it at all, since after the leading `/` the pattern demands another literal `/` or end-of-string, and `c` (from "convert") is neither.

**Found by:** tracing the failure from the outside in, not guessing. `aws sqs get-queue-attributes` showed 0 messages on both queues (the job never even reached SQS), the api pod's own logs never showed a `POST /convert` at all (only `GET /`), and the nginx ingress controller's logs showed exactly why: `"POST /convert HTTP/1.1" 404 ... [upstream-default-backend]` — nginx's own routing rule simply never matched the path, so it fell through to the default 404 backend instead of ever reaching the api Service.

**Fix:** root-path services now get `/()(.*)` instead of `/(/|$)(.*)` — same `$2` capture group the shared `rewrite-target: /$2` annotation already relies on, so every other service's behavior is untouched. (`snaPDF-gitops` `fix/root-path-ingress-regex`, PR #7.)

**Also hardened while fixing this:** the frontend's submit handler and `poll()` had zero error handling around `fetch`/`res.json()` — when nginx returned its non-JSON 404 page, `res.json()` threw, the promise rejected unhandled, and the UI just froze on "Sending file..." forever instead of surfacing any error. Wrapped both in try/catch/finally so a future failure of any kind fails visibly instead of silently hanging. (`snaPDF` `fix/convert-error-handling`, PR #27.)

**Verified live:** confirmed broken via the nginx logs above, fixed and confirmed working end-to-end (both free and signed) on dev first; the ingress-template fix (shared chart) was already live on staging automatically once merged; prod confirmed once its own promotion landed (see Bug 38).

### Bug 38 — 03/07's rollback-drill button break was never actually fixed at the source, resurfaced live in prod (04/07/2026)

**The symptom:** after promoting `staging` and `prod` branches to catch up with `main` (a clean fast-forward, ~75 commits, done to demonstrate the dev → staging → production promotion flow), the auth page's Sign In button read **"Sign In BROKEN"** in production.

**Root cause:** the rollback drill exercised for snaPDF #19 (03/07/2026, see that section above) intentionally changed `auth/main.py`'s button text from `Sign In` to `Sign In BROKEN` (commit `ecf541b`) to have something real to roll back. The drill then reverted the **gitops** commit that had bumped dev's image tag to point at that broken build — which rolled dev's *deployment* back to the previous image, but never touched the broken line still sitting in `auth/main.py` on `main` itself. The source-level bug was never fixed forward; it just sat invisible in `main`'s history because nothing had rebuilt directly from that exact commit again — until today's fast-forward promotion rebuilt fresh images straight from `main`'s current tip for `staging` and `prod`, both of which include `ecf541b` unrevoked, shipping the broken text live.

**Fix:** `git revert ecf541b` on `main` (a clean, conflict-free revert — restores `Sign In` exactly) rather than another gitops-only rollback, so the fix actually lives in the source this time and can't resurface on a future promotion. (`snaPDF` `fix/restore-signin-button-text`, PR #29.)

**Second gotcha, same incident:** after merging PR #29 into `main`, the button still showed BROKEN in prod. Cause: merging into `main` only auto-deploys to **dev** via the CI branch mapping — `staging` and `prod` are separate branches that each need their own explicit fast-forward promotion, exactly like Bug 37's fix needed. Re-ran the same `git merge origin/main --ff-only` promotion against both branches, which triggered `ci-auth.yml` (the only service whose source actually changed) and rolled `auth-production` over to the new image. Confirmed this time by actually `curl`-ing `https://snapdf.bond/auth/` and grepping the real rendered button text — not just checking CI/ArgoCD sync status — before calling it fixed.

**Lesson:** a rollback that only repoints a deployed *tag* reference (gitops layer) fixes the symptom on whichever environment you rolled back, but leaves the actual bug permanently baked into the branch's source — a landmine for the next time that branch is promoted or rebuilt from scratch. Fixing forward at the source (or reverting the actual code commit, not just the deployment pointer) is the only way a rollback drill's "fix" survives a later promotion. Also: neither "CI passed" nor "ArgoCD shows Synced" is proof a fix is actually live on a given branch/environment — only checking the live, rendered result is.

**Verified live, all three environments, after both fixes:** `curl` 200 on `{dev,staging}.snapdf.bond/` and `/auth/`, 200 on the new `snapdf.bond/` and `/auth/`, confirmed `prod.snapdf.bond` no longer resolves at all (old CNAME destroyed), and a forged JWT is genuinely rejected (server returns `null`/`null` for username/tier) on both dev and prod's live root pages — not just in unit tests.

### Both dev and prod destroyed simultaneously — four new destroy-time bugs found, 39-42 (05/07/2026)

First real full destroy exercised since yesterday's session added Karpenter, the ArgoCD webhook, and rewrote the ALB-cleanup hook (Bug 36) — all three turned out to have never actually been tested against a live `terragrunt destroy`, and each surfaced a real gap.

**Bug 39 — the `delete_load_balancers` hook's bash script broke over the WSL/Windows quoting boundary, on its very first real run.**
`infra/environments/{dev,prod}/addons/terragrunt.hcl`'s `before_hook` was written in bash (`execute = ["bash", "-c", ...]`). On this Windows machine `bash` resolves to WSL's `bash.exe`, and passing a multi-line script containing nested double-quotes (the `COUNT=$(aws elbv2 describe-load-balancers --query "length(LoadBalancers[?VpcId=='$VPC_ID'])" ...)` command substitution) across the native-Windows-process → WSL boundary corrupted the quoting, producing `bash: -c: line 17: syntax error near unexpected token '('` before a single command in the hook executed — identically on both dev and prod. Nothing had actually been destroyed yet at this point (a failed `before_hook` aborts that module's destroy entirely), confirmed via `aws eks list-clusters` still showing both clusters untouched. **Fix:** rewrote the hook in PowerShell (`execute = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ...]`), removing the WSL hop entirely — matches how `destroy.ps1` itself already talks to AWS/kubectl, so there's no longer a second, different shell in the loop. Applied to both environments, validated with `terragrunt validate`, then proven live on the retry.

**Bug 40 — the GitHub→ArgoCD webhook (added yesterday, infra #25) sped up ArgoCD's self-heal enough to break `destroy.ps1`'s own assumption that a manual `kubectl delete` would "stick" long enough to matter.**
`destroy.ps1`'s Step 1 manually deletes Ingress/LoadBalancer-Service objects *before* Terraform ever runs, as a pre-clean — that always relied on ArgoCD's old ~3min poll interval giving the deletion a window to survive. With the webhook now making sync near-instant, `argocd-application-controller` (still running at that point — it isn't scaled down until later, inside the addons module's own hook) recreated the same Ingress objects within seconds, so Step 3's LB-wait loop kept counting a load balancer that kept coming back and never converged to 0. Confirmed live: `kubectl get ingress -A` showed the objects back at ~5min old, and `argocd-application-controller` still at `1/1`. Not fatal — `destroy.ps1`'s own wait loop is bounded and just moves on after ~4-5 min regardless — but it wastes that whole window fighting a controller that's actively healing what it just deleted. The real fix for this race already existed and just hadn't run yet: the addons module's hook (Bug 39, now working) scales `argocd-application-controller` to 0 **before** deleting anything, so once Terraform's actual destroy reached that point, the Ingress deletion finally stuck for good. Worth revisiting `destroy.ps1`'s own Step 1 to scale ArgoCD down first too, now that sync is fast enough for this race to matter every time.

**Bug 41 — Karpenter-provisioned EC2 instances were orphaned when its Helm release was uninstalled, blocking their own security groups from deleting.**
Same failure shape as the ALB Controller orphaning ALBs (Bug 34/36), this time for compute instead of load balancers: `helm_release.karpenter`'s destroy tears down the controller pod with no chance for it to run its own deprovisioning finalizer against the nodes it had launched. Confirmed both leftover instances were Karpenter's, not the managed node group's, via their `karpenter.sh/nodeclaim`/`karpenter.sh/nodepool` tags. Each instance's still-`running` state kept an ENI attached to its node security group, which then sat `Still destroying...` for 5+ minutes on both dev and prod. **Fix:** terminated both instances directly via `aws ec2 terminate-instances` — same precedent as Bug 28 (disposable compute for a cluster already being torn down, no state manipulation needed). Once each instance genuinely reached `terminated`, its security group deleted within seconds.

**Bug 42 — the implicit EKS "cluster security group" AWS auto-creates alongside a cluster didn't clean up in time, blocking final VPC teardown on both.**
After `aws_eks_cluster.this` destroyed successfully and every Terraform-managed security group was gone, the final `aws_vpc.this` destroy still sat `Still destroying...` for 4+ minutes with zero ENIs anywhere in the VPC (checked directly, empty on both dev and prod). Root cause: EKS silently provisions its own `eks-cluster-sg-snapdf-{dev,prod}-*` security group as a side effect of cluster creation — it's never a resource in Terraform's state (the `aws_eks_cluster` resource doesn't expose it for management), and AWS doesn't always clean it up promptly once the cluster itself is gone. A VPC can't be deleted while any non-default security group still lives in it. **Fix:** confirmed both leftover groups had zero ENI dependencies, then `aws ec2 delete-security-group`'d them directly — both VPCs finished destroying within seconds of that.

**Verified fully clean, both environments, after all four fixes:** `aws eks list-clusters` → `[]`, `aws ec2 describe-vpcs --filters Project=snapdf` → `[]`, `aws rds describe-db-instances` → `[]`. Nothing running, no cost accruing.

### Both dev and prod rebuilt from scratch, one new bug found (43), 05/07/2026

`terragrunt run-all apply` on both `infra/environments/{dev,prod}` in parallel, ~23 minutes each. VPC/EKS/IAM/RDS/S3/SQS and the `addons` module's ArgoCD root bootstrap (infra #17) all applied cleanly and unattended on both — no manual step needed, confirming that automation still holds on a second real rebuild. Prod's full `addons` module (including Route53) completed on the first pass. Dev hit a new bug in the same module.

**Bug 43 — `data "kubernetes_ingress_v1"`'s `.status` read null immediately after the wait script confirmed the same Ingress had a real ALB hostname.**
The `addons` module's `null_resource.wait_for_load_balancers` polls `kubectl get ingress nginx-alb ... -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'` in a loop specifically so Terraform's own `aws_route53_record.app`/`.grafana` (which read the same status via `data "kubernetes_ingress_v1"`) never race the ALB Controller — this is the exact mechanism infra #17 added to prevent the old dev/03-07 and dev+prod/04-07 failures. On dev's rebuild the wait script printed `ALB ready: k8s-ingressn-nginxalb-...` at 10:43:27, but Terraform's own data source read a little over half a second later (10:43:28) got `data.kubernetes_ingress_v1.nginx_alb.status` as `null` anyway — `Error: Attempt to index null value` on both `aws_route53_record.app` and `.grafana`. Everything else in the module (ArgoCD, Karpenter, KEDA, kube-prometheus-stack, postgres-exporter, the ArgoCD Route53 record via a *different* data source `kubernetes_service.argocd`) had already applied successfully; only these two resources, both dependent on the nginx Ingress's status, failed. Prod did not hit this on the same rebuild, run in parallel — points to a genuine flicker in when the ALB Controller's status write actually lands/persists on the Ingress object, not a deterministic ordering bug, so the existing wait loop reduces but doesn't fully eliminate the race.
**Fix:** no code change made — re-ran `terragrunt run-all apply` on dev a second time. Since VPC/EKS/IAM/RDS and most of `addons` were already in state, the retry re-planned only the two orphaned Route53 records (`Plan: 3 to add` — `app["dev"]`, `app["staging"]`, `grafana`) and completed in under a minute. Worth hardening later: either add a short retry/second read inside the `wait_for_load_balancers` script itself before declaring ready, or give the two Route53 resources their own `retry` logic, so a from-zero rebuild doesn't depend on a human noticing and manually re-running apply.

**Verified after the retry:** both `snapdf-dev` and `snapdf-prod` EKS clusters `ACTIVE`; all ArgoCD Applications `Synced`/`Healthy` on both; prod's `https://snapdf.bond` returns `200` with correct `Host`/SNI (confirmed via `curl --resolve` directly against the ALB, bypassing DNS) — though the ALB target group's own AWS health check still reports the single nginx target `unhealthy` (`Target.ResponseCodeMismatch`, health checks failing with `404`) on both envs, because the health check probes `/` without a `Host: snapdf.bond` header and nginx's default backend 404s anything that doesn't match a configured host. Real traffic (correct Host header) works regardless — user confirmed prod reachable in-browser — but this is a pre-existing quirk (not new to this rebuild) worth fixing properly at some point: either add a dedicated `/healthz`-style health check path/ingress rule nginx will always answer 200 on, or point the target group's health check at the ALB Controller's own status port instead of the app path.

### infra #26 — ArgoCD moved off its own dedicated NLB onto the shared ALB (05/07/2026)

**The change:** `helm_release.argocd`'s `server.service.type` changed from `LoadBalancer` to `ClusterIP`, with `server.ingress.enabled` + `configs.params."server.insecure"` turned on so it routes through the same Nginx/ALB every other service already shares — one load balancer per environment instead of two. `aws_route53_record.argocd` repointed from ArgoCD's own LB status to the same `nginx-alb` Ingress data source Grafana/app already read. Removed the now-dead `data.kubernetes_service.argocd` and simplified `wait_for_load_balancers` (no longer needs to wait on ArgoCD's own LB).

**Two real bugs hit getting this working on dev, neither a one-shot clean apply:**

**Bug 45a — Terraform reported success while the Ingress was silently never adopted by nginx.** First apply completed with no errors, the old dedicated NLB genuinely disappeared (confirmed via `aws elbv2 describe-load-balancers` → `LoadBalancerNotFound`) — but `https://argocd-dev.snapdf.bond/` returned a flat `404`. `kubectl describe ingress argocd-server -n argocd` showed `Address:` empty, versus Grafana's working Ingress which shows nginx's real internal ClusterIP there. Root cause: this cluster's nginx controller runs with `--ingress-class=nginx` and no `--watch-ingress-without-class` flag, so it only picks up Ingress objects carrying the **legacy** `kubernetes.io/ingress.class: nginx` annotation — every existing working Ingress here (api-dev, Grafana) relies on exactly that annotation, none use `spec.ingressClassName` (which is why they all show `<none>` under the `CLASS` column yet still work). The argo-cd chart's own ingress template doesn't add this annotation automatically. **Fix:** added `server.ingress.annotations."kubernetes.io/ingress.class" = "nginx"` explicitly.

**Bug 45b — `nginx.ingress.kubernetes.io/backend-protocol: GRPC` broke the web UI entirely.** With the annotation added (to handle the `argocd` CLI's gRPC traffic, which shares the same port as the web UI), the Ingress was adopted (no longer 404) but every request now returned `502 Bad Gateway`. nginx's own error log showed why: `recv() failed (104: Connection reset by peer) ... upstream: "grpc://10.0.3.149:8080"` for an ordinary browser `HEAD /` request — the `backend-protocol: GRPC` annotation makes nginx proxy *every* request through that Ingress using its grpc_pass module, wrapping plain HTTP traffic in gRPC framing the backend doesn't expect, and ArgoCD's server (correctly configured, `configs.params."server.insecure": "true"` confirmed present in `argocd-cmd-params-cm`) resets the connection. **Fix:** removed the `backend-protocol: GRPC` annotation entirely — plain HTTP/HTTPS through nginx like every other Ingress here. Traded away: the `argocd` CLI can no longer speak raw gRPC through this Ingress and needs `--grpc-web` (ArgoCD's own documented fallback for exactly this ingress shape, e.g. `argocd login argocd-dev.snapdf.bond --grpc-web`) — not yet tested, called out as a known gap rather than assumed working.

**Verified on dev:** `curl -I https://argocd-dev.snapdf.bond/` → `200`; `curl https://argocd-dev.snapdf.bond/api/version` → a genuine ArgoCD API response (`{"Version":"v2.10.4+f5d63a5"}`), not just a passing status code. The `argocd` CLI's `--grpc-web` path has not been tested yet.

### Bug 44 — prod's `postgres_exporter` Helm release baked in yesterday's RDS password, not today's (05/07/2026)

**Symptom:** Grafana's custom "snaPDF - Business & Scaling Metrics" dashboard wasn't updating on prod. `kubectl logs` on `postgres-exporter-prometheus-postgres-exporter` showed a wall of `password authentication failed for user "dbadmin"` against `snapdf-prod-rds...`, every 30s.

**Root cause:** `infra/modules/addons/main.tf`'s `helm_release.postgres_exporter` populates its `config.datasource.*` values via `set_sensitive` from `local.db_creds` — `jsondecode(data.aws_secretsmanager_secret_version.db_credentials.secret_string)` — the same consolidated `snapdf-prod/db-credentials` secret the `rds` module keeps in sync with the real, live master password on every apply (the automated fix from Bug 29). By the time this was checked, that consolidated secret's `AWSCURRENT` value was already correct — but the password baked into `postgres-exporter`'s own Kubernetes Secret (`data_source_password`) matched neither the current nor even the previous-previous version: it matched exactly `AWSPREVIOUS` (created 04/07/2026, yesterday's now-destroyed prod instance's password). Terraform's `data` source for this secret was evidently read *before* the `rds` module's write of the fresh password had settled, during this specific apply's single, clean first pass through the `addons` module. Confirmed the theory by comparing dev: dev's `postgres_exporter` connected fine, because dev's `addons` module needed a second, later apply (Bug 43's retry) that incidentally re-read the secret after it had settled — prod succeeded cleanly on one pass and never got that second read.

**Fix:** `terragrunt apply -target=helm_release.postgres_exporter -auto-approve` in `infra/environments/prod/addons` (re-reads the data source, now safely past the staleness window — plan showed `1 to change`, all 3 `set_sensitive` blocks), then `kubectl rollout restart deployment postgres-exporter-prometheus-postgres-exporter -n monitoring` (a Helm/Secret value change doesn't automatically restart pods already using the old value via `secretKeyRef`, same lesson as Bug 24/29). Verified: new pod's logs show `Semantic version changed ... to=16.13.0` — a genuine successful authenticated query, not just "no error yet."

**Not yet fixed at the source** — this data source has no explicit dependency forcing it to read *after* the `rds` module's secret-sync write; it happened to work by luck on `dev` (retry) and fail on `prod` (clean first pass) on the exact same rebuild. Worth adding an explicit ordering guarantee (e.g. a `depends_on` chain, or reading the RDS-managed secret directly by ARN instead of the consolidated one) so this doesn't depend on whether a given apply happens to need a retry.

### Grafana dashboard + ServiceMonitors moved from gitops to a new infra chart, `monitoring-extras` (05/07/2026)

**Decision:** the "snaPDF - Business & Scaling Metrics" Grafana dashboard used to live as a bare `ConfigMap` in `snaPDF-gitops` (`apps/{dev,prod}/grafana-dashboards.yaml`), ArgoCD-applied. Moved it into a new local Helm chart, `infra/modules/addons/charts/monitoring-extras/`, installed by a new `helm_release.monitoring_extras` in the `addons` module — deliberately chosen over gitops specifically so it comes up in the *same* `terragrunt apply` as Prometheus/Grafana itself, with zero dependency on ArgoCD's root bootstrap (the single most bug-prone step in this project's history — infra #17, Bug 29, Bug 43 all live there). The chart also has an (currently empty) `serviceMonitors` values list, ready for the day `api`/`auth` add real `/metrics` instrumentation, so a future custom ServiceMonitor has an obvious home instead of being hand-written directly against the cluster.

**Migration hit exactly the conflict expected going in:** the first `terragrunt apply -target=helm_release.monitoring_extras` on dev failed — `Unable to continue with install: ConfigMap "grafana-dashboard-snapdf-business" ... exists and cannot be imported`, because the object still existed from ArgoCD's last sync and Helm refuses to silently adopt a resource it didn't create. Fixed by committing+pushing the gitops deletion first (`snaPDF-gitops` commit `1ff6c41`), force-refreshing ArgoCD's `root` Application on dev (`kubectl patch application root -n argocd --type merge -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'` — its synced revision was stuck on the pre-deletion commit) to actually prune the ConfigMap, confirming it was gone (`kubectl get configmap ... -> NotFound`), then re-running the apply — succeeded cleanly (`1 added`). Prod didn't need the manual refresh; its `root` Application had already synced to the deletion on its own by the time it was applied.

**Verified on both:** `helm list -n monitoring` shows `monitoring-extras` `deployed` on both clusters; the ConfigMap carries `app.kubernetes.io/managed-by=Helm` (Terraform/Helm-owned now, not ArgoCD); ServiceMonitor count unchanged (15) on dev, confirming the empty `serviceMonitors` list correctly rendered nothing; dashboard confirmed visible via Grafana's own `/api/search` on both `grafana-dev.snapdf.bond` and `grafana-prod.snapdf.bond`.

### infra #27 closed — Karpenter's own controller moved onto a dedicated Fargate profile (06/07/2026)

**The change:** `helm_release.karpenter` moved from the static managed node group (`kube-system`) onto a new `aws_eks_fargate_profile.karpenter`, scoped to its own `karpenter` namespace — a Fargate profile matches by namespace, and `kube-system` also holds CoreDNS/kube-proxy/the VPC CNI, none of which can run on Fargate (kube-proxy needs host networking; the rest are DaemonSets, unsupported on Fargate entirely). Also moved Karpenter's `EC2NodeClass`/`NodePool` manifests from gitops (ArgoCD-applied) into Terraform itself, via a `null_resource` + raw `kubectl apply` (same pattern as the ArgoCD root-bootstrap trick, infra #17) — removes the last piece of Karpenter that depended on ArgoCD sync timing. Same session also finished extracting ArgoCD into its own `argocd` module/environment folder (continuing the split infra #26 started) and moved Grafana's Ingress from gitops into the `observability` module for the same "no ArgoCD dependency" reason.

Tested via a full from-zero rebuild of dev (`terragrunt run-all apply` across all 10 modules, ~25 min) rather than an in-place migration — deliberately, since splitting `addons` into `karpenter`/`argocd`/`observability`/`keda` would otherwise need `terraform state mv` gymnastics across module boundaries; recreating the cluster fresh under the new module layout sidesteps that entirely. All 10 modules applied clean on the first pass (`s3`/`sqs`/`vpc` adopted pre-existing dev resources idempotently, `eks` 42 added, `iam` 23 added, `rds` 3 added, `addons` 8 added, `karpenter`/`argocd` 6 added each, `observability` 11 added, `keda` 1 added) — but the Karpenter controller pod itself came up broken, surfacing two real bugs neither `terraform apply` nor `terraform plan` could have caught, since both are live-cluster networking/auth problems invisible to Terraform's own state.

**Bug 46 — Karpenter's controller had zero CPU/memory requests, fatal specifically on Fargate.** The chart's own default is `resources: {}` — harmless on the managed node group (just uses whatever's free on a node that already exists), but Fargate sizes the entire microVM off the pod's own resource requests; with none set, it came up too small to run the controller at all. Symptom: `0/1 Running`, then `CrashLoopBackOff`, `kubectl logs` returning **completely empty** even after several restarts (the process never got enough scheduled CPU time to flush a single log line before being killed), and readiness/liveness probes cycling through `connection reset by peer` → `connection refused` → `context deadline exceeded` as the container repeatedly started and died. **Fix:** explicit `controller.resources.requests.cpu=1`, `requests.memory=1Gi`, `limits.memory=1Gi` set on `helm_release.karpenter` (`infra/modules/karpenter/main.tf`) — limits match requests since Fargate can't let a pod burst past its sized capacity anyway.

**Bug 47 — the node security group's CoreDNS rule only trusted itself, silently dropping every Fargate pod's DNS query.** Even after fixing Bug 46, the controller kept crash-looping, now with an actual log line: `"ec2 api connectivity check failed" ... "dial tcp: lookup sts.us-east-1.amazonaws.com: i/o timeout"`. Confirmed via a throwaway `busybox` debug pod scheduled onto the same Fargate profile: `nslookup sts.us-east-1.amazonaws.com` → `connection timed out; no servers could be reached`, even though CoreDNS itself was healthy and the route table/NAT gateway/security-group egress were all fine. Root cause, found by comparing ENI security groups directly: the `terraform-aws-modules/eks` module's default `node_security_group_additional_rules` only allows DNS (UDP/TCP 53) **inbound from the node security group itself** (self-referencing) — correct as long as everything needing DNS runs on the managed node group sharing that one SG. Fargate pod ENIs use a completely different SG (AWS's own auto-created implicit "cluster security group", the same one `aws eks describe-cluster` reports as `clusterSecurityGroupId`) — never granted DNS ingress to the node SG at all, so every Fargate pod's DNS query to CoreDNS was silently dropped. **First fix attempt was itself wrong**: tried the module's `source_cluster_security_group = true` shorthand, which turned out to resolve to a *different* SG the module creates internally (`aws_security_group.cluster`), not the AWS-implicit one Fargate actually uses — confirmed by checking the created rule's actual `source_security_group_id` against the Fargate ENI's real SG, they didn't match. **Real fix:** two standalone `aws_security_group_rule` resources in `infra/modules/eks/main.tf` (outside the `module "eks" {}` block — has to be, since the AWS-implicit cluster SG is only exposed via `module.eks.cluster_primary_security_group_id`, an *output*, which can't be fed back in as one of the same module's own *inputs* without a circular reference), explicitly wiring `source_security_group_id = module.eks.cluster_primary_security_group_id` → `security_group_id = module.eks.node_security_group_id` for both TCP and UDP port 53.

**Bug 48 — the Karpenter controller's IAM trust policy still pointed at its old namespace.** Fixing Bugs 46/47 got past the network layer, but `AssumeRoleWithWebIdentity` then came back a real, specific `403 AccessDenied` (progress — a network timeout became an actual API response). Root cause: `infra/modules/iam/main.tf`'s `aws_iam_role.karpenter_controller` trust policy still hardcoded `"${local.oidc_url}:sub" = "system:serviceaccount:kube-system:karpenter"` from before this session's move — the controller's ServiceAccount now lives in `karpenter:karpenter`, not `kube-system:karpenter`, so the real OIDC token's subject claim no longer matched what the trust policy allowed. **Fix:** updated the `StringEquals` condition to `system:serviceaccount:karpenter:karpenter`.

**Verified live, fully end-to-end, not just "pod is Running":** after all three fixes, force-deleted the pod to get a clean restart — came up `1/1 Running`, zero restarts, and its own logs showed it actually *working*, not just alive: discovered AMI SSM parameters, found a genuinely pending pod (`dev/free-worker-dev-...`), computed and created a NodeClaim, launched a real EC2 instance (`t3.small`, `i-0cfb52b1382b2ebe3`), registered and initialized it as a node — and `free-worker-dev`'s pod is confirmed `Running` on that exact node. `NodePool`/`EC2NodeClass` both show `READY: True`. This is the same "launched a real node for a real pending pod, watched it live" bar Karpenter was originally held to on the managed-node-group setup (v0.7.0) — now proven again on Fargate.

### Same migration rolled out to prod (06/07/2026, same day) — but a genuinely bigger job than dev's

**Discovered before touching anything:** prod's `karpenter`/`argocd`/`observability`/`keda` module directories existed (scaffolded by infra #26's earlier split) but had **zero state** — `terragrunt state list` in every one of them came back empty. Every one of those resources (ArgoCD, Karpenter, KEDA, kube-prometheus-stack, postgres-exporter — 19 resources total) was still genuinely live inside the old `addons` module's state on prod. The module split had only ever actually been *completed* for dev, via that from-zero rebuild above; prod's split existed in name only.

**Why this couldn't be dev's "destroy and rebuild from zero" approach:** prod is live, serving real traffic (`https://snapdf.bond`), with ArgoCD, Grafana, and Karpenter's existing NodePool all actively in use. Destroying and recreating any of that for real would mean real downtime and real risk of losing something. So this needed genuine `terraform state mv` surgery — moving each resource's tracked identity into its new module's state file without ever touching the real underlying object.

**Mechanics used** (Terraform's `state mv` only operates within a single state file, so moving resources *between* two different remote states — old `addons`, new `karpenter`/`argocd`/`observability`/`keda` — needs the pull → mv (with explicit `-state`/`-state-out` flags) → push dance): pulled `addons`'s state and each target module's (empty) state locally, ran `terraform state mv -state=addons.tfstate -state-out=<target>.tfstate <addr> <addr>` for all 19 resources (2 → karpenter, 6 → argocd, 10 → observability, 1 → keda), verified the local files looked exactly right (state list on both sides, resource counts matching), then pushed all four target states and the now-trimmed `addons` state back to their real backends. Kept a local backup of the original `addons.tfstate` before starting, as a safety net that was never needed.

**A second surprise, found while planning the imports:** three Kubernetes objects the new module code expects to manage as real resources — the `nginx-alb` Ingress (prod's actual ALB front door), the `grafana` Ingress, and Karpenter's `NodePool`/`EC2NodeClass` — already existed live on prod (created ~24h earlier by the same session that built infra #26), untracked by Terraform *and* absent from gitops. For the two real Ingress objects, used `terraform import` (not dev's "delete from gitops, let ArgoCD prune, let Terraform recreate" approach — deliberately, since a live prod Ingress briefly disappearing could cause a real traffic blip; `import` just tells Terraform "this already exists," no create/destroy at all). For the NodePool/EC2NodeClass, no import was needed or possible — they're managed by a `null_resource` + `kubectl apply`, not typed Terraform resources, and confirmed beforehand that prod's live values (`t3.medium/large/xlarge`, `9` vCPU, `18Gi`) already matched exactly what the committed module would apply, so re-running `kubectl apply` was a guaranteed no-op on the values that matter.

**Verified every plan before applying anything:** post-import, `addons` and `observability` each planned exactly one **in-place** update (new ALB/ingress-class annotations, and dropping a stale `argocd.argoproj.io/instance` label left over from before these objects were adopted into Terraform) — no destroy, no recreate. `argocd` planned one `null_resource` replacement (a `-/+` on `null_resource.argocd_root_bootstrap`, forced by a `recurse: true` addition to the root Application manifest) — confirmed safe since a `null_resource` has no destroy-time provisioner here, so "replace" just means "re-run the idempotent `kubectl apply`" with no real side effect. `keda` planned zero changes.

**Applied in order:** `addons`/`observability`/`argocd`/`keda` first (all landed exactly as planned — `0/1/0/1 to add`, matching predictions precisely), confirmed prod still fully healthy (`https://snapdf.bond` 200, all 7 ArgoCD Applications `Synced`/`Healthy`) before touching anything Karpenter-related. Then `eks` (2 SG rules added) and `iam` (1 changed, the trust policy fix) — both already proven safe on dev. Finally `karpenter` last — this is the one genuinely disruptive step, since changing `helm_release.karpenter`'s namespace forces Terraform to actually destroy the old release (running in `kube-system` on the static node) and install a fresh one on the new Fargate profile. Unlike dev, **prod's Karpenter controller came up healthy on the very first try** — `1/1 Running`, zero restarts, no crash-loop — because all three of Bugs 46-48's fixes were already baked into the shared module code before this apply ever ran; dev had to discover them the hard way, prod just inherited the fix.

**Verified live:** Karpenter's logs show real reconciliation activity within seconds of starting (SSM AMI parameter discovery, controller workers for every reconciler type). The pre-existing `NodePool`/`EC2NodeClass` and the one node they were already managing were completely untouched throughout (`AGE: 26h` unchanged) — confirming the migration only replaced the *controller*, never touched prod's actual running capacity. `https://snapdf.bond` stayed `200` and all ArgoCD Applications stayed `Synced`/`Healthy` through every step. Prod and dev are now structurally identical: same module layout, same Karpenter-on-Fargate setup, same three bug fixes.

### Wildcard DNS for Grafana/ArgoCD, dev only (infra #28 experiment) — and Bug 49, a real self-inflicted outage (06/07/2026)

**The goal:** stop hand-adding a Route53 record every time a new dashboard/admin UI needs a hostname. Restructured Grafana/ArgoCD from flat names (`grafana-dev.snapdf.bond`, `argocd-dev.snapdf.bond`) to nested ones (`grafana.dev.snapdf.bond`, `argocd.dev.snapdf.bond`) under one new `*.dev.snapdf.bond` wildcard CNAME — any future subdomain under `dev` now resolves automatically, no new Terraform resource needed. Deliberately scoped to dev only, and to a **separate** new ACM cert (`dev.snapdf.bond` + SAN `*.dev.snapdf.bond`) rather than adding a SAN to the existing `*.snapdf.bond` cert — extending the existing cert's SAN list forces ACM to reissue it (new ARN, real revalidation), which would have touched every hostname using it, including the main app; a wholly separate cert, added to the shared ALB listener's `certificate-arn` annotation as a second, comma-separated entry, never touches the original cert or its existing coverage at all.

**Bug 49 — a genuinely self-inflicted production-adjacent outage, caused by finishing someone else's correctly-staged-but-never-pushed cleanup.** While wiring the new cert onto `nginx-alb`'s Ingress, the annotation kept reverting to its old single-cert value within about a second of every apply. Traced via `managedFields` to `manager: argocd-controller` actively rewriting the annotation moments after Terraform did — meaning ArgoCD's `root` Application still believed it owned this object, despite no `nginx-alb-ingress.yaml` existing anywhere in the current `snaPDF-gitops` working tree. Root cause, found by checking the *local* gitops checkout's `git status`: three files — `nginx-alb-ingress.yaml`, `grafana-ingress.yaml`, `karpenter-nodepool.yaml` — were already correctly `git rm`'d and **staged**, but that deletion had never actually been committed or pushed. ArgoCD syncs from the real GitHub remote, not any local checkout, so it had been quietly re-applying all three stale manifests via self-heal this entire time — a live, silent fight between Terraform and ArgoCD over resources that had, for all practical purposes, already been "deleted" locally days earlier and simply forgotten before the final `git push`.

**Completing that already-correct staged deletion is what triggered the actual outage.** The moment the commit (`snaPDF-gitops` `0e57e3b`) landed and ArgoCD hard-refreshed, its `syncPolicy.automated.prune: true` did exactly what it's supposed to: deleted every resource no longer in git that it still tracked — which included the live, currently-serving `nginx-alb` Ingress (dev's actual ALB entry point), the Grafana Ingress, and Karpenter's `NodePool`/`EC2NodeClass`. `dev.snapdf.bond` and `staging.snapdf.bond` both went fully unreachable (`curl` timeouts) for the duration of the recovery.

**Recovery, three separate problems stacked on top of each other:**
1. **A genuinely new Terraform/plan-time bug, not the already-documented Bug 43.** Bug 43 was a *timing* race (ALB status not populated microseconds after a real Ingress already existed). This was different: since `nginx-alb` had been fully deleted, Terraform's plan-time evaluation of `data.kubernetes_ingress_v1.nginx_alb` — which the `aws_route53_record.app`/`.wildcard` resources read — returned a hard `null` (the object didn't exist *at all* yet, not just an unpopulated field), and Terraform errored outright (`Attempt to index null value`) instead of deferring gracefully. **Fix:** a targeted apply (`-target=null_resource.wait_for_load_balancers`) to create the Ingress and let a real ALB provision and populate its status *before* the full apply ever tried to read it — once the object genuinely existed with a real status, the normal apply completed cleanly.
2. **Karpenter's NodePool/EC2NodeClass needed a forced replace, not just a re-apply.** Both are created by a `null_resource` + raw `kubectl apply`, which Terraform has no drift detection for — deleting the live objects didn't register as drift Terraform would notice on its own. First recreate attempt (`-replace`) landed on an EC2NodeClass that was still mid-deletion (a lingering finalizer from the original prune) — kubectl reported `ec2nodeclass.karpenter.k8s.aws/default configured` with a `Warning: Detected changes to resource default which is currently being deleted`, and once that already-in-flight deletion actually completed moments later, it silently took the fresh config down with it. A second `-replace`, run only after confirming via `kubectl get` that the object had genuinely finished deleting, succeeded cleanly.
3. **A real, separate, unrelated AWS EC2 API throttling event** (`RequestLimitExceeded ... due to an operational issue`) delayed Karpenter's first node launch for the newly-capacity-starved `free-worker-dev` pod by several minutes — Karpenter's own retry/backoff handled this without any intervention; the pod came up `Running` on a freshly-launched node once AWS's throttling cleared.

**Verified fully recovered:** `dev.snapdf.bond`/`staging.snapdf.bond` both `200`; new hostnames `grafana.dev.snapdf.bond` (`302`, login redirect) and `argocd.dev.snapdf.bond` (`200`) both live on the new wildcard cert; old flat hostnames (`grafana-dev`/`argocd-dev.snapdf.bond`) confirmed fully gone (`000`, no longer resolving — deliberate, not a regression); all 12 ArgoCD Applications `Synced`/`Healthy`, including `free-worker-dev` back to `Healthy`; Karpenter's `NodePool`/`EC2NodeClass` both `READY: True`.

**Also found, separately, not caused by today's work:** the GitHub→ArgoCD instant-sync webhook (infra #25) has actually been silently failing with `400 Bad Request` on every delivery since **2026-07-04**, two days before this session — its last genuinely successful delivery was `2026-07-04T18:01:22Z`. ArgoCD's regular ~180s polling has covered for it invisibly this whole time (confirmed: `root` stayed `Synced` throughout today's incident regardless), so nothing was actually broken end-to-end, just quietly slower than intended. The webhook URL was updated to match the new `argocd.dev.snapdf.bond` hostname as part of this session's work, but the underlying `400` predates that change and needs its own separate investigation — filed as a follow-up, not fixed here.

**Lesson, worth remembering the same way Bug 38 already taught this project once:** a `git status` showing staged-but-uncommitted deletions in a GitOps repo isn't inert housekeeping — if ArgoCD is already silently relying on those files still being absent from a *local* checkout while the *real* remote still has them, finishing the commit is itself a live, prune-triggering action the moment it's pushed, not a cleanup. Worth checking `git log origin/main..HEAD` (or the reverse) before assuming a local working tree matches what any GitOps controller is actually syncing from.

### Bug 49, part 2 — the same prune silently hit prod too, undetected for ~90 minutes (06/07/2026)

**Found during an unrelated full health check.** Bug 49's gitops commit (`0e57e3b`) deleted `apps/prod/nginx-alb-ingress.yaml`, `grafana-ingress.yaml`, and `karpenter-nodepool.yaml` in the exact same push as the dev ones — prod's own independent `root` Application, on its own separate poll cycle (no hard-refresh ever manually triggered there), picked up the same deletion on its own and pruned the same three resources. Unlike dev, nobody was watching prod at the time, so this went unnoticed: `snapdf.bond` had been fully unreachable (DNS pointing at a now-deleted ALB) for roughly 90 minutes before a routine "is everything online" check caught it.

**Recovery followed the same playbook as dev** (targeted apply to recreate `nginx-alb` and let a real ALB provision before anything reads its status, then a full apply for the Route53 records — confirmed `snapdf.bond` back to `200` before doing anything else), then the same for Grafana's Ingress. Two things were different from dev's recovery, though:

1. **The `argocd` module's own Route53 record wasn't part of the addons/observability fix and got missed on the first pass.** `argocd-prod.snapdf.bond` returned `000` (`nslookup`: non-existent domain) even after the main app was back — its CNAME still pointed at the *old* ALB hostname from before `nginx-alb` was recreated, since `aws_route53_record.argocd` lives in a separate module that reads the same Ingress but wasn't re-applied. **Fix:** re-ran `terragrunt apply` in `environments/prod/argocd`, which picked up the new ALB hostname automatically.
2. **Karpenter's NodePool and EC2NodeClass were both genuinely stuck mid-deletion**, not just deleted-and-recreatable. Both had lingering finalizers from the original prune — `karpenter.k8s.aws/termination` on the EC2NodeClass, and Kubernetes' own `foregroundDeletion` on the NodePool — that never cleared, because Karpenter's own disruption controller couldn't proceed (it treats a "terminating" NodeClass as `not found`, so it could never safely finish deprovisioning the one real node still referencing it, which blocked the finalizer, which kept the NodeClass terminating — a self-inflicted deadlock, not a genuine safety condition). Confirmed safe to intervene: the underlying EC2 instance and its running pod (`auth-production`) don't depend on the NodeClass object's continued existence for their own operation, only Karpenter's ability to launch *new* capacity does. Manually cleared both finalizers (`kubectl patch ... -p '{"metadata":{"finalizers":[]}}'`), confirmed the existing node/pod were completely undisturbed, then recreated fresh via Terraform's `-replace`. A restart of Karpenter's own controller pod was also needed afterward — even after the fresh NodePool existed and showed `READY: True`, Karpenter's own logs kept reporting `"no nodepools found"` for several minutes (its watch/list view apparently never recovered cleanly from the object being deleted-and-recreated under the same name); a plain pod restart resolved it immediately.

**Verified fully recovered:** all of `snapdf.bond`, `/auth/`, `grafana-prod.snapdf.bond`, and `argocd-prod.snapdf.bond` back to `200`/`302`; all 7 prod ArgoCD Applications `Synced`/`Healthy`; the two pods that had been `Pending` for 90+ minutes (`api-production`, `auth-production` second replicas) scheduled successfully onto a freshly Karpenter-launched node within seconds of the fix landing.

**New lesson on top of Bug 49's first one:** a gitops commit doesn't just affect whichever environment prompted it — if dev and prod share one repo with per-environment ArgoCD Applications polling independently, a single push can trigger the identical prune on *every* environment reading that repo, each on its own schedule, with no natural way to notice the second one happened unless something is actively checking. Worth treating a gitops push that resolves a dev-side ArgoCD conflict as a signal to check prod too, not just watch the environment you were actually working on.
