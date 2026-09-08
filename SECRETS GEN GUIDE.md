# Secret Generation Reference

## 32-Character Hex Secrets

**Command:**

```bash
openssl rand -hex 16
```

**Variables:**

```text
POSTGRES_SUPERUSER_PASSWORD
PGPASS_KEYCLOAK
PGPASS_INFISICAL
PGPASS_LITELLM
PGPASS_MLFLOW
PGPASS_LANGFUSE
PGPASS_CUSTODIAN_LEDGER
PGPASS_CUSTODIAN_BACKEND
MINIO_ROOT_PASSWORD
INFISICAL_ENCRYPTION_KEY
INFISICAL_AUTH_SECRET
KEYCLOAK_ADMIN_PASSWORD
KEYCLOAK_BACKEND_CLIENT_SECRET
KEYCLOAK_CONSOLE_CLIENT_SECRET
OM_POSTGRES_ROOT_PASSWORD
LANGFUSE_CLICKHOUSE_PASSWORD
LANGFUSE_REDIS_AUTH
```

## 24-Character Hex Secrets

**Command:**

```bash
openssl rand -hex 12
```

**Variables:**

```text
INFISICAL_ADMIN_PASSWORD
AIRFLOW_ADMIN_PASSWORD
LANGFUSE_INIT_USER_PASSWORD
GRAFANA_ADMIN_PASSWORD
```

## 16-Character Hex Secrets

**Command:**

```bash
openssl rand -hex 8
```

**Variables:**

```text
DEMO_AP_CLERK_PASSWORD
DEMO_CONTROLLER_PASSWORD
DEMO_CFO_PASSWORD
```

## 64-Character Hex Secrets

**Command:**

```bash
openssl rand -hex 32
```

**Variables:**

```text
LANGFUSE_SALT
LANGFUSE_ENCRYPTION_KEY
LANGFUSE_NEXTAUTH_SECRET
CONSOLE_NEXTAUTH_SECRET
```

## Prefixed Secrets

These use a fixed literal prefix followed by `openssl rand -hex N`, glued together.

| Variable                           | Command                                              |
| ---------------------------------- | ---------------------------------------------------- |
| `MINIO_ROOT_USER`                  | `echo "custodian_admin_$(openssl rand -hex 4)"`      |
| `LITELLM_MASTER_KEY`               | `echo "sk-custodian-master-$(openssl rand -hex 16)"` |
| `LEDGER_API_KEY`                   | `echo "ldg-$(openssl rand -hex 16)"`                 |
| `VENDOR_LOOKUP_API_KEY`            | `echo "vlk-$(openssl rand -hex 16)"`                 |
| `LANGFUSE_INIT_PROJECT_PUBLIC_KEY` | `echo "pk-lf-$(openssl rand -hex 16)"`               |
| `LANGFUSE_INIT_PROJECT_SECRET_KEY` | `echo "sk-lf-$(openssl rand -hex 16)"`               |

## Not Generated With OpenSSL

### Real Provider Keys

These must be real keys obtained from each provider's dashboard, not randomly generated:

```text
OPENAI_API_KEY
GROQ_API_KEY
```

### Auto-Filled / Server-Generated Values

These are the `[AUTO-FILLED]` values. Each is generated server-side by Infisical, SPIRE, or LiteLLM itself when its setup script runs:

```text
INFISICAL_ORG_ID
SPIRE_AGENT_JOIN_TOKEN
LITELLM_KEY_AGENT_*
LITELLM_EXTRACTION_KEY
INFISICAL_PROJECT_ID
PAYMENT_EXECUTION_CLIENT_ID
PAYMENT_EXECUTION_CLIENT_SECRET
```

### Plain Fixed Configuration Values

These are normal configuration values, not secrets:

```text
KEYCLOAK_ADMIN
INFISICAL_ADMIN_EMAIL
INFISICAL_ADMIN_ORGANIZATION
SPIRE_TRUST_DOMAIN
USASPENDING_AGENCY
USASPENDING_FISCAL_YEAR
COMPOSE_PROJECT_NAME
```

# Why These Secret Lengths Are Used

## 1. 32 Bytes — 64 Hex Characters

Variables:

```text
LANGFUSE_SALT
LANGFUSE_ENCRYPTION_KEY
LANGFUSE_NEXTAUTH_SECRET
CONSOLE_NEXTAUTH_SECRET
```

These aren't just passwords. They are fed directly into specific cryptographic mechanisms that require a particular key size.

* Langfuse's encryption key uses AES-256, which requires a full **32-byte key**.
* NextAuth's secret is used to encrypt/sign session JWTs, with its documentation calling for **32 bytes**.
* Using a shorter value here isn't simply a matter of reduced strength; it may be the wrong key size for the intended cryptographic algorithm.

## 2. 16 Bytes — 32 Hex Characters

Variables include:

```text
PGPASS_*
MINIO_ROOT_PASSWORD
INFISICAL_ENCRYPTION_KEY
KEYCLOAK_*_SECRET
```

These are generally strong random secrets rather than keys tied to a specific algorithm's key-size requirement.

* **16 bytes = 128 bits** of randomness.
* This is a strong generic default for passwords and application secrets.
* It provides far more entropy than is practical to brute-force when generated using a cryptographically secure random generator such as `openssl rand`.

## 3. 12 Bytes / 8 Bytes — 24 / 16 Hex Characters

Variables include:

```text
INFISICAL_ADMIN_PASSWORD
AIRFLOW_ADMIN_PASSWORD
LANGFUSE_INIT_USER_PASSWORD
GRAFANA_ADMIN_PASSWORD

DEMO_AP_CLERK_PASSWORD
DEMO_CONTROLLER_PASSWORD
DEMO_CFO_PASSWORD
```

These are shorter because they are intended to be manually read and entered into login forms during setup or demonstrations.

* **12 bytes = 96 bits** of randomness.
* **8 bytes = 64 bits** of randomness.
* These values are still generated randomly using OpenSSL rather than being predictable human-created passwords.
