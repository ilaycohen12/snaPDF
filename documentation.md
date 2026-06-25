# ProjectView — Documentation Log

A living document of every step taken in this project, explained in plain English.
Updated throughout the build.

---

## Infra
> Everything related to AWS infrastructure: VPC, EKS clusters, IAM roles, Terraform/Terragrunt.

### Phase 0 — Bootstrap

#### Tool Installation
- **What:** Installed git, AWS CLI, kubectl, terraform, terragrunt, helm on Windows.
- **Why:** These are the core tools for the entire project. Without them nothing can be built or deployed.
- **How:** git/aws/kubectl were already present. terraform and helm installed via `winget`, then copied to `C:\Windows\System32` so they're available in any terminal. terragrunt downloaded directly from the official GitHub release as a single `.exe` and placed in `System32`.
- **Tools and their roles:**
  - `git` — version control, also used by GitHub Actions to tag Docker images by git SHA
  - `aws cli` — talks to your AWS account from the terminal
  - `kubectl` — CLI for Kubernetes, used to inspect clusters, pods, ArgoCD status
  - `terraform` — the IaC tool that provisions AWS resources from `.tf` files
  - `terragrunt` — thin wrapper around Terraform that removes config repetition between dev and prod environments
  - `helm` — Kubernetes package manager, used to deploy the app chart with per-environment values

#### AWS CLI Configuration
- **What:** Ran `aws configure` to authenticate the CLI with AWS credentials.
- **Why:** Every AWS command (creating S3, DynamoDB, ECR, EKS) needs to know which account to talk to and with what permissions.
- **Best practice applied:** Created a dedicated IAM user (`admin`) instead of using root access keys. Root keys have unlimited permissions and can never be restricted — if leaked, the entire AWS account is compromised. An IAM user can be deleted or have permissions revoked at any time.
- **Verified with:** `aws sts get-caller-identity` — returned Account ID `086241318869`, user `admin`.

#### S3 Bucket for Terraform State
- **What:** Created S3 bucket `projectview-tf-state-086241318869` in `us-east-1`. Enabled versioning on it.
- **Command:** `aws s3api create-bucket --bucket projectview-tf-state-086241318869 --region us-east-1`
- **Why:** Terraform tracks everything it has deployed in a state file (`terraform.tfstate`). Storing it in S3 means it's safe, shared, and never lost. Without remote state, the file lives only on your laptop — if you lose it, Terraform loses track of your entire infrastructure.
- **Why versioning:** If a state file gets corrupted during a failed apply, S3 versioning lets you restore the previous good version. Without it, a corrupted state = you lose track of everything Terraform manages.
- **Bucket name includes account ID** because S3 bucket names must be globally unique across all AWS accounts worldwide.

#### DynamoDB Table for State Locking
- **What:** Created DynamoDB table `projectview-tf-locks` in `us-east-1`. Status: ACTIVE.
- **Command:** `aws dynamodb create-table --table-name projectview-tf-locks --attribute-definitions AttributeName=LockID,AttributeType=S --key-schema AttributeName=LockID,KeyType=HASH --billing-mode PAY_PER_REQUEST --region us-east-1`
- **Why:** S3 stores the state file but doesn't prevent two Terraform runs from editing it at the same time. If that happens, the state gets corrupted. DynamoDB acts as a distributed lock — when a Terraform run starts, it writes a lock entry. Any other run that tries to start sees the lock and waits. When the first run finishes, the lock is released.
- **Billing mode PAY_PER_REQUEST:** We only pay per read/write — for a project like this the cost is essentially zero.

#### ECR Repository
- **What:** Created ECR repository `projectview-app` in `us-east-1`.
- **Command:** `aws ecr create-repository --repository-name projectview-app --region us-east-1`
- **URI:** `086241318869.dkr.ecr.us-east-1.amazonaws.com/projectview-app`
- **Why:** ECR is AWS's private Docker registry — the bridge between CI and the cluster. GitHub Actions builds the Flask app into a Docker image and pushes it here tagged by git SHA (e.g. `projectview-app:a3f9c12`). EKS pulls from here when deploying.

---

## App
> Everything related to the sample Flask application and its Dockerfile.

---

## Workflow
> Everything related to GitHub Actions CI pipeline.

---

## GitOps
> Everything related to ArgoCD, App of Apps, and deployment promotion flow.

---

## Secrets
> Everything related to External Secrets Operator and AWS Secrets Manager integration.

---

## Bug Fixes
> Issues encountered and how they were resolved.

---
