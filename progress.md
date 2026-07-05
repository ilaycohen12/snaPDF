# snaPDF — Progress Tracker

## Phase 0 — Bootstrap
- [x] Step 1 — Install all required tools (git, aws cli, kubectl, terraform, terragrunt, helm) ✅ 14:45 25/06/2026
- [x] Step 2 — Verify AWS CLI identity ✅ 14:52 25/06/2026
- [x] Step 3 — Create S3 bucket for Terraform remote state ✅ 14:54 25/06/2026
- [x] Step 4 — Create DynamoDB table for state locking ✅ 15:01 25/06/2026
- [x] Step 5 — Create ECR repository for Docker images ✅ 15:02 25/06/2026
- [x] Step 6 — Setup GitHub issue + PR templates and branch workflow ✅ 26/06/2026
- [x] Step 7 — Authenticate gh CLI and create all issues and PRs ✅ 26/06/2026

### Phase 0 Summary
We set up everything needed before touching any real infrastructure. Installed all 6 CLI tools (git, aws, kubectl, terraform, terragrunt, helm), authenticated the AWS CLI using a dedicated IAM user instead of root (a security best practice), and created the 3 AWS resources that every Terraform project depends on: an S3 bucket to store state remotely, a DynamoDB table to prevent concurrent runs from corrupting that state, and an ECR repository where Docker images will be pushed by CI and pulled by the clusters. We also set up the GitHub workflow — issue and PR templates, branch naming convention, and authenticated the gh CLI so all future work has a proper issue → branch → PR trail.

---

## Phase 1 — Infrastructure (Terragrunt)
- [x] Step 1 — Write Terraform module: `vpc` ✅ 25/06/2026
- [x] Step 2 — Write Terraform module: `eks` ✅ 26/06/2026
- [x] Step 3 — Write Terraform module: `iam` (ALB controller + ESO + KEDA + worker roles) ✅ 26/06/2026
- [x] Step 4 — Write Terraform module: `rds` ✅ 26/06/2026
- [x] Step 5 — Write Terraform module: `sqs` (signed queue + free queue) ✅ 27/06/2026
- [x] Step 6 — Write Terraform module: `s3` (PDF storage bucket) ✅ 27/06/2026
- [x] Step 7 — Write Terraform module: `global` (ECR + API key secret) ✅ 27/06/2026
- [x] Step 8 — Write Terraform module: `addons` (ALB controller, ESO, ArgoCD, KEDA) ✅ 27/06/2026
- [x] Step 9 — Deploy dev: vpc ✅ eks ✅ sqs ✅ s3 ✅ iam ✅ rds ✅ addons ✅ 27/06/2026
- [ ] Step 10 — Deploy prod: same order
- [ ] Step 11 — Import ECR into Terraform global module

## Phase 2 — Sample App + GitHub Actions CI
- [x] Step 1 — Write Hello World Flask app + Dockerfile (test deployment) ✅ 27/06/2026
- [x] Step 2 — Build + push image to ECR, deploy to EKS, verify in browser ✅ 27/06/2026
- [x] Step 3 — Write full Flask web server (PDF submit endpoint + signed/unsigned routing) ✅ 28/06/2026
- [x] Step 4 — Write PDF worker (signed + free, LibreOffice conversion, S3 upload, RDS write) ✅ 28/06/2026
- [x] Step 5 — Write multi-stage Dockerfile (LibreOffice + Python deps, web server + worker share same image) ✅ 28/06/2026
- [x] Step 6 — Build + push full app image to ECR, verify in browser ✅ 28/06/2026
- [x] Step 7 — Write GitHub Actions CI pipeline (build → lint → push to ECR → update image tag) ✅ 28/06/2026

## Phase 3 — Helm Chart + CI Restructure
- [x] Step 1 — Create snaPDF-gitops repo with charts/service Helm chart structure ✅ 29/06/2026
- [x] Step 2 — Write all 6 Helm chart templates (deployment, service, ingress-nginx, scaledobject, hpa, externalsecret) ✅ 29/06/2026
- [x] Step 3 — Write per-environment values files (dev, staging, prod) for all services ✅ 29/06/2026
- [x] Step 4 — Split app into separate microservice directories (api/, worker/, auth/) ✅ 29/06/2026
- [x] Step 5 — Create 3 separate ECR repos (snapdf-api, snapdf-worker, snapdf-auth) ✅ 29/06/2026
- [x] Step 6 — Write 3 separate CI workflows with unit tests, one per service ✅ 29/06/2026
- [x] Step 7 — Add branch-based environment promotion (main→dev, staging→staging, prod→prod) ✅ 29/06/2026
- [x] Step 8 — Fix destroy script — handle LBs, ENIs, security groups, subnets, --lock=false ✅ 30/06/2026

