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

### 3. t3.small nodes for EKS
**Decision:** Use `t3.small` EC2 instances (2 vCPU, 2GB RAM) for the EKS node group.
**Why:** Cost. t3.small is ~$15/month per node. The cluster runs 2 nodes by default and scales to 3 max. This is enough for the demo app, 4 addon pods (ALB controller, ESO, ArgoCD, KEDA), and 2 worker pods. For a real production workload we'd use t3.medium or larger.

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

---

## Secrets

> To be documented when ESO ClusterSecretStore and ExternalSecret are configured.

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

### Bug 5 — IAM applied before SQS and S3
- **Error:** `Unknown variable` on `dependency.sqs.outputs.signed_queue_arn` in `dev/iam/terragrunt.hcl`
- **Cause:** The IAM module references SQS and S3 dependency outputs. When those modules haven't been applied yet, their state files don't exist in S3, so Terragrunt can't resolve the outputs.
- **Fix:** Apply SQS and S3 before IAM. The `mock_outputs` in the dependency blocks only work for `plan` and `validate`, not for `apply`.
