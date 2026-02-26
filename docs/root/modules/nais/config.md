## NAIS Configuration

Follow these steps to analyze NAIS objects with Cartography.

1. Obtain a NAIS API key for the NAIS Console GraphQL endpoint.
    1. Generate an API key in the NAIS Console for your tenant (e.g. `nav`).
    1. Store the key in an environment variable, e.g. `NAIS_API_KEY`.
    1. Pass the variable name via `--nais-api-key-env-var NAIS_API_KEY`.

1. Set the NAIS Console GraphQL URL.
    1. The base URL is the GraphQL endpoint for your tenant, e.g. `https://console.nav.cloud.nais.io/query`.
    1. Pass it via `--nais-base-url https://console.nav.cloud.nais.io/query`.

1. Complete the Cartography configuration.

    ```bash
    cartography \
      --neo4j-uri bolt://localhost:7687 \
      --nais-api-key-env-var NAIS_API_KEY \
      --nais-base-url https://console.nav.cloud.nais.io/query
    ```

### Required permissions

The API key must have read access to teams, members, applications, jobs, and deployments in the NAIS Console.
