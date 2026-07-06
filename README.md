# snaPDF

## Overview
This repository contains the application layer of snaPDF: the source code
for the three Python microservices (api, auth, worker), their unit tests,
their Dockerfiles, and the CI pipelines that build them.

## Structure

    snaPDF/
    ├── api/
    │   ├── app.py               # Upload UI + job intake service (Flask)
    │   ├── Dockerfile           # Two-stage build on python:3.11-slim
    │   ├── requirements.txt
    │   └── tests/
    │       └── test_app.py      # Tier routing, upload validation, job status
    ├── auth/
    │   ├── main.py              # Registration/login + JWT issuance (Flask)
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── tests/
    │       └── test_main.py
    ├── worker/
    │   ├── worker.py            # SQS consumer + LibreOffice conversion
    │   ├── Dockerfile           # Only image that ships LibreOffice
    │   ├── requirements.txt
    │   └── tests/
    │       └── test_worker.py   # Job state machine, queue→table mapping
    ├── .github/
    │   └── workflows/
    │       ├── ci-api.yml       # One pipeline per service,
    │       ├── ci-auth.yml      # each triggered only by changes
    │       └── ci-worker.yml    # under its own directory
    ├── .flake8                  # Lint config used by CI
    └── README.md

Each service directory is self-contained and identically shaped: one source
file, its dependencies, a Dockerfile, and a test suite. A service can be
built, tested, and shipped without touching anything outside its folder —
which is exactly what the path-filtered CI workflows rely on.

## Microservices
**api** — Flask. The front door: serves the upload page, validates the
file, stores it in S3, writes a job row to PostgreSQL, and routes the job
to the right SQS queue — valid JWT → signed queue, missing/invalid/forged
token → free queue. Also serves job-status polling (returns the download
URL when done) and `/health` for Kubernetes probes.
Built with: Flask, boto3 (S3/SQS), psycopg2, PyJWT.

**auth** — Flask. Accounts and tokens: registration and login against
PostgreSQL, bcrypt-hashed passwords, issues the JWTs that api verifies.
The two services never call each other on the hot path — they just share
the signing secret (delivered via External Secrets Operator).
Built with: Flask, bcrypt, PyJWT, psycopg2.

**worker** — plain Python loop, no web framework. The conversion engine:
long-polls SQS, downloads the upload from S3, converts it to PDF with
headless LibreOffice (60s timeout), uploads the result, and marks the job
`done` — or `failed` on any exception. One codebase, deployed twice
(`free-worker` / `signed-worker`): env vars select the queue and the DB
table, so tiers are isolated at runtime without duplicating code. The only
image that ships LibreOffice, and the one KEDA scales from one on queue
depth.
Built with: boto3, psycopg2, subprocess → LibreOffice.

## Dockerfiles
All three services share one Dockerfile pattern — a two-stage build on
`python:3.11-slim`:

    FROM python:3.11-slim AS builder        # stage 1: build
    WORKDIR /install
    COPY requirements.txt .
    RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

    FROM python:3.11-slim                   # stage 2: runtime
    WORKDIR /app
    COPY --from=builder /install /usr/local
    COPY app.py .
    CMD ["python", "app.py"]


## Tests
Every CI pipeline runs pytest before any image is built — a failing test
means no image, no deploy. External boundaries (boto3, psycopg2) are
mocked, so the suites exercise service logic, run in milliseconds, and
need no AWS account or database:

    pip install -r api/requirements.txt
    pytest api/tests/ -v

**api** (13 tests) — the most heavily tested service, because it holds the
security-sensitive logic. The core of the suite is the tier-routing matrix:

- valid JWT → job goes to the **signed** queue
- no token → **free** queue
- invalid/expired token → **free** queue (graceful downgrade, no error)
- **forged JWT** (bad signature) → payload is *not* trusted, treated as free

plus upload validation (missing file → 400, wrong file type → 400), job
status responses (pending / done with download URL / failed), and
`/health`.

