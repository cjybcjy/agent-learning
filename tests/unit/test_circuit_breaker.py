import time
import pytest
from heatmap.collectors.circuit_breaker import CircuitBreaker


def test_initial_state_allows_requests():
    cb = CircuitBreaker(sleep_minutes=15, threshold=0.2, duration_seconds=120)
    assert cb.allow_request() is True
    assert cb.is_tripped is False


def test_circuit_opens_when_threshold_breached():
    cb = CircuitBreaker(sleep_minutes=15, threshold=0.2, duration_seconds=1)
    cb.report_availability(0.15)
    time.sleep(1.1)
    cb.report_availability(0.10)
    assert cb.allow_request() is False


def test_circuit_recovers_after_sleep():
    cb = CircuitBreaker(sleep_minutes=0.001, threshold=0.2, duration_seconds=1)
    cb.report_availability(0.10)
    time.sleep(1.1)
    cb.report_availability(0.10)
    assert cb.allow_request() is False
    time.sleep(0.1)
    assert cb.allow_request() is True


def test_circuit_stays_closed_above_threshold():
    cb = CircuitBreaker(sleep_minutes=15, threshold=0.2, duration_seconds=120)
    for _ in range(10):
        cb.report_availability(0.5)
    assert cb.allow_request() is True
    assert cb.is_tripped is False
