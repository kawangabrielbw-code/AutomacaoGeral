"""Connectors package for Observatório de Diadema data sources."""
from .metabase_card_connector import (
    MetabaseCardConnector,
    MetabaseConnectorError,
    MetabaseHTTPError,
    MetabaseTimeoutError,
    MetabaseJSONError,
    MetabaseSchemaError,
    MetabaseExportError,
)
from .google_sheets_connector import (
    GoogleSheetsConnector,
    GoogleSheetsError,
    GoogleSheetsAuthRequiredError,
    GoogleSheetsHTTPError,
    GoogleSheetsTimeoutError,
    GoogleSheetsValidationError,
    extract_sheet_id_and_gid,
)

__all__ = [
    "MetabaseCardConnector",
    "MetabaseConnectorError",
    "MetabaseHTTPError",
    "MetabaseTimeoutError",
    "MetabaseJSONError",
    "MetabaseSchemaError",
    "MetabaseExportError",
    "GoogleSheetsConnector",
    "GoogleSheetsError",
    "GoogleSheetsAuthRequiredError",
    "GoogleSheetsHTTPError",
    "GoogleSheetsTimeoutError",
    "GoogleSheetsValidationError",
    "extract_sheet_id_and_gid",
]
