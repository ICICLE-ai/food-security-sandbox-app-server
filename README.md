# Food Security Sandbox app server

Tapis OAuth login, chat, the model registry, similar-farmer matching and training requests. It is the only backend the frontend calls: it also forwards the frontend's dataset routes to the farmer server. It is one of the four services of Food Security Sandbox, a collaborative machine learning platform where farmers and researchers analyze agricultural data and train models together with privacy-preserving features.

**Tags:** Smart-Foodsheds, Food-Access

### License

[![License](https://img.shields.io/badge/License-BSD_3--Clause-yellow.svg)](https://opensource.org/licenses/BSD-3-Clause)

Distributed under the BSD 3-Clause License. See [`LICENSE`](LICENSE).

## References

Food Security Sandbox is split into four services, each in its own repository:

- [Food Security Sandbox Frontend](https://github.com/ICICLE-ai/food-security-sandbox-frontend)
- [Food Security Sandbox App Server](https://github.com/ICICLE-ai/food-security-sandbox-app-server) (this repository)
- [Food Security Sandbox Farmer Server](https://github.com/ICICLE-ai/food-security-sandbox-farmer-server)
- [Food Security Sandbox Param Server](https://github.com/ICICLE-ai/food-security-sandbox-param-server)

Related resources:

- [ICICLE CI/CD templates](https://github.com/ICICLE-ai/cicd-templates/wiki), which build and deploy each service
- [Tapis](https://tapis.readthedocs.io/), which provides login (OAuth2) and the pods the services run in
- [Adversarial Robustness Toolbox](https://adversarial-robustness-toolbox.readthedocs.io/), used for membership-inference risk analysis

Key terms:

- **Differential privacy**: adding calibrated random noise to data so that no single record can be singled out.
- **Geo-indistinguishability**: differential privacy for locations; a point is moved by a random distance so nearby places look alike.
- **k-anonymity**: every combination of identifying attributes is shared by at least *k* records.
- **Collaborative (federated) learning**: each farmer trains on their own data, and only model weights are combined.
- **Membership inference attack**: guessing from a model's outputs whether a record was in its training data.

## Acknowledgements

This research was also supported in part by the National Science Foundation (NSF) under award 2112533, and by the United States Department of Agriculture (USDA) under grant number NR233A750004G019.

*National Science Foundation (NSF) funded AI institute for Intelligent Cyberinfrastructure with Computational Learning in the Environment (ICICLE) (OAC 2112606)*

## Issue reporting

Report bugs and request features in [GitHub Issues](https://github.com/ICICLE-ai/food-security-sandbox-app-server/issues).

---

# Tutorials

## Run the app server locally

This walkthrough starts the app server on your machine against a local MongoDB and checks that it responds.

**Prerequisites:** Python 3.12, [uv](https://docs.astral.sh/uv/) and Docker.

1. Start a local MongoDB:

   ```bash
   docker run -d --name mongo -p 27017:27017 mongo:9.0
   ```

2. Create a `.env` file in the repository root:

   ```bash
   MONGODB_URI=mongodb://localhost:27017/food_security_sandbox
   TAPIS_BASE_URL=https://icicleai.tapis.io
   TENANT=icicleai
   CLIENT_ID=<tapis-oauth-client-id>
   CLIENT_KEY=<tapis-oauth-client-key>
   APP_BASE_URL=http://localhost:5000
   CALLBACK_URL=http://localhost:8000/api/oauth2/callback
   SANDBOX_SERVER_URL=http://localhost:8001   # farmer server
   PARAM_SERVER_URL=http://localhost:8002
   ```

All of these variables are required for the server to start. Logging in also needs a Tapis OAuth client that allows `CALLBACK_URL` as a redirect URI; `/health` works without one.

3. Install the dependencies and start the server:

   ```bash
   uv sync
   uv run python app.py
   ```

   Dependencies are locked with uv: after changing `pyproject.toml`, run `uv lock` and commit `uv.lock`.

4. Check that it is up:

   ```bash
   curl http://localhost:8000/health   # {"build_sha": "unknown", "status": "ok", ...}
   ```

---

# How-To Guides

## Configure the app server

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

## Release a new version

Deployed to the `fssback` Tapis pod (image `ghcr.io/icicle-ai/fssback`) by `.github/workflows/deploy.yaml`, using the shared
[ICICLE CI/CD templates](https://github.com/ICICLE-ai/cicd-templates/wiki/Quick-start) (`v2.3.0`).
Bump `service-version` in `icicle-service.yaml` and push to `main` to release.
CI checks the rollout through `GET /health`.

---

# Explanation

## How the services fit together

This repository is the **app server**.

```
browser ──> frontend (fss, Nginx)
              ├─ /         static React build
              └─ /api/...  ─> app server (fssback) ── dataset routes ──> farmer server (fsssandbox)
                                     └── /api/start_training ──> param server (fssparam) ──> farmer server
```

The browser only calls relative `/api/...` URLs. The frontend's Nginx forwards them to the app
server, which is the only backend the browser reaches. All three backends share one MongoDB-compatible
database, and each runs in its own Tapis pod, deployed from its own repository.

## Login

`/api/auth/login` redirects to the Tapis OAuth2 authorize page. Tapis returns to `/api/oauth2/callback`
with a code; the server exchanges it for a Tapis token, stores the session in the `sessions` collection,
and redirects to `APP_BASE_URL` with the token. Every other route resolves the bearer token to a username
through Tapis and requires an unexpired stored session.

## Gateway to the farmer server

The browser never calls the farmer server directly. The app server forwards the dataset routes the UI
uses (`get_user_datasets`, `delete_dataset`, `upload_csv`, `get_dataset_column_info`, `check_k_anonymity`,
`export_dataset_columns`) to `SANDBOX_SERVER_URL`, passing the caller's token along.

## Similar farmers, chat and models

Similar farmers are ranked by Euclidean distance over the selected dataset columns. Chat messages are
stored in MongoDB and loaded with `/api/getMessages`. Training requests create a
model record and hand the work to the param server (`PARAM_SERVER_URL`).
