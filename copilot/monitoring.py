"""Content-free operation metrics. Prices are user configured, never guessed."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
import logging
from copilot.models import OperationMetric

active = ContextVar("operation_metrics", default=None)


def provider_attempt(method, status, elapsed):
    trace = active.get()
    if trace is not None:
        trace.setdefault("provider_attempts", []).append(
            {"method": method, "status": status, "latency_ms": round(elapsed * 1000, 2)}
        )


def provider_usage(settings, method, body, elapsed, attempts=1):
    trace = active.get()
    if trace is None:
        return
    usage = body.get("usageMetadata", {})
    inputs = usage.get("promptTokenCount")
    outputs = (
        usage["candidatesTokenCount"] + usage.get("thoughtsTokenCount", 0)
        if "candidatesTokenCount" in usage
        else None
    )
    embedding = method == "batchEmbedContents"
    if embedding:
        outputs = 0
    rate = settings.embedding_usd_per_million if embedding else settings.input_usd_per_million
    out_rate = 0 if embedding else settings.output_usd_per_million
    cost = (
        (inputs * rate + outputs * out_rate) / 1_000_000
        if inputs is not None
        and outputs is not None
        and rate is not None
        and out_rate is not None
        and attempts == 1
        else None
    )
    trace["provider_calls"].append(
        {
            "method": method,
            "latency_ms": round(elapsed * 1000, 2),
            "attempts": attempts,
            "input_tokens": inputs,
            "output_tokens": outputs,
            "estimated_usd": cost,
        }
    )


@contextmanager
def operation(sessions, user, name):
    data = {"provider_calls": [], "status": "ok"}
    token = active.set(data)
    started = perf_counter()
    try:
        yield data
    except BaseException:
        data["status"] = "error"
        raise
    finally:
        active.reset(token)
        data["latency_ms"] = round((perf_counter() - started) * 1000, 2)
        calls = data["provider_calls"]
        data["estimated_usd"] = (
            sum(c["estimated_usd"] for c in calls)
            if all(c["estimated_usd"] is not None for c in calls) and data["status"] == "ok"
            else None
        )
        try:
            with sessions() as session:
                session.add(OperationMetric(tenant=user.tenant, actor=user.actor, operation=name, data=data))
                session.commit()
        except Exception:
            logging.getLogger(__name__).warning("Could not persist operation metrics")
