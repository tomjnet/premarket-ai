# premarket-ai on Minikube (Kubernetes)

The same stack as `podman compose`, on a single-node **Minikube** cluster in Ubuntu WSL. Nothing in the code, the Containerfiles, `compose.yaml` or `podman/config/` changes:

- **The same images.** `make -C python build` builds them with Podman as before, and `make -C minikube-kubernetes load-images` copies them into the cluster. Nothing is rebuilt and no registry is needed.
- **The same config files.** The kustomizations read `podman/config/*` and `sql/*.sql` in place. Nothing is copied.
- **The same `.env`.** `make -C minikube-kubernetes config` turns it into a ConfigMap (settings) and a Secret (passwords, keys, tokens).
- **The same architecture.** The edge is still the only entry. `web-1` / `web-2` sit behind it, ai-api handles `/api/`, and Ollama keeps running on the GPU host.

Podman compose keeps working, so you can switch between the two. Don't run both at the same time: together they need more memory than WSL has.

## Folder layout
```
minikube-kubernetes/
├── Makefile                  # tasks: start, load-images, config, up, obs-up, web, demo, rules, verify, brief, smoke, ...
├── settings.env              # non-secret settings with compose's defaults (.env values win)
├── scripts/
│   ├── config.sh             # .env -> ConfigMap premarket-settings + Secret premarket-env + the edge's site config
│   └── load-images.sh        # podman save -> minikube image load, for every app image
├── base/                     # compose profile "ai": one file per service (Deployment/Job + Service + PVC)
├── chroma/                   # ChromaDB, applied only while VECTOR_STORE=chroma (like the compose profile)
└── observability/            # compose profile "observability": Langfuse, OTel Collector, Prometheus, Grafana
```

