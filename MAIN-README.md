# snaPDF

## Overview

## repos

## Usage

### Using the app (end user)

1. Open [snapdf.bond](https://snapdf.bond) (or `dev.snapdf.bond` /
   `staging.snapdf.bond`).
2. **Free tier** — upload a document, wait, download the PDF. No account.
3. **Signed tier** — register and log in first; your jobs go through the
   dedicated signed queue and workers (the ones that scale from zero).
4. Job status is shown on the page; the download link appears when the
   conversion finishes.

### Day-to-day operations

| I want to… | I do… |
|---|---|
| Ship an app change | merge to `main` (dev) / `staging` / `prod` — CI + ArgoCD do the rest |
| Change replicas/resources/scaling | edit the service's values file in snaPDF-gitops, commit |
| Change AWS infrastructure | edit snaPDF-infra, `terragrunt apply` in that module's folder |
| Roll back a deploy | `git revert` the tag-bump commit in snaPDF-gitops |
| Rotate a secret | change it in Secrets Manager, restart the affected pods |
## architecture decisions
**One generic Helm chart for all four services.** No per-service charts —
`charts/service` with feature flags (ingress/HPA for web, KEDA ScaledObject
for workers). A chart fix lands on every service at once; adding a
service is a directory and a values file, no ApplicationSet edits.
**Two queues, not one queue with a priority field.** free and signed are
separate SQS queues per environment. SQS has no message priority, so
"one queue, priority column" doesn't exist — but the real win is that
separate queues give each tier its own scaling signal (KEDA watches only
the signed queue), its own workers, and its own blast radius: a flood of
free jobs can't delay a paying user's conversion by even one message.
**One worker codebase, two deployments.** free-worker and signed-worker
run the same image; `QUEUE_URL` + `QUEUE_TYPE` select the queue and DB
table at deploy time. The alternative — two worker services — doubles
Dockerfiles, CI pipelines, and drift surface for zero behavioral
difference. Configuration varies; code doesn't.
**S3 native state locking, no DynamoDB.** `use_lockfile = true` pins
Terraform ≥ 1.10 and deletes an entire bootstrap resource (the lock
table). Same conditional-write guarantee, one less thing to create on an
empty account — chosen fresh because the project postdates the feature.
**Webhook-triggered syncs, polling as fallback.** ArgoCD learns of
commits via a GitHub webhook (secret generated in Terraform, stored in
Secrets Manager) instead of waiting on the 3-minute poll. Deploys land in
seconds; the poll stays as the safety net when a webhook is lost — push
for speed, pull for correctness.
## documentation

## bugs i run into

## AI