## Phase 4 — GitOps (ArgoCD)
- [x] Step 1 — Add Nginx Ingress Controller to Terraform addons module ✅ 30/06/2026
- [x] Step 2 — Write eso-appset.yaml, services-appset.yaml, root-app.yaml ✅ 30/06/2026
- [x] Step 3 — Deploy dev infra and bootstrap ArgoCD with root app ✅ 30/06/2026
- [x] Step 4 — Fix Helm chart: add ESO property field + envFrom to deployment ✅ 30/06/2026
- [x] Step 5 — Fix IRSA trust policy for worker service accounts (wildcard) ✅ 30/06/2026
- [x] Step 6 — Fix ingress rewrite-target (path prefix stripping) ✅ 30/06/2026
- [x] Step 7 — Populate staging values files with env vars and ESO secrets ✅ 30/06/2026
- [x] Step 8 — Fix JavaScript fetch paths and HTML form actions for path routing ✅ 30/06/2026
- [x] Step 9 — Fix curly quote encoding bug in Python source files ✅ 30/06/2026
- [x] Step 10 — Verify full end-to-end flow: signup → upload → convert → download ✅ 30/06/2026
- [x] Fixed — ArgoCD Services missing (drift outside Terraform's visibility), recreated via `terragrunt apply -replace=helm_release.argocd` ✅ 09:51 01/07/2026 (see Bug 23 in documentation.md)
- [x] Fixed — signed-worker stuck at 1 replica, KEDA never authenticated to AWS (wrong Helm values path + missing identityOwner + stale operator pod) ✅ 11:15 01/07/2026 (see Bug 24 in documentation.md). KEDA now genuinely scales 0→N based on real SQS queue depth.
- [x] Fixed — worker IAM role's Terraform file didn't match its live (already-fixed) trust policy, risked silently reverting Bug 19 on next apply ✅ 14:31 01/07/2026 (see Bug 25 in documentation.md). Found during IAM/IRSA learning session, not an active failure.
- [x] Fixed — deleted orphaned NLB + target group from pre-rename `deploy-dev.yaml` manual test deployment (billing since Phase 2, untracked by Terraform), removed the stale file from the repo ✅ 01/07/2026 (see Bug 26 in documentation.md).
- [x] Added — ArgoCD RBAC: `non-prod`/`prod` AppProjects, prod restricted to manual-sync-only via syncWindows, wired into existing services-appset.yaml generator split ✅ 01/07/2026 (see documentation.md "ArgoCD RBAC — AppProject split"). Closes snaPDF-gitops issue #1.
- [x] Added — ConfigMap template to the generic chart, switched plain env vars to envFrom configMapRef ✅ 01/07/2026. Closes snaPDF-gitops issue #5.
- [x] Fixed — ESO Services missing (Bug 27, same root cause as Bug 23 recurring on a different Helm release), fixed via terragrunt apply -replace=helm_release.eso ✅ 01/07/2026.
- [x] Fixed — renamed gitops environments/prod → environments/production to match spec namespace naming, also fixed hidden ENV="prod" dependency in all 3 CI workflows ✅ 01/07/2026. Closes snaPDF-gitops issue #2.
- [x] Added — per-environment resource requests/limits (dev < staging < production) across all 12 values files ✅ 01/07/2026. Closes snaPDF-gitops issue #3.
- [x] Fixed — production values files completed (env vars, auth's roleArn, signed-worker's queueURL) ✅ 01/07/2026. eso.secrets deliberately left blocked — filed as snaPDF-infra issue #21 (prod-specific db-credentials + jwt-secret don't exist yet). **Must resolve #21 before starting the prod apply (issue #20) or every prod pod will crash-loop.**
- [x] Dev environment destroyed via destroy.ps1 ✅ 02/07/2026, ~35 min total. Hit and fixed a new issue mid-destroy — orphaned EC2 instance blocking subnet deletion (see Bug 28 in documentation.md). Confirmed fully gone: no EKS cluster, RDS, VPC, or LBs remain. global module (ECR, api-key secret) untouched by design.
- [x] Both dev and prod destroyed simultaneously ✅ 05/07/2026 morning — first real destroy since Karpenter/webhook/ALB-hook-rewrite landed, surfaced Bugs 39-42 (all fixed, see documentation.md).
- [x] Both dev and prod rebuilt from scratch via `terragrunt run-all apply` (parallel) ✅ 05/07/2026, ~23 min each. Prod's `addons` module completed clean on the first pass. Dev hit a new bug (43 — `data "kubernetes_ingress_v1"` read null status right after the wait script confirmed it was ready) on the Route53 records; fixed by re-running apply once more (picked up the 2 orphaned records in <1 min). Both clusters confirmed `ACTIVE`, all ArgoCD Applications `Synced`/`Healthy`, prod verified reachable at `https://snapdf.bond`. See documentation.md for full writeup.
- [x] Fixed — prod's Grafana business-metrics dashboard wasn't updating: `postgres_exporter`'s Helm release had baked in yesterday's (04/07) RDS password instead of today's, a Terraform data-source staleness race on the same rebuild (Bug 44 in documentation.md) ✅ 05/07/2026. Fixed via targeted `terragrunt apply -target=helm_release.postgres_exporter` + pod restart; confirmed authenticating successfully afterward.
- [x] infra #26 — ArgoCD moved off its own dedicated NLB onto dev's shared ALB ✅ 05/07/2026. Two real bugs hit and fixed getting there (missing legacy `kubernetes.io/ingress.class: nginx` annotation; `backend-protocol: GRPC` breaking plain browser traffic) — see documentation.md. Web UI verified reachable end-to-end (`/api/version` returning real ArgoCD data); `argocd` CLI's `--grpc-web` requirement not yet tested. Prod not yet migrated.
- [x] Added a `PodDisruptionBudget` (`maxUnavailable: 1`) to the generic `charts/service` chart ✅ 05/07/2026 — protects `api-production`/`auth-production`'s 2 replicas from both being evicted at once during a Karpenter node drain; safe no-op on every `replicas: 1` service. Verified live: all 12 PDBs present across dev/staging/production, `ALLOWED DISRUPTIONS: 1` on the 2-replica prod services.
- [x] `vpc` module refactored to compute subnets dynamically from `az_count` instead of 4 hand-maintained CIDR lists ✅ 05/07/2026. Offsets tuned specifically (+1/+3/+5) to reproduce the exact CIDRs already live — confirmed `0 to add, 0 to destroy` on both dev and prod before ever applying (a wider +0/+10/+20 spacing was tried first and would have force-replaced all 13 subnets on live dev — reverted). Applied to both via full `terragrunt run-all apply` (not the vpc module alone, so the eks module's out-of-band Karpenter subnet-discovery tag reconciled in the same run). Verified live: same CIDRs, same tags, both clusters `ACTIVE`, zero downtime.
- [ ] Step 11 — Apply prod infra: terragrunt run-all apply in environments/prod
- [ ] Step 12 — Register prod cluster with ArgoCD: argocd cluster add
- [ ] Step 13 — Configure ArgoCD webhook — instant sync on snaPDF-gitops push

### Phase 4 Summary
ArgoCD is fully operational managing 8 applications (4 services × dev + staging). The complete user flow works end-to-end: sign up on /auth → upload .docx on /api → worker picks up from SQS → converts with LibreOffice → stores in S3 → user downloads PDF via presigned URL. Key fixes included: ESO ExternalSecret property field rendering, pod envFrom injection, IRSA trust policy wildcard for service accounts, nginx rewrite-target for path-based routing, JavaScript URL prefixing, and replacing curly smart quotes that were breaking JS in the browser.

## Phase 5 — Observability (Prometheus + Grafana)
- [ ] Step 1 — Install kube-prometheus-stack via Helm (Prometheus + Grafana + Alertmanager)
- [ ] Step 2 — Create Grafana dashboard: pod CPU/memory, SQS queue depth, conversion rate
- [ ] Step 3 — Add KEDA ScaledObject metrics to Grafana (signed worker replica count)

## Phase 6 — Karpenter
- [ ] Step 1 — Install Karpenter via Helm, replace managed node group
- [ ] Step 2 — Write NodePool and EC2NodeClass manifests
- [ ] Step 3 — Verify nodes provision and deprovision based on pod demand

## Phase 7 — Documentation & Diagram
- [x] Step 1 — Create architecture diagram (HTML) ✅ 26/06/2026
- [ ] Step 2 — Update architecture diagram with KEDA + SQS + S3 + workers + Prometheus
- [ ] Step 3 — Write README (setup, decisions, limitations)
- [ ] Step 4 — Final review of documentation.md