## How compose maps to Kubernetes
| compose.yaml | Kubernetes, here |
|---|---|
| a service | a Deployment plus a ClusterIP Service with the **same name** (`postgres`, `redis`, `ai-api`, `mcp-server`, ...), so every URL in the config still works |
| `ai-api-init` (one-shot, `service_completed_successfully`) | Job `ai-api-init`. Dependent pods wait in an initContainer until their DB role can log in (the init creates the roles last) |
| `depends_on: service_healthy` | initContainers that wait for Postgres / Redis / the gateway / MCP |
| `healthcheck` | readiness, liveness and startup probes (the same commands and URLs) |
| `x-hardened` (read-only, `cap_drop: ALL`, `no-new-privileges`) | `securityContext`: `readOnlyRootFilesystem`, `drop: [ALL]`, `allowPrivilegeEscalation: false` |
| `tmpfs` | `emptyDir: {medium: Memory}` with the same size |
| `mem_limit` | `resources.limits.memory` (with small requests, so the stack fits on one node) |
| named volumes | PersistentVolumeClaims (Minikube's `standard` storage class) |
| `.env` / `${VAR:-default}` | Secret `premarket-env` + ConfigMap `premarket-settings` (`settings.env` defaults, `.env` wins) |
| `sk-${LLM_GATEWAY_KEY}` | Kubernetes `$(VAR)` expansion: `sk-$(LLM_GATEWAY_KEY_RAW)` |
| profiles `ai`, `chroma`, `observability` | `base/`, `chroma/`, `observability/` |
| published port `127.0.0.1:8080` (edge) | `kubectl port-forward svc/edge 8080:8080` (`make -C minikube-kubernetes web`) |
| `podman compose run --rm ai-api-init ai-api <cmd>` | `kubectl exec deploy/scheduler -- ai-api <cmd>`: same base image, same database-owner env |
| `--scale ai-worker=3` | `kubectl -n premarket scale deploy/ai-worker --replicas=3` |

**The one config difference: the edge's upstream names.** nginx re-resolves `web-1`, `web-2` and `ai-api` at runtime through its own `resolver`, which ignores DNS search domains. Podman's DNS answers short names, but kube-dns needs the full name. So `scripts/config.sh` reads `podman/config/edge/templates/edge.conf.template` and rewrites only those three `server` lines to `<name>.premarket.svc.cluster.local`, into the ConfigMap `edge-templates`. The file in the repo stays unchanged, and changes to it reach Kubernetes on the next `make -C minikube-kubernetes up`. Every other client (Python, Go) uses the pod's DNS search domains, so short names like `postgres` and `http://otel-collector:4318` work unchanged.

## 1. Install Minikube and kubectl (Ubuntu / WSL, once)
The project's WSL setup is assumed: `.wslconfig` with 16 GB (`scripts/windows/01_setup-wslconfig.ps1`), systemd, and rootless Podman (`scripts/wsl/02_setup-podman.sh`). No Docker.

```bash
sudo apt install -y make curl git

# kubectl (the latest stable release)
curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && rm kubectl
kubectl version --client

# minikube
curl -LO https://github.com/kubernetes/minikube/releases/latest/download/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube && rm minikube-linux-amd64
minikube version
```

**The Podman driver, rootless.** Minikube runs its node as a Podman container. Rootless Podman needs cgroup v2 with the CPU and memory controllers delegated to your user:
```bash
stat -fc %T /sys/fs/cgroup                                   # must print cgroup2fs
cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers
# must list cpu and memory; if not, delegate them:
sudo mkdir -p /etc/systemd/system/user@.service.d
printf '[Service]\nDelegate=cpu cpuset io memory pids\n' | sudo tee /etc/systemd/system/user@.service.d/delegate.conf
sudo systemctl daemon-reload     # then, from Windows: wsl --shutdown, and open Ubuntu again
```
If `stat` prints `tmpfs` (cgroup v1), add `kernelCommandLine = cgroup_no_v1=all` under `[wsl2]` in `.wslconfig` and run `wsl --shutdown`.

```bash
minikube config set driver podman
minikube config set rootless true
minikube config set container-runtime containerd
```

## 2. Get the code and prepare `.env`
All commands run from the repo root in Ubuntu WSL (`~/src/premarket-ai`), never from `/mnt/c` or `/mnt/d`.
```bash
git clone https://github.com/tomjnet/premarket-ai.git ~/src/premarket-ai
cd ~/src/premarket-ai
git switch inc-8-minikube-kubernetes
ls                                   # compose.yaml cpp docs minikube-kubernetes podman python scripts sql ui
```
Then create `.env`, the same file compose uses:
```bash
cp .env.example .env
make -C python env                   # prints "generated REDIS_PASSWORD", "generated JWT_SECRET", ...
scripts/wsl/03_check-ollama.sh       # prints the OLLAMA_BASE_URL to use (the GPU host's LAN address)
```
Put the printed address in `.env`, for example:
```bash
sed -i 's#^OLLAMA_BASE_URL=.*#OLLAMA_BASE_URL=http://10.0.0.156:11434#' .env
grep -c . .env                       # well over 100 lines; 22 means the wrong branch
```
Two rules that `make -C minikube-kubernetes up` checks before it deploys anything:
- **Every secret must be filled in.** Otherwise the error is `empty in .env: REDIS_PASSWORD ...`. Run `make -C python env` on this branch; older branches' `env` task doesn't generate secrets.
- **`OLLAMA_BASE_URL` can't be `host.containers.internal`.** That name only exists in Podman; pods can't resolve it. Use the LAN address that `03_check-ollama.sh` prints. It's a DHCP address, so rerun the script if LLM calls stop working after a reboot.

For the demo day, also set **`SEC_USER_AGENT`** (a name and a contact email, which SEC requires on every download). Without it, `corpus` stops the demo and the FAKE_COMPANY / FAKE_TICKER checks are skipped:
```bash
sed -i 's#^SEC_USER_AGENT=.*#SEC_USER_AGENT=Jane Doe jane@example.com#' .env
```

`.env` is read when `up` runs. After changing it later, run `make -C minikube-kubernetes up restart`.

## 3. Start the cluster
```bash
make -C minikube-kubernetes start      # minikube start --driver=podman --container-runtime=containerd --cpus=6 --memory=12g --disk-size=60g
kubectl get nodes                      # minikube   Ready
```
12 GB fits the stack (the reranker alone may use 4 GB, the worker 3 GB) and leaves about 4 GB for WSL itself. With the observability overlay as well, stop other containers first. For a smaller demo, use `make -C minikube-kubernetes start MEMORY=10g`.

## 4. Build and load the images
The images are the ones Podman compose uses:
```bash
make -C python build                              # the images, in Podman
make -C minikube-kubernetes load-images           # podman save | minikube image load, for all 7 app images
```
After you rebuild an image, load it again and restart that Deployment:
```bash
make -C python build && make -C minikube-kubernetes load-images && make -C minikube-kubernetes restart SVC=ai-api
```
Public images (pgvector, Redis, LiteLLM, text-embeddings-inference, SearXNG, nginx, Langfuse, ...) are pulled by the cluster, with the same pinned tags as `compose.yaml`.

## 5. Run
```bash
make -C minikube-kubernetes up         # config + apply base (+ chroma) + re-run ai-api-init, wait until ready
make -C minikube-kubernetes ps         # pods, the init Job (Completed) and the volumes
make -C minikube-kubernetes web        # port-forward: http://localhost:8080 (Ctrl+C to stop)
```
Keep `make ... web` running in its own terminal. WSL forwards `localhost`, so the Windows browser opens `http://localhost:8080` directly. Demo logins: `trader1`, `analyst1`, `admin1`, with the password `DEMO_USER_PASSWORD` from `.env`.

The first `up` takes a while: it pulls the public images and downloads the reranker model (about 1 GB) into the `hf-models` volume.

**Fresh data every day.** Every task defaults to **today's date in New York** (`DATE ?= $(shell TZ=America/New_York date +%F)`, as in `python/Makefile`). vendor-sim generates a new feed for any date (the same seed and date always give the same 100 items). So each day, just run:
```bash
make -C minikube-kubernetes demo
```
That day's run ingests the 5 previous days as history plus today, runs the rules and the AI, verifies, writes the brief and runs `smoke` for today. `corpus` only adds the new SEC and Fed documents since the last run. Run a day once: to see an older or fixed day, pass it, for example `DATE=2026-09-25` (the evals' golden-set day). With `RUN_MODE=production`, the scheduler runs the same timeline by itself on NYSE trading days; in `demo` mode (the default) you start it.

