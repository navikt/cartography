import logging
import os
from typing import Any

import neo4j

import cartography.intel.nais.teams
import cartography.intel.nais.workloads
from cartography.client.core.tx import load
from cartography.config import Config
from cartography.intel.nais.client import NaisGraphQLClient
from cartography.models.nais.tenant import NaisTenantSchema
from cartography.util import run_analysis_job
from cartography.util import timeit

logger = logging.getLogger(__name__)


def _load_tenant(
    neo4j_session: neo4j.Session,
    tenant_id: str,
    update_tag: int,
) -> None:
    load(
        neo4j_session,
        NaisTenantSchema(),
        [{"id": tenant_id}],
        lastupdated=update_tag,
    )


@timeit
def start_nais_ingestion(neo4j_session: neo4j.Session, config: Config) -> None:
    """
    Entry point for NAIS ingestion. Called by the cartography sync framework.
    """
    if not config.nais_api_key or not config.nais_base_url:
        logger.info(
            "NAIS import is not configured - skipping this module. "
            "See docs to configure.",
        )
        return

    tenant_id = config.nais_base_url
    common_job_parameters: dict[str, Any] = {
        "UPDATE_TAG": config.update_tag,
        "TENANT_ID": tenant_id,
    }

    client = NaisGraphQLClient(
        api_key=config.nais_api_key,
        base_url=config.nais_base_url,
    )

    _load_tenant(neo4j_session, tenant_id, config.update_tag)

    cartography.intel.nais.teams.sync(
        neo4j_session,
        client,
        tenant_id,
        config.update_tag,
        common_job_parameters,
    )

    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        tenant_id,
        config.update_tag,
        common_job_parameters,
    )

    analysis_jobs_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data",
        "jobs",
        "analysis",
        "nais",
    )
    for job_file in sorted(os.listdir(analysis_jobs_dir)):
        if job_file.endswith(".json"):
            run_analysis_job(
                os.path.join(analysis_jobs_dir, job_file),
                neo4j_session,
                common_job_parameters,
            )
