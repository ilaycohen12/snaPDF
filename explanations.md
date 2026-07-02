# snaPDF — Concept Explanations

New technologies and concepts get added here the first time they come up, in plain English.

---

## Why new cluster-scoped objects go in the gitops repo's `apps/` folder

`apps/` isn't just "where ApplicationSets live" — it's specifically the one folder the `root` Application (`infra/bootstrap/root-app.yaml`) watches (`spec.source.path: apps`), applying anything found there straight into the `argocd` namespace, automatically, because `root`'s `syncPolicy` is `automated`.

This means **any** valid Kubernetes object dropped into `apps/` gets auto-applied for free — it doesn't have to be an ApplicationSet specifically. When adding the `non-prod`/`prod` `AppProject` objects (01/07/2026), they went into `apps/appprojects.yaml` for exactly this reason: `AppProject`s must live in the `argocd` namespace to work, and `apps/` was already the one folder wired to land things there automatically, with zero new plumbing (no new ApplicationSet, no manual `kubectl apply`).

Contrast with `bootstrap/` — that folder is *not* watched by anything on its own. `bootstrap/eso/clustersecretstore.yaml` only gets applied because `eso-appset.yaml` (itself sitting in `apps/`) explicitly points its generator at `bootstrap/eso`. Without that generator, nothing in `bootstrap/` would ever reach the cluster automatically.

**The rule:** if something needs to land in the `argocd` namespace with zero extra setup, put it in `apps/`. If it needs to land somewhere else, it needs its own ApplicationSet (or to be referenced by an existing one) pointing at wherever it actually lives.

## Terraform `helm_release` only tracks release metadata, not child objects
When Terraform creates a `helm_release` resource, it's really just calling `helm install` under the hood and remembering the Helm release name, chart, version, and values it used. It does **not** keep a live inventory of every Kubernetes object (Deployment, Service, ConfigMap, etc.) that chart created. This means `terraform plan` can say "no changes" even if someone deletes one of those objects directly with `kubectl delete` — Terraform simply never looks. Contrast this with a native Terraform resource like `aws_s3_bucket`, where Terraform refreshes the *actual* AWS object's state on every plan and will show drift if you change it outside Terraform.

**Practical implication:** if a Helm-managed Kubernetes object gets deleted or modified out-of-band, `terraform plan` will not catch it. The fix has to be manual: either fix it directly with `kubectl`/`helm`, or force Terraform to redo the whole release.

## `terraform apply -replace=<address>`
Normally `terraform apply` only touches resources that changed in your `.tf` config. `-replace` is a flag that tells Terraform "destroy this specific resource and recreate it, even though nothing in the config changed." For a `helm_release`, that means: run `helm uninstall`, then `helm install` fresh. This is the go-to tool for fixing a Helm release whose live Kubernetes objects have drifted from what the chart expects, since Terraform has no finer-grained way to repair individual objects inside a release — it can only redo the whole thing.

In Terragrunt (which wraps Terraform), the same flag works: `terragrunt apply -replace=helm_release.argocd` from inside the relevant module directory.

## Why deleting a Service breaks DNS between pods
Kubernetes gives every Service a stable internal DNS name like `argocd-repo-server.argocd.svc.cluster.local` (or just `argocd-repo-server` from within the same namespace), resolved by CoreDNS. This DNS name is *only* created because the Service object exists — it's what CoreDNS uses to answer lookups and route traffic to whichever pod(s) match the Service's label selector. If the Service is deleted but the pod behind it is still running, the pod still exists and is healthy, but nothing can find it by name anymore — other pods trying to connect get `no such host`. This is why ArgoCD's controller pods were all "Running" and yet ArgoCD as a whole was non-functional: the pods were up, but unreachable from each other.

## Why `helm uninstall` doesn't delete CRDs
Helm has a long-standing rule: CRDs (Custom Resource Definitions) installed by a chart are *never* deleted automatically on `helm uninstall`, even though everything else the chart created does get removed. The reasoning is safety — deleting a CRD cascades to delete every custom resource of that type across the entire cluster. For ArgoCD, deleting the `applications.argoproj.io` CRD would wipe out every `Application` object (all 14 of your ArgoCD-managed services across dev/staging/prod) as a side effect of just reinstalling the ArgoCD control plane. Helm avoids this footgun by keeping CRDs around and only lets you delete them explicitly if you really mean to.

