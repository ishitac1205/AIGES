# Hybrid Public Hosting

This deployment mode keeps the full AEGIS control plane on your machine and publishes only the dashboard through Vercel.

Architecture:

- Vercel hosts the React dashboard from `dashboard/`
- your PC hosts the Online Boutique stack, observability stack, AEGIS backend, models, and SQLite stores
- ngrok exposes the backend on `https://...ngrok.app`
- the Vercel dashboard talks directly to that public backend URL

This is the supported public path when you want to preserve current localhost behavior, including:

- live topology and infrastructure data
- model insights
- system logs and reports
- the bounded public demo button
- Docker-backed remediation from the same machine

## What Stays On Your Machine

- `docker-compose.yml`: boutique services + observability
- `docker-compose.platform.yml`: AEGIS backend container
- `models/aegis_models`: runtime model artifacts
- `backend/.runtime/*.db`: incidents, logs, demo runs, reports, memory
- Docker socket access for remediation

## What Goes To Vercel

- `dashboard/` only

Do not deploy the FastAPI backend to Vercel. The backend is a long-running control plane with background loops, Docker/Kubernetes control, local model loading, and SQLite persistence.

## 1. Prepare Your Machine

Start the application stack:

```bash
cd /Users/ishu/Hackathon/AIGES
docker compose up -d
```

Create the public environment file:

```bash
cp .env.public.example .env.public
```

Edit `.env.public` and set at least:

- `AEGIS_ALLOWED_ORIGINS`
- `AEGIS_API_TOKEN`
- `AEGIS_DOCKER_NETWORK`
- `AEGIS_PUBLIC_SITE_ORIGIN`
- `AEGIS_PUBLIC_DEMO_ENABLED=true`

Recommended values:

- `AEGIS_ALLOWED_ORIGINS=http://localhost:5173,https://your-vercel-site.vercel.app,https://your-stable-backend.ngrok.app`
- `AEGIS_DOCKER_NETWORK=aiges_boutique`
- `AEGIS_PUBLIC_DEMO_SERVICES=recommendationservice`

## 2. Run The Hosted Backend On Your Machine

Start only the backend container with the public env file:

```bash
docker compose --env-file .env.public -f docker-compose.platform.yml up -d --build aegis-backend
```

Why this container matters:

- it mounts `./backend/.runtime` so reports and incident history survive restarts
- it mounts `/var/run/docker.sock` so remediation can control the local boutique containers
- it uses the same trained model artifacts packaged into the image

Verify it:

```bash
curl http://localhost:8001/health
curl http://localhost:8001/demo/policy
curl http://localhost:8001/topology
```

## 3. Expose The Backend With ngrok

Install and authenticate ngrok:

```bash
brew install ngrok
ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN
```

Use the example config in `infra/ngrok/ngrok.yml.example` or open a tunnel directly:

```bash
ngrok http 8001
```

Important:

- the Vercel dashboard must point to the backend ngrok URL, not to the local dashboard container
- if possible, reserve a stable ngrok domain so your Vercel env does not need to be changed every session

Optional:

- expose `8080` on a second tunnel if you also want the public storefront visible

## 4. Deploy The Dashboard To Vercel

In Vercel:

1. import the GitHub repo
2. set the project root directory to `dashboard`
3. keep the build command as `npm run build`
4. keep the output directory as `dist`
5. add the environment variable:

```text
VITE_API_BASE_URL=https://your-stable-backend.ngrok.app
```

The repo includes `dashboard/vercel.json` so the project has an explicit static build contract.

## 5. Configure CORS Correctly

Your backend must allow:

- `http://localhost:5173`
- your Vercel production domain
- optional preview domains if you use them

Set that through:

- `AEGIS_ALLOWED_ORIGINS`

If the Vercel UI loads but all fetches fail, this is usually the first thing to check.

## 6. Public Demo Behavior

The public site now uses a dedicated bounded route:

- `POST /demo/public-run`

This is intentionally narrower than the operator route:

- only allowed when `AEGIS_PUBLIC_DEMO_ENABLED=true`
- only allowed for services in `AEGIS_PUBLIC_DEMO_SERVICES`
- only one demo can run at a time
- cooldown is enforced by `AEGIS_PUBLIC_DEMO_COOLDOWN_S`
- per-viewer rate limiting is enforced by `AEGIS_PUBLIC_DEMO_RATE_LIMIT` and `AEGIS_PUBLIC_DEMO_WINDOW_S`

Operator-only actions such as manual remediation still require the secret operator token.

## 7. Local And Public Parity Checks

Check these before you announce the public URL:

```bash
curl http://localhost:8001/health
curl http://localhost:8001/infrastructure
curl http://localhost:8001/ml/insights
curl http://localhost:8001/events?limit=20
curl http://localhost:8001/logs?limit=20
curl http://localhost:8001/demo/policy
```

Then open the Vercel site and confirm:

- Solar System loads
- Infrastructure loads
- Model Insights loads
- System Logs loads
- the demo button starts a real run
- alerts, health, logs, and report update end to end

## 8. Restart And Persistence Checks

Restart the hosted backend container:

```bash
docker compose --env-file .env.public -f docker-compose.platform.yml restart aegis-backend
```

Then verify:

- `backend/.runtime/aegis_system.db` still contains demo runs and logs
- `backend/.runtime/incident_memory.db` still contains incident memory
- `/demo/latest` still returns the latest stored run

## 9. What Remains Private

Keep these private unless you explicitly want to expose them:

- Grafana
- Jaeger
- Prometheus
- Loki

The dashboard already aggregates the backend view of those systems, so public users do not need direct access to those tools.

## 10. Shutdown

Stop the hosted backend:

```bash
docker compose -f docker-compose.platform.yml down
```

Stop the boutique stack:

```bash
docker compose down
```
