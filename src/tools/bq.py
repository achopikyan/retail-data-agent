"""BigQuery client wrapper.

The BigQueryRunner class is the one provided in the assignment, kept
as-is. We only add a `dry_run_query` helper for free SQL validation
(used by the LangGraph validator node).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class BigQueryRunner:
    """A lean BigQuery client for executing SQL queries and returning DataFrame results."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        dataset_id: Optional[str] = "bigquery-public-data.thelook_ecommerce",
    ) -> None:
        logger.info("Initializing BigQuery client")
        try:
            self.client = bigquery.Client(project=project_id)
            self.dataset_id = dataset_id
            logger.info("BigQuery client initialized for dataset: %s", self.dataset_id)
        except Exception as e:
            logger.error("Failed to initialize BigQuery client: %s", e)
            raise

    def execute_query(self, sql_query: str) -> pd.DataFrame:
        """Execute a SQL query and return results as a DataFrame."""
        try:
            logger.info("Executing BigQuery query")
            query_job = self.client.query(sql_query)
            df = query_job.result().to_dataframe()
            logger.info("Query completed successfully, returned %d rows", len(df))
            return df
        except Exception as e:
            logger.error("BigQuery execution failed: %s", e)
            raise

    def get_table_schema(self, table_name: str) -> List[Dict[str, Any]]:
        """Get schema information for a specific table."""
        try:
            table_ref = f"{self.dataset_id}.{table_name}"
            table = self.client.get_table(table_ref)
            schema_info = []
            for field in table.schema:
                schema_info.append(
                    {
                        "name": field.name,
                        "type": field.field_type,
                        "mode": field.mode,
                        "description": field.description or "",
                    }
                )
            logger.info("Retrieved schema for table %s", table_name)
            return schema_info
        except Exception as e:
            logger.error("Failed to get schema for table %s: %s", table_name, e)
            raise

    def dry_run_query(self, sql_query: str) -> Tuple[bool, Optional[str], int]:
        """Validate a SQL query without running it (free).

        Returns (is_valid, error_message, bytes_scanned).
        """
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        try:
            job = self.client.query(sql_query, job_config=job_config)
            return True, None, int(job.total_bytes_processed or 0)
        except Exception as e:
            return False, str(e), 0


def get_schema_summary(runner: BigQueryRunner) -> str:
    """Compact schema summary for the SQL-gen prompt.

    Uses the four required tables: orders, order_items, products, users.
    """
    tables = ("orders", "order_items", "products", "users")
    lines: List[str] = []
    for t in tables:
        try:
            schema = runner.get_table_schema(t)
        except Exception:
            continue
        cols = ", ".join(f"{c['name']}:{c['type']}" for c in schema)
        lines.append(f"- {t}: {cols}")
    return "\n".join(lines)
