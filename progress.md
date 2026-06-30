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
- [ ] Step 1 — Add Nginx Ingress Controller to Terraform addons module
- [ ] Step 2 — Delete apps/nginx-app.yaml from snaPDF-gitops (Nginx moved to Terraform)
- [ ] Step 3 — Fill in apps/eso-appset.yaml — ApplicationSet deploying ClusterSecretStore per cluster
- [ ] Step 4 — Fill in apps/services-appset.yaml — ApplicationSet generating one app per service per env
- [ ] Step 5 — Write infra/bootstrap/root-app.yaml in snaPDF-infra — root ArgoCD Application pointing at snaPDF-gitops/apps/
- [ ] Step 6 — Apply dev infra: terragrunt run-all apply in environments/dev
- [ ] Step 7 — Reconnect kubectl to dev: aws eks update-kubeconfig --region us-east-1 --name snapdf-dev
- [ ] Step 8 — Apply root app: kubectl apply -f infra/bootstrap/root-app.yaml (one-time bootstrap)
- [ ] Step 9 — Apply prod infra: terragrunt run-all apply in environments/prod
- [ ] Step 10 — Reconnect kubectl to prod: aws eks update-kubeconfig --region us-east-1 --name snapdf-prod
- [ ] Step 11 — Register prod cluster with ArgoCD: argocd cluster add
- [ ] Step 12 — Configure ArgoCD webhook — instant sync on snaPDF-gitops push
- [ ] Step 13 — Verify full GitOps flow end to end

## Phase 5 — Documentation & Diagram
- [x] Step 1 — Create architecture diagram (HTML) ✅ 26/06/2026
- [ ] Step 2 — Update architecture diagram with KEDA + SQS + S3 + workers
- [ ] Step 3 — Write README (setup, decisions, limitations)
- [ ] Step 4 — Final review of documentation.md
