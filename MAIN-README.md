# snaPDF

## Overview
snaPDF is a PDF conversion SaaS built end-to-end as a production-grade
system: upload a document, it's converted asynchronously, download the
result — a free tier for anonymous users, a signed tier for
authenticated ones.

## Repos
The system spans three repositories with deliberately designed
boundaries — split by *who changes it and what a change means*:

| Repo | Owns | A commit here means |
|---|---|---|
| **[snaPDF](https://github.com/ilaycohen12/snaPDF)** | Application code, Dockerfiles, tests, CI | CI builds an image and bumps a tag in gitops |
| **[snaPDF-infra](https://github.com/ilaycohen12/snaPDF-infra)** | Every AWS resource — VPC, EKS, RDS, SQS, S3, IAM, autoscaling, observability, ArgoCD itself | Nothing, until a human runs `terragrunt apply` |
| **[snaPDF-gitops](https://github.com/ilaycohen12/snaPDF-gitops)** | What runs in the clusters — ApplicationSets, one generic Helm chart, per-env values | ArgoCD deploys it within seconds |

They connect at exactly two points: infra's last act installs ArgoCD and
plants one root Application pointing at gitops; and app CI's last act
commits an image-tag bump into gitops. No other repo touches another —
and no actor holds both git-write and cluster access.

Each repo's README covers its own layer in depth.

## Usage

### Using the app (end user)

1. Open [snapdf.bond](https://snapdf.bond)
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

## Architecture Decisions

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

## Documentation
The project is documented the way it was built — as a running engineering
log, not an afterthought. There were three living documents in the app repo:

- **(documentation.md)** — the core log: every key
  decision with its reasoning (Terragrunt over Terraform, two queues,
  LibreOffice, …) and every bug hit along the way — 45+ entries, each
  with symptom, root cause, fix, and verification. Entries are written
  the same day the work happened.
- **(progress.md)** — chronological build log: what was
  done, when, in what order.
- **(explanations.md)** — concepts learned during the
  build, written up in plain language (IRSA mechanics, ENI/IP pod limits,
  ArgoCD generators, …).

## Bugs I Run Into
45+ bugs are logged in documentation.md with root
cause, fix, and live verification. Three that are worth your time:

**Bug 24 — KEDA never actually authenticated to AWS**
signed-worker ignored its 0–3 scaling range with no error anywhere. Three
stacked causes: a Helm `set` key that didn't exist in the chart schema
(Helm accepts unknown keys silently), KEDA defaulting to the *workload's*
identity instead of its own scoped role (`identityOwner`), and an
operator pod older than its own IAM annotation — IRSA injects credentials
only at pod creation. Fixes spanned both repos plus a rollout restart.

**Bug 32 — the 17-pod ceiling was an IP limit, not a CPU limit**
Pods Pending on a cluster that was only ~73% utilized. The real limit:
VPC CNI gives each pod a real IP from the node's ENIs — t3.medium's math
is 3 ENIs × 5 + 2 = 17 pods, a networking constant no bigger t3 fixes.
Fixed with CNI prefix delegation, deliberately capped at maxPods 35, and
the CNI brought under Terraform management for the first time.

**Bug 38 — a rollback drill's break resurfaced in prod a day later**
A drill intentionally broke a button to practice gitops rollback. The
rollback — reverting the tag-bump commit — restored the *deployment* but
left the broken line in `main`'s source. One fast-forward promotion
later, fresh images built from `main`'s tip shipped it to production.
Lesson: a deployment rollback and a source fix are different operations;
now every rollback is followed by a source-level revert or fix-forward.

## AI
On this project, I used CLAUDE.md and Claude Skills.
It was used as a learning accelerator and pair engineer throughout — but as engineered tooling: CLAUDE.md holds standing project context, and custom skills encode the repo's conventions (bug-entry format, module structure, PR format).

## Summary
This is the second DevOps project I've made, and I really feel that I learned a lot of things much better. Thank you for the opportunity and I hope you like my work!