## Helm `set` values are never validated against the chart's schema
When you write `set { name = "some.path.here" ... }` in a Terraform `helm_release`, or `--set some.path.here=x` on the CLI, Helm just merges that key into the values tree it hands to the chart's templates. It does **not** check whether any template actually reads that key. If you get the path wrong — like using `serviceAccount.operator.annotations` on a chart that only understands `podIdentity.aws.irsa.roleArn` — Helm accepts it without complaint, installs "successfully," and the value simply sits there unused. Nothing errors. The only way to catch this is to check the *actual rendered object on the cluster* (e.g. `kubectl get sa <name> -o yaml`) against what you expected, or read the chart's own values schema (`helm show values <repo>/<chart>`) before trusting a `set` path. This is why Bug 24's root cause survived silently since day one of the project.

## IRSA credentials are injected once, at pod creation — not live
IRSA (IAM Roles for Service Accounts) isn't magic baked into the ServiceAccount object itself — it works through a mutating admission webhook that Kubernetes runs whenever a *pod* is created. If the pod's ServiceAccount has the `eks.amazonaws.com/role-arn` annotation at the moment the pod is scheduled, the webhook injects two things into that pod's spec: an `AWS_ROLE_ARN` env var and a projected volume containing a short-lived OIDC token, which the AWS SDK inside the container automatically uses to assume that IAM role.

The critical consequence: if you add or fix that annotation on a ServiceAccount *after* a pod using it is already running, nothing happens to that existing pod. It keeps running with whatever credentials it started with (often silently falling back to the EC2 node's own instance role, which usually has much narrower permissions). You must delete/restart the pod — e.g. `kubectl rollout restart deployment <name>` — so a brand-new pod gets created and the webhook runs again with the now-correct annotation in place. This is exactly what happened with `keda-operator` in Bug 24: fixing the ServiceAccount wasn't enough on its own.

## KEDA's `identityOwner`: pod vs operator
For AWS-based KEDA scalers (like `aws-sqs-queue`), the `identityOwner` field on a trigger controls *whose* AWS identity KEDA uses to make the metrics call:
- `identityOwner: pod` (the default) — KEDA reads the IAM role attached to the **scaled workload's own ServiceAccount** (e.g. `signed-worker-dev-sa`). Simple, but means your autoscaling metrics check reuses whatever broad permissions that workload's role already has.
- `identityOwner: operator` — KEDA instead uses the IAM role attached to the **KEDA operator's own ServiceAccount**, completely independent of the workload being scaled.

## NLB vs ALB, and why two AWS Load Balancer Controllers can coexist doing nothing
An AWS Network Load Balancer (NLB) operates at the connection level (L4) — it forwards raw TCP/UDP traffic without looking inside it, and has no concept of HTTP paths, hostnames, or headers. An Application Load Balancer (ALB) operates at the HTTP level (L7) — it can read the URL path, the `Host:` header, and route based on either, and it's the only one of the two that AWS lets you attach an SSL/TLS certificate to for termination.

In this project, Nginx's Kubernetes `Service` is `type: LoadBalancer`, which makes Kubernetes ask the cloud provider for a load balancer directly — on AWS this provisions an **NLB**, automatically, the moment that Service is created. Separately, the **AWS Load Balancer Controller** is installed in the cluster specifically to create **ALBs**, but only in response to a Kubernetes `Ingress` object that has `ingressClassName: alb` on it. If no such Ingress exists, the controller just sits there, subscribed to an event stream with nothing ever appearing on it — running, healthy, and doing precisely nothing. That's the exact state this project was in: an NLB doing all the real work, an idle ALB controller installed alongside it for no functional reason.

## TLS termination — what "terminates" actually means
An HTTPS connection is encrypted between the client and whichever endpoint is holding the matching TLS certificate. "TLS terminates at X" means X is that endpoint — it's the last hop where the traffic is still encrypted; everything past it can be (and usually is) plain HTTP. Terminating at the ALB means: browser → ALB is HTTPS (real encryption, real certificate, e.g. from ACM), and ALB → Nginx → pods is plain HTTP. This is standard and considered safe because that internal hop never leaves AWS's private network (the VPC) — nothing on the public internet ever sees the unencrypted traffic.

Choosing `operator` lets you create a role scoped to exactly one permission (`sqs:GetQueueAttributes`, nothing else) purely for reading queue depth — separate from whatever broader role the actual worker pods need for processing jobs (read/write/delete messages, S3 access, etc.). This is a straightforward least-privilege split: the component that only *checks* the queue doesn't need the same permissions as the component that *processes* it.
