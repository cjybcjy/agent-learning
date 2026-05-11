import time
import logging

LOG = logging.getLogger("heatmap.circuit_breaker")


class CircuitBreaker:
    """Circuit breaker for proxy pool health.

    When proxy pool availability drops below threshold for longer than
    duration_seconds, the circuit opens (trips) and all collectors sleep
    for sleep_minutes to protect proxy resources and server load.
    """

    def __init__(
        self,
        sleep_minutes: float = 15.0,
        threshold: float = 0.2,
        duration_seconds: float = 120.0,
    ):
        self.sleep_seconds = sleep_minutes * 60
        self.threshold = threshold
        self.duration_seconds = duration_seconds
        self._low_since: float | None = None
        self._tripped_at: float | None = None
        self._last_availability: float = 1.0

    def report_availability(self, available_ratio: float) -> None:
        """Called by ProxyPool after each health check."""
        self._last_availability = available_ratio
        now = time.monotonic()

        if available_ratio < self.threshold:
            if self._low_since is None:
                self._low_since = now
            elif (now - self._low_since) >= self.duration_seconds:
                if self._tripped_at is None:
                    self._tripped_at = now
                    LOG.warning(
                        "Circuit BREAKER TRIPPED: availability %.1f%% < %.0f%% for %.0fs. Sleeping %.0f min.",
                        available_ratio * 100, self.threshold * 100,
                        self.duration_seconds, self.sleep_seconds / 60,
                    )
        else:
            self._low_since = None

    def allow_request(self) -> bool:
        """Check if requests should be allowed."""
        if self._tripped_at is None:
            return True
        elapsed = time.monotonic() - self._tripped_at
        if elapsed >= self.sleep_seconds:
            self._tripped_at = None
            self._low_since = None
            LOG.info("Circuit breaker recovered after %.1f min sleep.", elapsed / 60)
            return True
        return False

    @property
    def is_tripped(self) -> bool:
        return self._tripped_at is not None and not self.allow_request()

    def probe_success(self) -> None:
        """Call after a successful probe request to confirm recovery."""
        self._tripped_at = None
        self._low_since = None
        LOG.info("Circuit breaker: probe successful, recovery confirmed.")
