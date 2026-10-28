"""Logging and Azure Monitor (Application Insights) telemetry.

Logs never include ticket text, only IDs, labels, timings and counts. When the Application Insights
connection string is set, OpenTelemetry sends requests, dependencies (SQL, Azure OpenAI) and these
logs to Azure Monitor, where the workbook and alerts in Terraform pick them up.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from triage.settings import Settings

_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        data.update(
            {k: v for k, v in record.__dict__.items() if k not in _STANDARD and not k.startswith("_")}
        )
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


_configured = False


def configure(settings: Settings) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if settings.env == "prod" else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if settings.applicationinsights_connection_string:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string.get_secret_value(),
            logger_name="triage",
        )
