# Leafline: microservices + SOAP + Jenkins CI/CD (STQA Practical 9)

The Leafline plant shop (Flask + SQLite, SOAP 1.1 via Spyne/Zeep) split into **4 containerised
microservices**, with a **Jenkins pipeline** that builds, tests (with coverage) and verifies the whole
stack end to end over SOAP.

## Architecture

```
                     browser / SOAP client / Locust
                                  │  :5000
                        ┌─────────▼─────────┐
                        │      gateway      │  storefront, REST API (/api/*), SOAP console,
                        │   (Flask, :5000)  │  SOAP reverse proxy  /soap/<service>/
                        └───┬─────┬─────┬───┘
              SOAP / WSDL   │     │     │
          ┌─────────────────┘     │     └───────────────────┐
┌─────────▼────────┐   ┌──────────▼─────────┐   ┌───────────▼────────┐
│ catalog-service  │   │    auth-service    │   │   order-service    │
│  :5001  SOAP     │   │   :5002  SOAP      │   │    :5003  SOAP     │
│  products, stock │   │  users, tokens     │   │  cart, checkout    │
│  catalog-data 🗄 │   │  auth-data 🗄      │   │  order-data 🗄     │
└─────────▲────────┘   └──────────▲─────────┘   └───────┬─────┬──────┘
          │   ReserveStock /      │  ValidateToken      │     │
          └───ReleaseStock (SOAP)─┼─────────────────────┘     │
                                  └───────────────────────────┘
```

| Service | Folder | SOAP operations | Owns |
|---|---|---|---|
| catalog-service | `catalog-service/` | `ListCategories`, `SearchProducts`, `GetProduct`, `CheckStock` (+ internal `ReserveStock`, `ReleaseStock`) | products |
| auth-service | `auth-service/` | `Register`, `Login` (+ internal `ValidateToken`) | users, tokens |
| order-service | `order-service/` | `ViewCart`, `AddToCart`, `RemoveFromCart`, `Checkout`, `ListOrders` (all need the `AuthHeader` SOAP header) | cart, orders |
| gateway | `gateway/` | none of its own; proxies the three WSDLs and offers the original REST API on top of SOAP | nothing |

### How SOAP shaped the design
* **Every service is a SOAP service** with its own WSDL: `http://localhost:5000/soap/{catalog,auth,orders}/?wsdl`.
* **Services talk to each other over SOAP** (Zeep clients): `order-service` calls `auth-service.ValidateToken`
  and `catalog-service.GetProduct / ReserveStock / ReleaseStock`.
* **The session token stays in a SOAP header** (`<ns:AuthHeader><ns:token>…`), as in the original.
* **Errors are SOAP Faults** with the same codes as before (`Client.ProductNotFound`, `Client.Unauthorized`,
  `Client.EmptyCart`, `Client.OutOfStock`, …). The gateway maps them to HTTP status codes for the REST API.
* **Internal operations are not exposed.** The gateway proxy answers `ReserveStock`, `ReleaseStock` and
  `ValidateToken` with a `403 Client.Forbidden` fault; the three SOAP services publish no host port at all.
* **Checkout across services** claims the cart atomically, reserves stock in the catalog, records the order,
  and *compensates* (releases stock, restores the cart) if any step fails.
* **One database per service** (a named Docker volume each). The original's single shared SQLite file would
  have coupled the services.

## Run it

```bash
docker compose up --build              # http://localhost:5000  (storefront)
                                       # http://localhost:5000/soap-console  (SOAP console, shows real XML)
docker compose --profile test run --rm smoke-tests    # end-to-end SOAP tests against the running stack
docker compose down -v                 # stop + delete the databases
```
Without Docker (Python 3.10 required by spyne 2.13.16): start each service folder with
`python app.py` after setting `AUTH_WSDL` / `CATALOG_WSDL` (order-service) and `*_URL` / `*_WSDL` (gateway).

## Tests and coverage (written with AI)

