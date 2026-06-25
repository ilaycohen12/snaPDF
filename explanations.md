# ProjectView — Technology Explanations

A reference of every technology and concept covered in this project, explained in plain English.

---

## Terraform

**What it is:** An Infrastructure as Code (IaC) tool. You describe what AWS resources you want in `.tf` files, and Terraform creates them for you.

**Key concepts:**

- **Provider** — the plugin that lets Terraform talk to a specific cloud. For us: `provider "aws"`. Without it Terraform doesn't know which cloud to use.
- **Resource** — a real thing you want to create (a VPC, an EKS cluster, an IAM role). Each resource maps to one real AWS object.
- **Module** — a reusable folder of `.tf` files. Write the VPC logic once, call it for dev and prod with different values. Like a function in code.
- **State file (`terraform.tfstate`)** — a JSON file Terraform keeps to track what it already created. Terraform compares your `.tf` files against the state to figure out what to add/change/delete. Without it, Terraform is blind.
- **Backend** — where the state file lives. Default = local file on your laptop. We use S3 so it's safe and shared.
- **Variables** — inputs to a module. Like function arguments. Defined in `variables.tf`.
- **Outputs** — values a module exposes to the outside. Like a function return value. Defined in `outputs.tf`.
- **`terraform init`** — downloads providers and modules. Must run before anything else.
- **`terraform plan`** — dry run. Shows what will be created/changed/destroyed. Nothing actually happens.
- **`terraform apply`** — actually creates/changes/destroys resources on AWS.
- **`terraform destroy`** — tears everything down. Deletes all resources Terraform manages.

---

## Terragrunt

**What it is:** A thin wrapper around Terraform that removes repetition when managing multiple environments (dev, prod).

**The problem it solves:** In pure Terraform, every environment needs its own copy of the backend config (S3 bucket, region, DynamoDB). If you have 4 modules × 2 environments = 8 files with near-identical boilerplate. Terragrunt defines it once and all environments inherit it.

**Key concepts:**

- **Root `terragrunt.hcl`** — sits at the top of the infra folder. Defines the S3 backend and AWS provider once. Every child environment inherits it automatically via `find_in_parent_folders()`.
- **Environment `terragrunt.hcl`** — sits next to each module (e.g. `dev/vpc/terragrunt.hcl`). Points to the Terraform module, reads env values, and passes inputs.
- **`env.hcl`** — a file per environment (dev/prod) that holds all environment-specific values (region, node type, CIDR block). Keeps values in one place per environment.
- **`locals`** — variables for use inside a `terragrunt.hcl` file only. Used to read and prepare values before passing them to Terraform. Nothing outside the file sees them.
- **`inputs`** — values passed into the Terraform module. These become the actual variable values inside the module. Handed over to Terraform, not kept in Terragrunt.
- **`dependency`** — tells Terragrunt one module depends on another and can read its outputs (e.g. `eks` reads the `vpc_id` output from `vpc`).
- **`run-all`** — runs a command across all modules in the correct dependency order automatically.
- **`find_in_parent_folders()`** — walks up the directory tree until it finds a file (usually `terragrunt.hcl` or `env.hcl`).
- **`read_terragrunt_config()`** — reads another `.hcl` file and gives you access to its locals.
- **`path_relative_to_include()`** — generates a unique S3 key per module automatically (e.g. `dev/vpc/terraform.tfstate`).
- **`generate "provider"`** — tells Terragrunt to create a `provider.tf` file automatically in each module before running Terraform. This is how the AWS provider is injected without writing it in every module.

**One line summary:** Terraform is the engine. Terragrunt is the steering wheel that lets you drive the same engine to multiple destinations without rebuilding it each time.

---

## S3 (Terraform Remote State)

**What it is:** AWS Simple Storage Service — object/file storage in the cloud.

**How we use it:** Store Terraform state files remotely so they are safe, versioned, and shared across machines and CI runs.

**Why versioning is enabled:** If a state file gets corrupted during a failed apply, S3 versioning lets you restore the previous good version.

**Bucket:** `projectview-tf-state-086241318869` (account ID in name for global uniqueness)

---

## State Locking (`use_lockfile = true`)

**What it is:** A mechanism to prevent two Terraform runs from editing the state file at the same time, which would corrupt it.

**How it works:** When a Terraform run starts, it creates a `.tflock` file in S3 next to the state file. Any other run that tries to start sees that file and waits. When the run finishes, the lockfile is deleted automatically.

**Why not DynamoDB:** We initially planned to use DynamoDB for locking (the traditional pattern), but switched to `use_lockfile = true` — a native S3 locking option introduced in Terraform 1.10+ — to avoid needing a separate AWS resource.

**Where it lives:** Configured in the root `terragrunt.hcl` backend config. The S3 bucket itself needs no changes.

---

## ECR (Elastic Container Registry)

**What it is:** AWS's private Docker image registry.

**How we use it:** GitHub Actions builds the Flask app into a Docker image and pushes it here tagged by git SHA (e.g. `projectview-app:a3f9c12`). EKS pulls from here when deploying.

