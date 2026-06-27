# ProjectView — DevOps Engineer Assessment

## Project Goal
Build a production-grade cloud infrastructure for a DevOps job interview assessment.
Demonstrate proficiency in IaC, Kubernetes, GitOps, CI/CD, and secrets management.

## Current State (v0.1.0)
- Phase 0 and Phase 1 complete — all infrastructure deployed in dev
- Hello World Flask app deployed to EKS and accessible via ALB in browser
- Next: Phase 2 — full Flask PDF app + workers + GitHub Actions CI

## Three Repos
- **ProjectView** — Flask app code, Dockerfile, CI pipeline, docs (this repo)
- **ProjectView-infra** — Terraform modules + Terragrunt configs for dev/prod
- **ProjectView-gitops** — Helm charts + ArgoCD apps (to be created in Phase 3/4)

## Actual Architecture

### App
- **Web server** — Flask app: accepts PDF conversion requests, routes to signed or free SQS queue
- **signed-worker** — reads signed queue, converts HTML→PDF with WeasyPrint, uploads to S3, saves metadata to RDS
- **free-worker** — reads free queue, same processing, fixed 1 pod (no autoscaling)
- **KEDA** — watches signed queue depth, scales signed-worker from 0 to 3 pods
- **Priority pattern** — signed (paying) users get burst capacity, free users get steady 1-pod throughput

### Infrastructure (all in us-east-1)
- **VPC** — 3-tier: public (ALB/NAT), private (EKS nodes), database (RDS)
- **EKS** — cluster `projectview-dev`, t3.small nodes, min=1 max=3 desired=2
- **RDS** — PostgreSQL 15, stores PDF job metadata (user, s3_key, status)
- **SQS** — two queues: `projectview-dev-signed` and `projectview-dev-free`
- **S3** — private bucket for storing generated PDFs, served via presigned URLs
- **ECR** — `projectview-app` repository, images tagged by git SHA
- **Secrets Manager** — DB password + API key (`projectview/api-key`)
- **IAM roles (IRSA)** — alb-controller, eso, keda, worker

### Addons (installed via Helm in addons Terragrunt module)
- **ALB Ingress Controller** — creates AWS load balancers from Ingress resources
- **External Secrets Operator (ESO)** — syncs Secrets Manager into K8s secrets
- **ArgoCD** — GitOps CD, App of Apps pattern
- **KEDA** — event-driven autoscaler watching SQS

## Versioning
Tags follow `vMAJOR.MINOR.PATCH`. Current: `v0.1.0` (Hello World deployed).
`v1.0.0` = fully working PDF app with CI/CD and GitOps end to end.
Tell the user when a version is tagged.

## Shutdown / Startup

### Shutdown (end of day — saves ~$160/month)
```bash
# 1. Delete test resources if any
kubectl delete deployment hello
kubectl delete svc hello

# 2. Destroy all infrastructure
cd C:\Users\USER\ProjectView-infra\infra\environments\dev
terragrunt run-all destroy
```

### Startup (next day)
```bash
# 1. Rebuild all infrastructure (~40 min)
cd C:\Users\USER\ProjectView-infra\infra\environments\dev
terragrunt run-all apply

# 2. Reconnect kubectl
aws eks update-kubeconfig --region us-east-1 --name projectview-dev
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
- Infra hotfixes can go directly to main in ProjectView-infra
- Tag versions on ProjectView repo only, not infra repo

## AWS Account
- Account ID: `086241318869`
- Region: `us-east-1`
- ECR URI: `086241318869.dkr.ecr.us-east-1.amazonaws.com/projectview-app`
- State bucket: `projectview-tf-state-086241318869`
- EKS cluster: `projectview-dev`