Each service has its own `tests/` folder, `pytest.ini` and `.coveragerc`:

```bash
cd catalog-service
pip install -r requirements-dev.txt
pytest                    # runs tests + prints coverage; writes reports/{coverage.xml,htmlcov/,junit.xml}
```

| Service | Unit tests | Line + branch coverage |
|---|---|---|
| catalog-service | 20 | 100% |
| auth-service | 11 | 100% |
| order-service | 28 | 100% |
| gateway | 34 | 100% |
| **integration-tests/** (live stack, real SOAP via Zeep) | 17 | n/a |

**Quality gate:** `.coveragerc` sets `fail_under = 80`, so pytest (and therefore the Jenkins build) fails if a
service drops below 80%.

**How AI was used.** The test suites were generated with Claude from the source code, using prompts like:

> *"For this Spyne SOAP service, write pytest tests that call every operation through Flask's test client with
> real SOAP envelopes. Cover the happy path, every SOAP Fault code, input validation, the AuthHeader, and
> boundary values (qty 0/1/20/21, page 0/past the end). Aim for branch coverage, then list any
> branch you could not reach."*
>
> *"order-service calls other services. Replace those clients with fakes and test the failure paths of Checkout:
> out of stock on the 2nd line, upstream outage, and a database error after stock was reserved."*

The AI output was then **checked, not trusted**: coverage only shows lines were *executed*, so three
deliberate bugs were injected (skip the stock rollback, stop blocking internal operations, remove the stock
check in `ReserveStock`). Each was caught by the tests. Writing the integration tests also exposed a real bug:
Zeep returns fault codes as `soap11env:Client.X`, which `order-service` would have re-emitted with a doubled
prefix. The fix is in `order-service/clients.py` and `gateway/soap_clients.py`, and the integration tests
now assert exact fault codes.

## Jenkins

`Jenkinsfile` (declarative, at the repo root):

| Stage | What it does |
|---|---|
| Checkout | `checkout scm`, prints Docker/Compose versions |
| Build test images | `docker build --target test` for the 4 services, in parallel |
| Unit tests + coverage | runs pytest in each test image (parallel); copies `reports/` out with `docker cp`; fails on a test failure or coverage < 80% |
| Build images | `docker compose build` |
| SOAP integration tests | `docker compose up -d --wait`, then the `smoke-tests` container exercises all three WSDLs through the gateway |
| Deploy | `docker compose up -d` as project `leafline`, **only on `main`** |
| post | JUnit results, archived reports, a coverage table in the console, HTML coverage + trend (if the optional plugins exist), `docker compose down -v` |

**Set up Jenkins (works on Windows, macOS, Linux with Docker Desktop):**
```bash
cd jenkins
docker compose up -d --build
docker compose exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword   # unlock http://localhost:8080
```
Then: push this folder to a Git repository → **New Item → Pipeline → Pipeline script from SCM** → Git URL, branch
`main`, Script Path `Jenkinsfile` → **Build Now**. (The `jenkins/` image already contains the Docker CLI,
Compose and the plugins: Pipeline, Git, JUnit, HTML Publisher, Coverage.)

Where to look after a build: *Test Result* (JUnit), *Coverage - <service>* (HTML), the console's coverage
summary, and *Build Artifacts → reports/*.

## Repository layout
```
docker-compose.yml        4 services + smoke-tests (profile "test")
Jenkinsfile               the pipeline
catalog-service/ auth-service/ order-service/ gateway/
    Dockerfile  .dockerignore  requirements*.txt  pytest.ini  .coveragerc  tests/  *.py
integration-tests/        end-to-end SOAP tests + smoke_client.py (readable demo of the SOAP flow)
jenkins/                  Jenkins image with Docker CLI + plugins
load-tests/               original Locust files (REST API is unchanged)
```
Each Dockerfile has three stages: `base` (pinned deps), `test` (adds pytest + tests; used by Jenkins) and
`runtime` (non-root user, only the app files, a `/health` HEALTHCHECK, gunicorn).
