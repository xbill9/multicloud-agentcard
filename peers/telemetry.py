"""OpenTelemetry setup, shared by the fetcher and the local card specimens.

**What this is not.** It does not replace ``peers/trace.py``. Those two answer
different questions and both are wanted:

``peers/trace.py``
    the evidence layer -- what this process did on the wire, recorded into the
    specimen, shown in the report, kept in the stored corpus. It is the thing
    a reader can check.

this module
    distributed tracing -- what happened on the *other side* of the call, which
    the evidence trace cannot show because it stops at this process's socket.

Carried over from the repo this forked from, where the second half mattered
more: a coordinator fanning out to three clouds wants the remote's model call
and search round trips hanging under its own leg span. Discovery is a single
GET, so here it is mostly the specimens' side that benefits. Kept because it
costs nothing without an exporter configured, and because the alternative --
making it optional -- is how the one deployment that needed traces turns out to
be the one that did not have it installed.
"""

import logging
import os
from contextlib import contextmanager

log = logging.getLogger("telemetry")

#: Where traces go. ``otlp`` needs ``OTEL_EXPORTER_OTLP_ENDPOINT``;
#: ``gcp`` writes to Cloud Trace with the ambient service account and needs no
#: endpoint, which is why it is the right default on Cloud Run and useless
#: anywhere else; ``console`` prints spans to stdout, for a laptop; ``none``
#: installs no exporter at all.
TRACE_EXPORTERS = ("none", "otlp", "gcp", "console")

DEFAULT_SERVICE_NAMESPACE = "agentcard"

_configured = False
_summary: dict = {"enabled": False, "exporter": "none", "service": "", "reason": "not configured"}


def _exporter_choice() -> str:
    explicit = os.getenv("OTEL_TRACES_EXPORTER", "").strip().lower()
    if explicit in TRACE_EXPORTERS:
        return explicit
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return "otlp"
    return "none"


def setup(service_name: str) -> dict:
    """Configure tracing and log correlation for this process. Idempotent.

    Called at import by every server and by the master. Returns the same dict
    ``telemetry_summary()`` does, so a caller can report it without a second
    lookup.

    Never raises. A telemetry backend that is unreachable, misconfigured or
    simply absent must not stop an agent from serving -- the whole mesh once
    lost a leg to an exporter that could not resolve its collector, and a
    research agent that will not start because it cannot report *that it
    started* is the wrong trade in every direction.
    """
    global _configured, _summary
    if _configured:
        return _summary

    _configured = True
    choice = _exporter_choice()
    if choice == "none":
        _summary = {
            "enabled": False,
            "exporter": "none",
            "service": service_name,
            "reason": "set OTEL_TRACES_EXPORTER or OTEL_EXPORTER_OTLP_ENDPOINT",
        }
        return _summary

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.namespace": DEFAULT_SERVICE_NAMESPACE,
                # Which cloud this process is on, so one backend collecting all
                # three can group by it. Set from the agent's own environment
                # rather than inferred: the coordinator is a different container
                # and cannot know.
                "cloud.provider": os.getenv("RESEARCH_CLOUD", "unknown"),
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(_build_exporter(choice)))
        trace.set_tracer_provider(provider)

        _instrument_logging()
        _instrument_httpx()

        _summary = {
            "enabled": True,
            "exporter": choice,
            "service": service_name,
            "reason": "",
        }
        log.info("telemetry: %s exporter, service %s", choice, service_name)
    except Exception as exc:  # noqa: BLE001 - telemetry must never fail a serve
        _summary = {
            "enabled": False,
            "exporter": choice,
            "service": service_name,
            "reason": f"{type(exc).__name__}: {exc}",
        }
        log.warning("telemetry setup failed, continuing without it: %s", exc)

    return _summary


def _build_exporter(choice: str):
    if choice == "gcp":
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        return CloudTraceSpanExporter()
    if choice == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter()


def _instrument_logging() -> None:
    """Put trace and span ids into every log record.

    This is the half of "standard logging" that actually pays: the mesh
    already logs a `run_id` on every line, and this adds the ids that join
    those lines to the spans and to whatever the vendor SDKs emit on their own.
    """
    from opentelemetry.instrumentation.logging import LoggingInstrumentor

    LoggingInstrumentor().instrument(set_logging_format=False)

    # Guarantee the fields the format string names, on every record.
    #
    # The instrumentor supplies them through a log record factory, and a record
    # that predates it -- or is built by a library that constructs its own --
    # does not have them. `logging` then raises inside `formatMessage` while
    # trying to format, which it swallows and prints as a traceback with no
    # message attached to it. Measured on the deployed GCP researcher, where
    # every ADK line ("Sending out request, model: %s...") turned into a
    # KeyError traceback in Cloud Logging, and the actual log was unreadable.
    #
    # A filter rather than a fallback format: it fixes the records instead of
    # giving up the trace correlation the format exists for.
    class _EnsureTraceFields(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            for field in ("otelTraceID", "otelSpanID", "otelServiceName"):
                if not hasattr(record, field):
                    setattr(record, field, "0")
            return True

    logging.basicConfig(
        format=(
            "[%(levelname)s] %(name)s "
            "[trace=%(otelTraceID)s span=%(otelSpanID)s] %(message)s"
        ),
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        force=True,
    )
    guard = _EnsureTraceFields()
    for handler in logging.getLogger().handlers:
        handler.addFilter(guard)


def _instrument_httpx() -> None:
    """Trace every outbound HTTP call, and propagate context on it.

    Propagation is the part worth having. The coordinator's call to a
    researcher carries W3C `traceparent`, so the researcher's spans -- its
    model call, its search round trips -- hang under the coordinator's leg span
    in one trace across three clouds. That is the view the bespoke evidence
    trace cannot produce, because it stops at this process's socket.
    """
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()


def instrument_app(app) -> None:
    """Trace inbound requests to a Starlette app, continuing the caller's trace."""
    try:
        from opentelemetry.instrumentation.starlette import StarletteInstrumentor

        StarletteInstrumentor.instrument_app(app)
    except Exception as exc:  # noqa: BLE001 - never fail a serve for telemetry
        log.warning("could not instrument the app: %s", exc)


def telemetry_summary() -> dict:
    """What telemetry this process actually has, for /health.

    Reported rather than assumed, for the same reason `auth_modes` is: a
    process that *intended* to export traces and could not is indistinguishable
    from one that is exporting them, right up until someone goes looking for a
    trace that was never sent.
    """
    return dict(_summary)


@contextmanager
def span(name: str, **attributes):
    """One span, with attributes, that never raises on a telemetry fault.

    A no-op when telemetry is off, which is the default. Exceptions are
    recorded on the span and re-raised -- the caller's error handling is not
    this module's business.
    """
    try:
        from opentelemetry import trace as _trace

        tracer = _trace.get_tracer("agentcard")
    except Exception:  # noqa: BLE001
        yield None
        return

    with tracer.start_as_current_span(name) as current:
        try:
            for key, value in attributes.items():
                if value is not None:
                    current.set_attribute(key, value)
        except Exception:  # noqa: BLE001,S110 - a bad attribute must not fail the work
            pass
        try:
            yield current
        except Exception as exc:
            try:
                current.record_exception(exc)
                from opentelemetry.trace import Status, StatusCode

                current.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:  # noqa: BLE001,S110
                pass
            raise


__all__ = [
    "TRACE_EXPORTERS",
    "instrument_app",
    "setup",
    "span",
    "telemetry_summary",
]
