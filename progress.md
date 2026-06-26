# ProjectView — Progress Tracker

## Phase 0 — Bootstrap
- [x] Step 1 — Install all required tools (git, aws cli, kubectl, terraform, terragrunt, helm) ✅ 14:45 25/06/2026
- [x] Step 2 — Verify AWS CLI identity ✅ 14:52 25/06/2026
- [x] Step 3 — Create S3 bucket for Terraform remote state ✅ 14:54 25/06/2026
- [x] Step 4 — Create DynamoDB table for state locking ✅ 15:01 25/06/2026
- [x] Step 5 — Create ECR repository for Docker images ✅ 15:02 25/06/2026

### Phase 0 Summary
We set up everything needed before touching any real infrastructure. Installed all 6 CLI tools (git, aws, kubectl, terraform, terragrunt, helm), authenticated the AWS CLI using a dedicated IAM user instead of root (a security best practice), and created the 3 AWS resources that every Terraform project depends on: an S3 bucket to store state remotely, a DynamoDB table to prevent concurrent runs from corrupting that state, and an ECR repository where Docker images will be pushed by CI and pulled by the clusters. Phase 0 has no code — it's purely setup and AWS plumbing.

---

## Phase 1 — Infrastructure (Terragrunt)
- [x] Step 1 — Write Terraform module: `vpc` ✅ 25/06/2026
- [x] Step 2 — Write Terraform module: `eks` ✅ 26/06/2026
- [x] Step 3 — Write Terraform module: `iam` ✅ 26/06/2026
- [x] Step 4 — Write Terraform module: `rds` ✅ 26/06/2026
- [ ] Step 5 — Write Terraform module: `addons`
- [ ] Step 5 — Write Terragrunt configs for dev + prod
- [ ] Step 6 — Deploy: vpc → eks → iam → addons

## Phase 2 — Sample App + GitHub Actions CI
- [ ] Step 1 — Write Python Flask app
- [ ] Step 2 — Write multi-stage Dockerfile
- [ ] Step 3 — Write GitHub Actions CI pipeline (build → lint → push to ECR → update Helm values)

## Phase 3 — Helm Chart
- [ ] Step 1 — Write generic Helm chart (Deployment, Service, Ingress, ConfigMap, ExternalSecret)
- [ ] Step 2 — Write per-environment values: dev.yaml, staging.yaml, production.yaml

## Phase 4 — GitOps (ArgoCD)
- [ ] Step 1 — Install ArgoCD on both clusters
- [ ] Step 2 — Set up App of Apps pattern
- [ ] Step 3 — Configure promotion flow (dev → staging → production)
- [ ] Step 4 — Configure RBAC per environment

## Phase 5 — Documentation & Diagram
- [ ] Step 1 — Write README (setup, decisions, limitations)
- [ ] Step 2 — Create architecture diagram (HTML/SVG)
- [ ] Step 3 — Final review of documentation.md
