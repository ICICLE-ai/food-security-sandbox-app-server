# Food Security Sandbox app server

Tapis OAuth login, chat, the model registry, similar-farmer matching and training requests. It is the only backend the frontend calls: it also forwards the frontend's dataset routes to the farmer server.

## Configuration

Read from environment variables (or a local `.env` file, which is never copied into the image).

| Variable | Value |
|---|---|
| `MONGODB_URI` | MongoDB connection string |
| `SANDBOX_SERVER_URL` | Farmer server URL |
| `PARAM_SERVER_URL` | Param server URL |
| `TAPIS_BASE_URL` | `https://icicleai.tapis.io` |
| `TENANT` | `icicleai` |
| `CLIENT_ID`, `CLIENT_KEY` | Tapis OAuth client credentials |
| `APP_BASE_URL` | Frontend URL |
| `CALLBACK_URL` | `<frontend URL>/api/oauth2/callback`, registered on the Tapis client |
| `HOST`, `PORT`, `DEBUG` | Optional; default `0.0.0.0`, `8000`, `false`. Never enable `DEBUG` on a pod. |

`GET /health` returns `{"status": "ok", "build_sha": ...}` for the deployment check.

## Run locally

```bash
uv sync
uv run python app.py
```

Dependencies are locked with uv: after changing `pyproject.toml`, run `uv lock` and commit `uv.lock`.

## Deployment

Deployed to the `foodsecuritybackend` Tapis pod by `.github/workflows/deploy.yaml`, using the shared
[ICICLE CI/CD templates](https://github.com/ICICLE-ai/cicd-templates/wiki/Quick-start) (`v2.2.1`).
Bump `service-version` in `icicle-service.yaml` and push to `main` to release.
CI checks the rollout through `GET /health`.
