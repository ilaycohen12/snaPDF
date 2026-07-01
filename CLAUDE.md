# snaPDF — DevOps Engineer Assessment

## Project Goal
Build a production-grade cloud infrastructure for a DevOps job interview assessment.
Demonstrate proficiency in IaC, Kubernetes, GitOps, CI/CD, and secrets management.

## Current State (v0.6.1)
- Phases 0-3 complete, Phase 4 dev environment fully hardened and verified,
  plus an in-progress spec-compliance pass against the actual requirements doc
  (Desktop/Infrastructure_Deployment_Task.pdf): ArgoCD RBAC/AppProject split,
  ConfigMap added to chart, prod->production namespace rename, per-env resource limits
- Next: remaining spec-compliance issues (see GitHub issue trackers across all 3
  repos, titled "IMPORTANT ISSUE"), then prod apply + register + webhook → v0.6.0

## Three Repos
- **snaPDF** — Flask app code, Dockerfile, CI pipeline, docs (this repo)
- **snaPDF-infra** — Terraform modules + Terragrunt configs for dev/prod
- **snaPDF-gitops** — Helm charts + ArgoCD apps (to be created in Phase 3/4)

## Actual Architecture

### App
- **Web server** — Flask app: accepts PDF conversion requests, routes to signed or free SQS queue
- **signed-worker** — reads signed queue, converts HTML→PDF with WeasyPrint, uploads to S3, saves metadata to RDS
- **free-worker** — reads free queue, same processing, fixed 1 pod (no autoscaling)
- **KEDA** — watches signed queue depth, scales signed-worker from 0 to 3 pods
- **Priority pattern** — signed (paying) users get burst capacity, free users get steady 1-pod throughput

### Infrastructure (all in us-east-1)
- **VPC** — 3-tier: public (ALB/NAT), private (EKS nodes), database (RDS)
- **EKS** — cluster `snapdf-dev`, t3.small nodes, min=1 max=3 desired=2
- **RDS** — PostgreSQL 15, stores PDF job metadata (user, s3_key, status)
- **SQS** — two queues: `snapdf-dev-signed` and `snapdf-dev-free`
- **S3** — private bucket for storing generated PDFs, served via presigned URLs
- **ECR** — `snapdf-app` repository, images tagged by git SHA
- **Secrets Manager** — DB password + API key (`snapdf/api-key`)
- **IAM roles (IRSA)** — alb-controller, eso, keda, worker

### Addons (installed via Helm in addons Terragrunt module)
- **ALB Ingress Controller** — creates AWS load balancers from Ingress resources
- **External Secrets Operator (ESO)** — syncs Secrets Manager into K8s secrets
- **ArgoCD** — GitOps CD, App of Apps pattern
- **KEDA** — event-driven autoscaler watching SQS

## Versioning
Tags follow `vMAJOR.MINOR.PATCH`, on the `snaPDF` app repo only (never on infra/gitops repos).
Each `v0.x.0` = one major phase/milestone genuinely complete and verified — not just code written.

| Tag | Milestone |
|---|---|
| v0.1.0 | Phase 0+1 — bootstrap + all infra modules deployed |
| v0.2.0 | Phase 2 — full PDF converter app + CI pipeline |
| v0.3.0 | Phase 3 — Helm chart + CI restructure + GitOps handoff |
| v0.4.0 | Phase 4 dev — ArgoCD wired, initial end-to-end flow verified (30/06/2026) |
| v0.5.0 | Phase 4 dev hardened — KEDA genuinely autoscaling (Bug 24), ArgoCD service drift fixed (Bug 23), IAM file/live drift fixed (Bug 25) — same app commit as v0.4.0, but the surrounding infra/gitops state is now actually solid, not just "looked working" |
| v0.6.0 | Prod environment fully up (Phase 4 100% complete — steps 11-13) |
| v0.7.0 | Karpenter (Phase 6) done |
| v0.8.0 | Observability / Grafana (Phase 5) done |
| v1.0.0 | **Final release** — all tests passing + README finalized + applied — redefined 01/07/2026 |

**Patch versions track in-progress work within the current phase** — e.g. once at v0.5.0, incremental changes while building toward prod (v0.6.0) get tagged v0.5.1, v0.5.2, etc. Once the next milestone (v0.6.0) is actually reached, jump straight to it — patch numbers reset per minor version, they don't count up forever.

Proactively suggest tagging (and update this table) whenever a phase milestone or a meaningful in-phase change is reached — don't wait to be asked.

## Shutdown / Startup

### Shutdown (end of day — saves ~$160/month)
```bash
# 1. Delete test resources if any
kubectl delete deployment hello
kubectl delete svc hello

# 2. Destroy all infrastructure
cd C:\Users\USER\snaPDF-infra\infra\environments\dev
terragrunt run-all destroy
```

### Startup (next day)
```bash
# 1. Rebuild all infrastructure (~40 min)
cd C:\Users\USER\snaPDF-infra\infra\environments\dev
terragrunt run-all apply

# 2. Reconnect kubectl
aws eks update-kubeconfig --region us-east-1 --name snapdf-dev
```

## Key Decisions (summary)
- Terragrunt over plain Terraform — DRY config for dev/prod
- t3.small nodes — cost saving for demo
- Two SQS queues — priority processing (signed vs free users)
- KEDA only on signed queue — free worker always 1 pod
- PDF generation — justifies queue + worker + S3 + DB all at once
- ECR over GHCR — same AWS account, no extra credentials needed
- No Route 53 / CloudFront — not needed for demo
- `wait = false` on Helm releases — avoids timeout on small nodes
- Always annotate LB services with `service.beta.kubernetes.io/aws-load-balancer-scheme=internet-facing`

## Working Instructions
- Explain every CLI command — what it does and why we need it now
- Teach step by step — the user wants to understand everything
- Update `documentation.md` after every significant step or decision
- Update `progress.md` with dates after every completed step
- Follow branch workflow: issue → branch (`type/description`) → PR → merge → tag if milestone
- Never push directly to main for app code — always branch + PR
- Infra hotfixes can go directly to main in snaPDF-infra
- Tag versions on snaPDF repo only, not infra repo

## AWS Account
- Account ID: `086241318869`
- Region: `us-east-1`
- ECR URI: `086241318869.dkr.ecr.us-east-1.amazonaws.com/snapdf-app`
- State bucket: `snapdf-tf-state-086241318869`
- EKS cluster: `snapdf-dev`