**A faster demo.** The first `demo` spends about 20 minutes in `corpus`: it downloads about 600 SEC and Fed documents and embeds about 5,000 chunks on the GPU host. This happens once:
- **Later runs are incremental.** `corpus` embeds only chunks that aren't indexed yet, so the next `demo` takes seconds there.
- **Ctrl+C is safe.** Progress is saved every 32 chunks. Finish it later with `make -C minikube-kubernetes corpus`, then run the rest of the day with `make -C minikube-kubernetes ingest rules enrich verify brief scorecard smoke DATE=...`.
- **`make -C minikube-kubernetes demo CORPUS=false` skips it.** "Ask the News" then has no trusted sources to cite, so `smoke`'s citation check fails until a corpus exists.
- **A smaller corpus, on a fresh database:** set `CORPUS_MONTHS=3`, `CORPUS_MAX_FILINGS=2` and `CORPUS_MAX_RELEASES=10` in `.env` (the defaults are 12, 8 and 40), then run `make -C minikube-kubernetes up restart`. Chunks already downloaded are still embedded, so this only helps before the first `corpus` or after `reset`.

| Task | What it does |
|---|---|
| `make -C minikube-kubernetes demo` | the whole day for **today** (New York date): history ingest + rules, corpus, ingest, rules, enrich, verify, brief, scorecard, smoke. `DATE=YYYY-MM-DD` runs another day |
| `ingest`, `rules`, `enrich`, `corpus`, `verify`, `brief`, `scorecard`, `smoke`, `demo-open`, `retention` | the same commands as `make -C python`, for today unless `DATE=...` is given |
| `schedule-plan`, `sla`, `mcp-tools`, `feed-summary`, `llm-status` | as in `make -C python` |
| `logs SVC=ai-worker` | follow one service (no SVC: every pod) |
| `psql` | psql on the premarket database |
| `mcp` | port-forward the MCP server to `http://localhost:8765/mcp` |
| `restart [SVC=<name>]` | roll one Deployment (after `load-images`), or all of them (after a `.env` change) |
| `down` | remove the Deployments, Services and the Job; volumes, config and secrets are kept |
| `reset` | delete the namespace: **all data** |
| `stop` / `delete-cluster` | stop Minikube / delete the cluster |

`make -C minikube-kubernetes help` lists every task.

