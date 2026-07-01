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
