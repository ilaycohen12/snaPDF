# snaPDF — DevOps Engineer Assessment

## Project Goal
Build a production-grade cloud infrastructure for a DevOps job interview assessment.
Demonstrate proficiency in IaC, Kubernetes, GitOps, CI/CD, and secrets management.

## Current State (v1.0.3)
- **Wildcard DNS for Grafana/ArgoCD (dev only), 06/07/2026 — and Bug 49, a real self-inflicted outage.** New nested hostnames (`grafana.dev.snapdf.bond`, `argocd.dev.snapdf.bond`) under one `*.dev.snapdf.bond` wildcard + a separate new ACM cert, replacing the flat `grafana-dev`/`argocd-dev` per-service records. While wiring this up, discovered `snaPDF-gitops` had 3 files (`nginx-alb-ingress.yaml`, `grafana-ingress.yaml`, `karpenter-nodepool.yaml`) correctly `git rm`'d and staged **locally** but never actually committed/pushed — since ArgoCD syncs from the real GitHub remote, it had been silently self-healing all three stale manifests back this whole time, fighting Terraform. Pushing that already-correct staged deletion (the right thing to do) triggered ArgoCD's `prune: true` to actually delete the live `nginx-alb` Ingress (dev's real ALB entry point), Grafana's Ingress, and Karpenter's NodePool/EC2NodeClass — a real outage (`dev`/`staging.snapdf.bond` both unreachable) as a direct side effect. Fully recovered: found and fixed a new plan-time Terraform bug (reading a data source against a *fully deleted*, not just newly-created, object — different from the already-documented Bug 43), used a targeted apply to sequence the ALB's creation before anything read its status, and force-replaced Karpenter's null_resource-managed objects (hitting a mid-deletion-finalizer race on the first attempt). Also surfaced, unrelated to today: the ArgoCD instant-sync webhook has been silently returning `400` on every delivery since 2026-07-04 — not fixed, filed as a separate follow-up. Full writeup (Bug 49) in documentation.md. Verified fully recovered: both apps `200`, both new hostnames live, old ones confirmed gone, all 12 ArgoCD Applications `Synced`/`Healthy`, Karpenter `NodePool`/`EC2NodeClass` both `READY: True`.
- **Prod migrated onto the same Karpenter-on-Fargate/module-split structure as dev, 06/07/2026, same day.** Turned out to be a bigger job than dev's: prod's `karpenter`/`argocd`/`observability`/`keda` module directories existed but had zero state (the addons→module split from infra #26 was only ever completed for dev). Since prod is live and serving real traffic, this needed genuine `terraform state mv` surgery (pull/mv/push across each module's remote state, 19 resources relocated) rather than dev's destroy-and-rebuild approach, plus `terraform import` for 3 Kubernetes objects (the live `nginx-alb`/`grafana` Ingresses, prod's actual ALB front door) that existed already but were untracked. Every plan verified before applying — zero unexpected destroys. Karpenter's controller itself came up `1/1 Running` on the very first try (no crash-loop, unlike dev) since all 3 bug fixes below were already baked into the shared module code. Prod's pre-existing NodePool/node were completely untouched throughout; `https://snapdf.bond` stayed `200` the whole time. Prod and dev are now structurally identical.
- **Infra #27 closed, 06/07/2026: Karpenter's own controller moved onto a dedicated Fargate profile (dev first, then prod same day).** Also finished extracting ArgoCD into its own module (continuing infra #26's split) and moved Grafana's Ingress + Karpenter's EC2NodeClass/NodePool from gitops into Terraform. Dev tested via a full from-zero rebuild rather than an in-place migration (avoids `terraform state mv` across the new module boundaries). Found and fixed 3 real bugs invisible to `terraform plan` (live-cluster networking/auth issues, not state drift): Karpenter's controller had no CPU/memory requests (fatal on Fargate specifically — chart default `resources: {}` is fine on a real node, not on a sized microVM); the node security group's CoreDNS rule only trusted itself, silently dropping every Fargate pod's DNS query (fixed with two standalone `aws_security_group_rule` resources pointed at the *actual* AWS-implicit cluster SG, not the module's own same-named-but-different SG); and Karpenter's IAM trust policy still pointed at `kube-system`, not its new `karpenter` namespace. Full writeup in documentation.md. Verified live end-to-end on both envs, not just "pod is Running": Karpenter found a genuinely pending pod, launched a real EC2 instance, and that pod is confirmed running on it.
- **Both dev and prod rebuilt from scratch and currently ACTIVE, 05/07/2026 late morning.** `terragrunt run-all apply` on both environments in parallel, ~23 min each. Prod's `addons` module (ArgoCD, Karpenter, KEDA, monitoring, Route53) completed clean on the first pass. Dev hit a new bug (43) on the last 2 Route53 records — `data "kubernetes_ingress_v1"`'s `.status` read `null` a fraction of a second after the `wait_for_load_balancers` script itself confirmed the same Ingress had a real ALB hostname; fixed by simply re-running `terragrunt run-all apply` once more (state already had everything else, so it just picked up the 2 orphaned records in under a minute). Full writeup in documentation.md. Verified: both EKS clusters `ACTIVE`, all ArgoCD Applications `Synced`/`Healthy` on both, prod confirmed reachable live at `https://snapdf.bond`. One pre-existing quirk noticed (not new, not blocking): the ALB target group's own AWS health check reports the single nginx target `unhealthy` (404) on both envs because the health-check probe doesn't send a `Host: snapdf.bond` header and nginx's default backend 404s anything host-unmatched — real traffic with the correct Host header works fine regardless. Worth fixing properly at some point (dedicated health-check path/ingress rule).
- **Both dev and prod destroyed simultaneously, 05/07/2026 morning — first real destroy since Karpenter/webhook/Bug-36's hook rewrite, all three turned out untested against a live teardown.** Found and fixed 4 new destroy-time bugs (39-42): the ALB-cleanup hook's bash script broke over the WSL/Windows quoting boundary (rewritten in PowerShell); the new instant-sync webhook raced `destroy.ps1`'s manual Ingress cleanup faster than ArgoCD's old poll interval ever could; Karpenter-provisioned EC2 instances got orphaned when its Helm release was uninstalled before they could self-terminate; and AWS's own implicit EKS cluster security group didn't clean up in time, blocking final VPC teardown on both. Full writeup in documentation.md.
- **Infra #17 closed, 04/07/2026, v0.8.1: ArgoCD's root Application bootstrap automated end-to-end.**
  Previously the one manual step left in the whole system — `kubectl apply -f
  infra/bootstrap/root-app{,-prod}.yaml` — had to be run by hand after every fresh
  cluster stand-up, using the right file for the right cluster. Automated via a
  `null_resource` + `local-exec` in the `addons` module that inlines the manifest and
  picks the path (`apps/dev` vs `apps/prod`) by `var.env_name`, so there's no file to
  remember or mismatch (the old `infra/bootstrap/*.yaml` files were deleted — one
  source of truth now, not two). A second `null_resource` polls until the ALB
  Controller has actually provisioned real load balancer hostnames for `nginx-alb`
  and `argocd-server` before Terraform's Route53 records try to read them, replacing
  the targeted-apply → manual-bootstrap → wait → full-apply dance that was needed by
  hand on every from-zero rebuild since 03/07. Directly motivated by a real incident
  this same session: applying the wrong root-app file to prod briefly ran dev/staging
  workloads inside the prod cluster (cleaned up by hand, no lasting damage). Verified
  end-to-end on both dev and prod: `terragrunt run-all apply` now stands a cluster up
  fully unattended, zero manual steps, zero race against ArgoCD/ALB timing.
- **Milestone reached 04/07/2026: Phase 5 (Observability/Grafana), v0.8.0.**
  `kube-prometheus-stack` (Prometheus, Grafana, Alertmanager, node-exporter,
  kube-state-metrics) + `postgres-exporter` (business metrics: total users, free/signed
  jobs by status) + KEDA scaler metrics all installed and verified live on dev. A
  custom "snaPDF - Business & Scaling Metrics" dashboard was built entirely as code
  (a `ConfigMap` + Grafana's dashboard-sidecar auto-load pattern) instead of built by
  hand in the UI — survives every cluster rebuild by design. Not yet applied to prod.
- **Also fixed this session (04/07/2026), same root cause recurring (Bug 29's pattern):**
  a from-scratch full-VPC rebuild of both dev and prod left `snapdf{,-prod}/db-credentials`
  holding stale passwords (RDS regenerates a new one on every real recreate) and dev
  missing its `snapdf_staging` logical database (Terraform only manages the default
  database) — both now automated instead of manual: the `rds` module keeps the
  consolidated secret in sync with the real master password on every apply, and the
  `addons` module runs a self-contained Job that recreates `snapdf_staging` only when
  the RDS instance is genuinely new (keyed to its `resource_id`).
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
- **v1.0.0 tagged 04/07/2026.** snaPDF #22 (JWT signature verification), infra #24
  (node group shrink) and #25 (GitHub → ArgoCD webhook) all closed same day; observability
  and TLS confirmed live on both dev and prod. infra #20 (formal prod end-to-end
  verification) is functionally satisfied (all 4 acceptance criteria met, including the
  webhook) but still open on GitHub pending formal closure. Remaining lower-priority,
  non-gating: snaPDF #20 (README), #21 (architecture diagram), #23 (logout button)

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
| v0.8.1 | Infra #17 — ArgoCD root bootstrap automated (no more manual step, any cluster) |
| v1.0.0 | **Final release** — all tests passing — redefined 04/07/2026 (README no longer a gating requirement) |
| v1.0.1 | infra #27 — Karpenter's controller moved onto its own Fargate profile (dev only; prod pending) |
| v1.0.2 | infra #27 rollout completed — prod migrated onto the same Fargate/module-split structure as dev |
| v1.0.3 | Wildcard DNS for Grafana/ArgoCD (dev only) + Bug 49 (self-inflicted outage from finishing a staged-but-unpushed gitops deletion) |

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