**Settings.** Edit `.env` as usual, then run `make -C minikube-kubernetes up restart`. Pods read the settings and secrets only when they start. `up` updates the ConfigMap and Secret, and `restart` (without `SVC`) rolls every Deployment. When a file under `podman/config/` changes, `up` alone is enough: those ConfigMaps get a new name, which rolls their pods.

**The vector store.** While `VECTOR_STORE=chroma` (the default), `up` also applies `chroma/`. After `make -C python migrate-vectors` sets `VECTOR_STORE=pgvector` in `.env`, it doesn't.

## 6. Observability (optional)
```bash
make -C minikube-kubernetes obs-up     # Langfuse, OTel Collector, Prometheus, Grafana
make -C minikube-kubernetes grafana    # http://localhost:3001  (admin / GRAFANA_ADMIN_PASSWORD)
make -C minikube-kubernetes langfuse   # http://localhost:3000  (LANGFUSE_INIT_USER_EMAIL / LANGFUSE_INIT_USER_PASSWORD)
make -C minikube-kubernetes obs-down   # remove it; the volumes are kept
```
For metrics, set `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` in `.env`. For traces, set `LANGFUSE_TRACING=true`. Then run `make -C minikube-kubernetes up`.

## 7. Test (the "done when" check)
```bash
make -C minikube-kubernetes up
make -C minikube-kubernetes demo DATE=2026-09-25     # ends with `ai-api smoke` through the edge: must pass
curl -s http://localhost:8080/edge-health            # while `make ... web` runs: ok
kubectl kustomize --load-restrictor LoadRestrictionsNone minikube-kubernetes/base | kubectl apply --dry-run=server -f -
```
Unit tests, lint and sanitizers are unchanged: they run in the Containerfile stages with `make -C python test lint sanitizers`.

## Troubleshooting
- **`502 Bad Gateway`, pods stuck in `Init:0/1`, DNS `connection timed out`** (even a pod IP times out): the Minikube node image also starts a Docker daemon, which sets the node's iptables `FORWARD` policy to `DROP`, so pods can't reach each other. `make -C minikube-kubernetes node-net` allows the pod network (`10.244.0.0/16`); `start` and `up` run it for you. After a `minikube stop`/`start` done by hand, run `node-net` (or `up`) again.
- **`ErrImageNeverPull`**: the image isn't in the node. Run `make -C minikube-kubernetes load-images`, then check `minikube image ls | grep premarket-ai`.
- **`redis.exceptions.AuthenticationError` or `password authentication failed` after re-creating `.env`**: `make -C python env` generated new secrets, but pods that haven't restarted still use the old ones. Run `make -C minikube-kubernetes up restart`: `up` re-runs `ai-api-init`, which sets the database roles to the new passwords, and `restart` rolls every pod. Wait until it returns before running tasks.
- **A namespace from an earlier try** (`kubectl get ns premarket`): its `pgdata` volume keeps the old `POSTGRES_PASSWORD`. `make -C minikube-kubernetes reset` starts clean.
- **A pod stays in `Init:0/1`**: it waits for `ai-api-init`. Check with `kubectl -n premarket logs job/ai-api-init` (a wrong password in `.env`, or a `pgdata` volume created with another `POSTGRES_PASSWORD`: `make ... reset` starts clean).
- **LLM calls fail**: the gateway calls `OLLAMA_BASE_URL` from `.env` (the GPU host's LAN address from `scripts/wsl/03_check-ollama.sh`). Test it from inside the cluster: `kubectl -n premarket exec deploy/llm-gateway -- python3 -c "import urllib.request,os;print(urllib.request.urlopen(os.environ['OLLAMA_BASE_URL']+'/api/tags').status)"`.
- **OOMKilled / Pending pods**: give Minikube more memory (`minikube delete && make ... start MEMORY=14g`, within `.wslconfig`), or stop the observability overlay.
- **`minikube start` fails with a cgroup error**: see the delegation step in section 1. As a last resort, use rootful Podman: `minikube config set rootless false`, which needs passwordless `sudo podman`.
- **Login says "Origin not allowed"**: open the site on `http://localhost:$WEB_PORT` (the port-forward), not on the Minikube IP.
- **Rate limits count everyone as one client**: behind `kubectl port-forward`, the edge sees every request as coming from `127.0.0.1`. This is the same as rootless Podman's port forwarder: the limits still act as a ceiling.
