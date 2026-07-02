# snaPDF — DevOps Engineer Assessment

## Project Goal
Build a production-grade cloud infrastructure for a DevOps job interview assessment.
Demonstrate proficiency in IaC, Kubernetes, GitOps, CI/CD, and secrets management.

## Current State (v0.7.0)
- **Milestone reached 02/07/2026: Karpenter fully working on both dev and prod**
  (this is the "Karpenter done" milestone from the original versioning plan). Node
  autoscaling replaces the "human notices a scheduling failure, manually runs Terraform"
  loop that happened 3 times today with automatic provisioning: Karpenter watches for
  `Pending` pods and launches right-sized nodes on its own, then cleanly terminates
  them once idle. Verified live on both clusters, both directions (scale-up and
  scale-down), with real test pods, not just installed-and-assumed-working.
  Dev capped at 6 vCPU/12GiB (`t3.micro`-`medium`); prod at 9 vCPU/18GiB
  (`t3.medium`-`xlarge`, sized for prod's heavier per-pod memory needs, not just
  scaled up from dev's numbers). Found and fixed 2 real bugs along the way: Karpenter
  v1's `EC2NodeClass` requires explicit `amiSelectorTerms` (not just `amiFamily`), and
  Karpenter's separately-created node role needed its own EKS access entry to actually
  join the cluster (the managed node group's role gets this automatically; a
  Karpenter-launched node doesn't). Original managed node group intentionally left
  unshrunk for now — Karpenter installed *alongside* existing capacity, not replacing
  it yet, until a deliberate decision to shrink it.

- **Infra #18 closed, 02/07/2026:** real ALB now sits in front of Nginx on both dev and
  prod — Nginx switched to `ClusterIP` (no longer creates its own load balancer), a new
  `Ingress` (`ingressClassName: alb`) routes real traffic instead, and DNS repointed at
  the ALB. Done in two safe phases (new ALB provisioned and verified *before* touching
  Nginx's existing setup) so there was no downtime window. Unblocks infra #19 (TLS).
  Also caught and fixed a real process gap: 16 files of already-applied infra changes
  (staging isolation, prefix delegation, this ALB switchover) had never been committed —
  committed retroactively in 3 logical commits matching their documentation entries.
- **Prod's pod-density ceiling fixed, 02/07/2026 (Bug 32):** both dev's and prod's nodes
  now use AWS VPC CNI prefix delegation (raises the per-node pod ceiling from 17 to 100+,
  capped deliberately at `maxPods: 35`) instead of the default one-IP-per-pod scheme that
  was silently limiting `t3.medium` to 17 pods/node regardless of spare CPU. `signed-worker-
  production`, which had never successfully scheduled before this, is now Running.
  VPC CNI also formally brought under Terraform management for the first time.
- **Staging fully isolated from dev, 02/07/2026 (Bug 31):** staging previously shared every
  AWS resource with dev (SQS queues, S3 bucket, JWT secret, and even the same database) —
  now has its own `snapdf-staging-signed`/`free` queues, `snapdf-staging-pdfs-...` bucket,
  `snapdf-staging/jwt-secret`, and its own `snapdf_staging` database (a second logical
  database on the same RDS instance, not a new one — kept cost at zero). `infra/modules/sqs`
  and `s3` refactored to create one set of resources per namespace (`app_namespaces`
  pattern, same as Bug 30's IAM fix); `iam`'s KEDA/worker policies updated to grant
  permissions on all of them. Verified live: new pods confirmed with correct env vars
  (not just ArgoCD Synced), KEDA's signed-worker-staging watches its own queue specifically.
- **Milestone reached 02/07/2026: prod is fully up and serving real traffic end-to-end**
  (this is the "prod fully up" milestone originally planned as v0.6.0 back on 01/07 — the
  exact version number drifted since patches kept incrementing the minor version instead
  of the patch, but the milestone itself landed today under v0.6.5)
- Phases 0-3 complete, Phase 4 dev environment fully hardened and verified,
  plus an in-progress spec-compliance pass against the actual requirements doc
  (Desktop/Infrastructure_Deployment_Task.pdf): ArgoCD RBAC/AppProject split,
  ConfigMap added to chart, prod->production namespace rename, per-env resource limits
- Dev AND prod infra are both live — both clusters have Ready nodes (prod upgraded
  t3.small -> t3.medium, matching dev, Bug 30), independent healthy ArgoCD instances
  each reading only their own cluster's ApplicationSets (`apps/dev` vs `apps/prod`
  split, infra #23 closed — no more cross-cluster Application generation)
- ResourceQuota per namespace added via new generic `charts/env-scoped` chart (gitops #6, closed)
- Prod-specific secrets, per-environment ingress hosts on the purchased domain
  `snapdf.bond` + Route53, and prod's own root ArgoCD bootstrap are all live and
  verified: `curl http://prod.snapdf.bond/api/` and `/auth/` both return 200, all 5
  production pods Running, KEDA signed-worker ScaledObject READY:True (infra #21,
  gitops #4 both closed; Bug 30's IAM trust-policy gap, found only once prod's pods
  actually started, also fixed)
- Issue tracker cleanup done (v0.6.2): closed 21 stale planning issues across app and
  infra repos that were already implemented in earlier phases
- Next: infra #17 (automate ArgoCD root bootstrap so this manual step isn't needed for
  future clusters), then remaining "IMPORTANT ISSUE" spec-compliance gaps (ALB/TLS,
  rollback drill, README, architecture diagram)

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