**Why private:** Public registries expose your image to anyone. ECR is private and lives inside your AWS account — only your EKS clusters and CI pipeline can access it.

**Repository URI:** `086241318869.dkr.ecr.us-east-1.amazonaws.com/projectview-app`

---

## EKS (Elastic Kubernetes Service)

**What it is:** AWS's managed Kubernetes service. AWS runs the Kubernetes control plane for you — you only manage the worker nodes.

**Two sides of a cluster:**

- **Control Plane** — the brain. Decides where to run your app, watches for crashed pods and restarts them, handles scaling. AWS runs this on their own servers. You never SSH into it — it's a flat ~$73/month fee.
- **Worker Nodes** — regular EC2 instances (`t3.small` in our case). These sit in your VPC in the private subnet. The control plane tells them what to run. You pay for these like any EC2 instance.
- **Pods** — the smallest unit in Kubernetes. A pod is one or more containers running together. Your Flask app = one pod per replica. Pods run inside worker nodes.

**Why worker nodes are in the private subnet:** Nodes run your code and have access to internal resources (RDS, Secrets Manager). Private subnet = no inbound internet route. Nodes still reach the internet outbound (to pull images from ECR) via the NAT Gateway.

**What happens when you deploy:**
1. You push code to GitHub
2. GitHub Actions builds a Docker image and pushes it to ECR
3. GitHub Actions updates the Helm values file with the new image tag
4. ArgoCD sees the change in GitHub
5. ArgoCD tells the Control Plane: "run this new image"
6. Control Plane picks a Worker Node and schedules a Pod on it
7. The Worker Node pulls the image from ECR (via NAT Gateway)
8. The Pod starts — your Flask app is running
9. User hits the ALB → ALB routes to the Pod → response goes back

**How we use it:** Two clusters — `projectview-dev` (with `dev` and `staging` namespaces) and `projectview-prod` (with `production` namespace). Both use `t3.small` worker nodes.

---

## RDS (Relational Database Service)

**What it is:** AWS's managed PostgreSQL service. AWS handles backups, patching, and failover — you just use the database.

**Where it lives:** In the same **private subnets** as the EKS worker nodes. Never reachable from the internet.

**How the app connects:**
```
Flask app pod (private subnet)
        ↓  private IP — stays inside the VPC
RDS PostgreSQL (private subnet)
```
Both are inside the same VPC so they talk via internal AWS routing — no NAT, no internet, no ALB involved.

**Security:** RDS has its own Security Group that acts as a firewall. It only allows port 5432 (PostgreSQL) from the EKS worker nodes' Security Group. Nothing else can reach it.

**How the app gets the DB password:** The password is stored in AWS Secrets Manager. The External Secrets Operator pulls it into a Kubernetes Secret. The Flask app reads it as an environment variable. The password never lives in Git or in the Docker image.

---

## ArgoCD

**What it is:** A GitOps continuous delivery tool for Kubernetes. It watches a Git repo and automatically syncs the cluster state to match what's in Git.

**App of Apps pattern:** One root ArgoCD app that manages all child apps. Instead of registering every app manually, you register one root app and it discovers and manages the rest.

**Promotion flow:** CI auto-deploys to dev → manual PR to staging → manual PR to production.

**Rollback:** Git revert the values file → ArgoCD auto-syncs the cluster back to the previous state.

---

## Helm

**What it is:** The Kubernetes package manager. Packages a Kubernetes app as a reusable "chart" with templates and values.

**How we use it:** One generic chart for the app with per-environment values files (dev.yaml, staging.yaml, production.yaml). The chart defines the Deployment, Service, Ingress, ConfigMap, and ExternalSecret templates. The values files fill in the environment-specific details.

---

## External Secrets Operator

**What it is:** A Kubernetes operator that pulls secrets from external secret managers (like AWS Secrets Manager) and creates Kubernetes Secrets from them.

**How we use it:** A `ClusterSecretStore` connects to AWS Secrets Manager. `ExternalSecret` objects define which secrets to pull and where to put them in the cluster. The app reads them as normal Kubernetes Secrets.

**Why:** Never store secrets in Git. They live in AWS Secrets Manager and are injected into the cluster at runtime.

---

## GitHub Actions CI

**What it is:** GitHub's built-in CI/CD system. Runs automated workflows triggered by git events (push, PR, tag).

**Our pipeline:** build → lint → push image to ECR (tagged by git SHA) → update Helm values file with new image tag → ArgoCD picks up the change and deploys.

---

## IAM (Identity and Access Management)

**What it is:** AWS's permission system. Controls who (users, services, clusters) can do what on AWS.

**Best practice applied:** Created a dedicated IAM user (`admin`) instead of using root access keys. Root keys have unlimited permissions and can never be restricted — if leaked, the entire AWS account is compromised.

---

## VPC (Virtual Private Cloud)

**What it is:** A private, isolated network inside AWS. All your resources (EKS nodes, RDS, etc.) live inside a VPC.

**Our setup:** Two VPCs — one per cluster.
- Dev VPC: `10.0.0.0/16`
- Prod VPC: `10.1.0.0/16`

Different CIDR blocks so the networks don't overlap — required if you ever want to connect them via VPC peering.
