"""Every agent step and LLM call becomes a real span, exported via
OTLP/HTTP to the self-hosted Langfuse instance, using OpenTelemetry's
GenAI semantic conventions (gen_ai.system, gen_ai.request.model, etc.).
"""
import base64
import contextlib
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

LANGFUSE_URL = os.environ.get("LANGFUSE_URL", "http://langfuse-web:3000")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")

_initialized = False


def setup_tracing(app=None):
    global _initialized
    if _initialized:
        return trace.get_tracer("verisettle-backend")

    auth = base64.b64encode(f"{LANGFUSE_PUBLIC_KEY}:{LANGFUSE_SECRET_KEY}".encode()).decode()
    provider = TracerProvider(resource=Resource.create({"service.name": "verisettle-backend"}))
    exporter = OTLPSpanExporter(
        endpoint=f"{LANGFUSE_URL}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}", "x-langfuse-ingestion-version": "4"},
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    RequestsInstrumentor().instrument()
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)

    _initialized = True
    return trace.get_tracer("verisettle-backend")


@contextlib.contextmanager
def llm_span(agent: str, model: str, operation: str = "chat"):
    """Wraps one LLM call with GenAI-convention attributes. Yields a
    callback to record the real token usage once the completion returns -
    real numbers from the provider's response, never estimated."""
    tracer = trace.get_tracer("verisettle-backend")
    with tracer.start_as_current_span(f"{operation} {model}") as span:
        span.set_attribute("gen_ai.system", "litellm")
        span.set_attribute("gen_ai.operation.name", operation)
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.agent.name", agent)

        def record_usage(completion):
            usage = getattr(completion, "usage", None)
            if usage is not None:
                span.set_attribute("gen_ai.usage.input_tokens", usage.prompt_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", usage.completion_tokens)
            response_model = getattr(completion, "model", None)
            if response_model:
                span.set_attribute("gen_ai.response.model", response_model)

        yield record_usage