**worker** (3 tests) — pins the job state machine: a processed message
inserts `pending` and ends `done`; any exception during conversion marks
the job `failed` (never lost silently); and `QUEUE_TYPE=free` writes to
`free_jobs` — the mapping that keeps the two tiers' data separate.

**auth** — placeholder only; real coverage (register/login flows, wrong
password, duplicate user, token contents) is the known next step.

## Environment Variables
All configuration enters through the environment — nothing is hardcoded,
and no config files ship in the images. In the cluster, non-secret values
are injected by the Helm chart's ConfigMap, secrets arrive via External
Secrets Operator from AWS Secrets Manager, and AWS API access (S3, SQS)
needs no variables at all — it's IRSA, so boto3 picks up credentials from
the pod's service account.

### api

| Variable | Purpose |
|---|---|
| `SIGNED_QUEUE_URL` | SQS queue for authenticated (signed-tier) jobs |
| `FREE_QUEUE_URL` | SQS queue for anonymous (free-tier) jobs |
| `S3_BUCKET` | Bucket for uploaded files and converted outputs |
| `JWT_SECRET` | HMAC secret used to *verify* tokens issued by auth |
| `AUTH_URL` | Public URL of the auth service, for login/register links |
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` | PostgreSQL (RDS) connection |
| `DB_NAME` | Logical database — defaults to `snapdf` |

### auth

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | Same secret as api — auth *signs*, api *verifies* |
| `API_URL` | Public URL of api, to redirect users back after login |
| `DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | PostgreSQL connection (users table) |

### worker

| Variable | Purpose |
|---|---|
| `QUEUE_URL` | The one queue this deployment polls |
| `QUEUE_TYPE` | `signed` or `free` — selects the DB table (`signed_jobs` / `free_jobs`) |
| `S3_BUCKET` | Download source (uploads/) and result target (outputs/) |
| `DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | PostgreSQL connection |

Two variables define the whole deployment model: `QUEUE_URL` + `QUEUE_TYPE`
are what turn one worker codebase into two independent deployments —
`free-worker` and `signed-worker` differ *only* in these values, set per
environment in the gitops repo.

Required variables are read with `os.environ[...]` and crash the service
at startup if missing (fail-fast); only genuinely optional ones
(`DB_NAME`, `AUTH_URL`/`API_URL`) have defaults via `.get()`.
## CI
One workflow per service — `ci-api.yml`, `ci-auth.yml`, `ci-worker.yml` —
identical in shape, each triggered only by pushes touching its own
directory (`paths: 'api/**'` etc.). Changing the worker never rebuilds the
api; a commit touching two services runs two pipelines in parallel.

The pipeline, in order:

1. **Lint** — flake8 (max line length 120). Style errors fail the build.
2. **Unit tests** — pytest. A red test means no image is ever built.
3. **Build & push** — the Docker image is built and pushed to its ECR
   repository, tagged with the commit SHA (`snapdf-api:<sha>`). No
   `latest`, no version guessing: the tag running in the cluster is the
   exact commit that produced it.
4. **Deploy — by commit, not by kubectl** — the workflow clones
   snaPDF-gitops, updates `image.tag` in that service's values file for the
   target environment, and pushes the commit. ArgoCD notices (webhook) and
   rolls out. CI has no cluster credentials at all — its only power is
   writing to a git repo.

The target environment is selected by branch:

| Branch | Environment (values file updated) |
|---|---|
| `main` | dev |
| `staging` | staging |
| `prod` | production |

so promotion between environments is a git operation — merge to `staging`,
the same pipeline points the same image process at the staging values.

**Authentication:** AWS access uses GitHub OIDC (`id-token: write` +
`role-to-assume`) — the workflow exchanges a short-lived GitHub token for
temporary AWS credentials, so no AWS keys are stored in the repo. The only
long-lived secret is `GITOPS_TOKEN`, scoped to pushing the tag-bump commit
to the gitops repo.


