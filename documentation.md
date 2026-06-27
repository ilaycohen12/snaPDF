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

### Phase 1 — Infrastructure (Terragrunt)

#### Step 1 — VPC Terraform Module (`modules/vpc`)
- **What:** Wrote the complete VPC Terraform module — 3 files: `variables.tf`, `main.tf`, `outputs.tf`.
- **Uses:** `terraform-aws-modules/vpc/aws` community module — handles all subnet, route table, IGW, and NAT Gateway creation internally.
- **Network layout (3-tier):**
  - Public subnets `10.0.1.0/24`, `10.0.2.0/24` — ALB and NAT Gateway
  - Private subnets `10.0.3.0/24`, `10.0.4.0/24` — EKS worker nodes
  - Database subnets `10.0.5.0/24`, `10.0.6.0/24` — RDS (isolated tier)
- **Key decisions:**
  - `single_nat_gateway = true` — one NAT Gateway shared across both AZs to save cost (~$32/month vs $64/month)
  - `create_database_subnet_group = true` — auto-creates the RDS subnet group the RDS module will need
  - `enable_dns_hostnames` + `enable_dns_support` — both required by EKS so nodes can register with the control plane
  - Public subnet tag `kubernetes.io/role/elb = 1` — required by ALB Ingress Controller to find which subnets to create the ALB in
- **Outputs exposed:** `vpc_id`, `public_subnet_ids`, `private_subnet_ids`, `database_subnet_ids`, `database_subnet_group_name` — consumed by EKS, RDS, and security group modules via Terragrunt dependencies.

#### Step 2 — EKS Terraform Module (`modules/eks`)
- **What:** Wrote the complete EKS Terraform module — 3 files: `variables.tf`, `main.tf`, `outputs.tf`.
- **Uses:** `terraform-aws-modules/eks/aws` community module v20.
- **Key decisions:**
  - `cluster_version = "1.31"` — current stable Kubernetes version
  - `cluster_endpoint_public_access = true` — allows kubectl from laptop (needed for development)
  - `enable_irsa = true` — creates OIDC provider, required for ESO and ALB controller to assume IAM roles
  - `enable_cluster_creator_admin_permissions = true` — gives Terraform caller kubectl admin access after apply
  - Managed node group: `min=1`, `max=3`, `desired=2` — 2 nodes spread across 2 AZs
- **Outputs exposed:** `cluster_name`, `cluster_endpoint`, `cluster_certificate_authority_data`, `oidc_provider_arn`, `node_group_role_arn` — consumed by IAM and addons modules.
- **Terragrunt configs:** Written for dev and prod with `dependency "vpc"` block and `mock_outputs` so `terragrunt plan` works before VPC is deployed.

#### Step 3 — RDS Terraform Module (`modules/rds`)
- **What:** Wrote the complete RDS Terraform module — 3 files: `variables.tf`, `main.tf`, `outputs.tf`.
- **What it creates:** A security group for RDS and a PostgreSQL `db.t3.micro` instance in the database subnets.
- **Key decisions:**
  - `manage_master_user_password = true` — AWS auto-generates the password and stores it in Secrets Manager. ESO reads it from there. Password never lives in Git or code.
  - `multi_az = false` — single AZ to save cost. The 2 database subnets are required by AWS for the subnet group but don't mean Multi-AZ.
  - `skip_final_snapshot = true` + `deletion_protection = false` — allows easy `terraform destroy` without requiring a backup snapshot first
  - Security group allows port 5432 only from `node_security_group_id` — only EKS worker nodes can reach RDS, nothing else
- **Outputs exposed:** `db_endpoint`, `db_name`, `db_master_user_secret_arn` — consumed by the app and ESO.
- **Terragrunt configs:** Written for dev and prod with two dependencies — `vpc` (for subnet group + VPC ID) and `eks` (for node security group ID) — both with mock outputs.

#### Step 4 — IAM Terraform Module (`modules/iam`)
- **What:** Wrote the complete IAM Terraform module — 3 files: `variables.tf`, `main.tf`, `outputs.tf`.
- **What it creates:** Two IAM roles with IRSA trust policies — one for ALB Ingress Controller, one for External Secrets Operator.
- **Key concepts:**
  - `data "aws_caller_identity"` — reads AWS account ID at runtime, used to derive the OIDC URL from the ARN
  - `replace()` local — strips the ARN prefix to get the plain OIDC URL needed in trust policy conditions
  - Trust policy `Condition` — locks each role to a specific Kubernetes service account (namespace + name). No other pod can assume the role.
  - Role and policy are separate resources connected by `aws_iam_role_policy_attachment`
- **ALB controller permissions:** `ec2:Describe*`, `elasticloadbalancing:*`, `iam:CreateServiceLinkedRole`, `acm:DescribeCertificate`
- **ESO permissions:** `secretsmanager:GetSecretValue`, `secretsmanager:DescribeSecret` — read-only, nothing else
- **Outputs exposed:** `alb_controller_role_arn`, `eso_role_arn` — passed into Helm chart values in the addons module.

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
