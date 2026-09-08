"""Bounded passive learning for KAISAI KHX heat-curve control."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise
from math import floor, isfinite
from typing import Any, Final, Literal

ADAPTIVE_STORAGE_VERSION: Final = 1
ADAPTIVE_CORRECTION_LIMIT: Final = 3.0
ADAPTIVE_BUCKET_WIDTH: Final = 5.0
ADAPTIVE_SAMPLE_INTERVAL: Final = timedelta(minutes=15)
ADAPTIVE_CONTINUITY_MAX_GAP: Final = timedelta(minutes=30)
ADAPTIVE_UPDATE_INTERVAL: Final = timedelta(hours=1)
ADAPTIVE_SAMPLE_TOLERANCE: Final = timedelta(minutes=30)
ADAPTIVE_HISTORY_RETENTION: Final = timedelta(hours=36)
ADAPTIVE_LEARNING_RATE: Final = 0.2
ADAPTIVE_MAX_UPDATE_STEP: Final = 0.25
ADAPTIVE_ERROR_DEADBAND: Final = 0.1
ADAPTIVE_FULL_CONFIDENCE_UPDATES: Final = 12
ADAPTIVE_MAX_STORED_SAMPLES: Final = 160

type AdaptiveLearningPhase = Literal["observing", "blending", "active", "paused"]


def adaptive_storage_key(entry_id: str) -> str:
    """Return the per-config-entry adaptive-learning storage key."""
    return f"kaisai_khx.adaptive_learning.{entry_id}"


def _finite_number(value: Any) -> float | None:
    """Return a finite float without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if isfinite(numeric) else None


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a timezone-aware ISO timestamp."""
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _bucket_center(ambient_temperature: float) -> float:
    """Return the centre of a stable five-degree ambient bucket."""
    return floor(ambient_temperature / ADAPTIVE_BUCKET_WIDTH) * ADAPTIVE_BUCKET_WIDTH + (ADAPTIVE_BUCKET_WIDTH / 2)


def _bucket_key(center: float) -> str:
    return f"{center:.1f}"


@dataclass(frozen=True, slots=True)
class AdaptiveBucket:
    """One learned correction for an ambient-temperature range."""

    correction: float = 0.0
    updates: int = 0

    @classmethod
    def from_dict(cls, stored: Any) -> AdaptiveBucket | None:
        if not isinstance(stored, dict):
            return None
        correction = _finite_number(stored.get("correction"))
        updates = stored.get("updates")
        if correction is None or isinstance(updates, bool) or not isinstance(updates, int) or updates < 0:
            return None
        return cls(
            correction=round(
                _clamp(correction, -ADAPTIVE_CORRECTION_LIMIT, ADAPTIVE_CORRECTION_LIMIT),
                3,
            ),
            updates=updates,
        )

    def as_dict(self) -> dict[str, float | int]:
        return {"correction": self.correction, "updates": self.updates}


@dataclass(frozen=True, slots=True)
class AdaptiveSample:
    """Minimal delayed-response sample; no indoor history is persisted."""

    timestamp: datetime
    effective_ambient: float
    indoor_target: float

    @classmethod
    def from_dict(cls, stored: Any) -> AdaptiveSample | None:
        if not isinstance(stored, dict):
            return None
        timestamp = _parse_timestamp(stored.get("timestamp"))
        ambient = _finite_number(stored.get("effective_ambient"))
        indoor_target = _finite_number(stored.get("indoor_target"))
        if timestamp is None or ambient is None or indoor_target is None:
            return None
        return cls(timestamp, ambient, indoor_target)

    def as_dict(self) -> dict[str, str | float]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "effective_ambient": round(self.effective_ambient, 2),
            "indoor_target": round(self.indoor_target, 2),
        }


@dataclass(frozen=True, slots=True)
class AdaptiveEstimate:
    """Current learned correction and confidence."""

    correction: float
    confidence: int
    phase: AdaptiveLearningPhase


@dataclass(slots=True)
class AdaptiveLearningModel:
    """Passively learn a bounded correction to the existing heat curve."""

    buckets: dict[str, AdaptiveBucket] = field(default_factory=dict)
    samples: list[AdaptiveSample] = field(default_factory=list)
    total_samples: int = 0
    learning_updates: int = 0
    last_sample_time: datetime | None = None
    last_update_time: datetime | None = None
    last_room_error: float | None = None
    last_adjustment: float | None = None

    @classmethod
    def from_dict(cls, stored: dict[str, Any] | None) -> AdaptiveLearningModel:
        """Load and sanitize persistent learning state."""
        if not isinstance(stored, dict):
            return cls()

        buckets: dict[str, AdaptiveBucket] = {}
        raw_buckets = stored.get("buckets")
        if isinstance(raw_buckets, dict):
            for key, value in raw_buckets.items():
                try:
                    center = float(key)
                except (TypeError, ValueError):
                    continue
                bucket = AdaptiveBucket.from_dict(value)
                if isfinite(center) and bucket is not None:
                    buckets[_bucket_key(center)] = bucket

        samples: list[AdaptiveSample] = []
        raw_samples = stored.get("samples")
        if isinstance(raw_samples, list):
            samples = [
                sample
                for value in raw_samples[-ADAPTIVE_MAX_STORED_SAMPLES:]
                if (sample := AdaptiveSample.from_dict(value)) is not None
            ]
            samples.sort(key=lambda sample: sample.timestamp)

        total_samples = stored.get("total_samples", len(samples))
        learning_updates = stored.get("learning_updates", sum(bucket.updates for bucket in buckets.values()))
        if isinstance(total_samples, bool) or not isinstance(total_samples, int) or total_samples < len(samples):
            total_samples = len(samples)
        if isinstance(learning_updates, bool) or not isinstance(learning_updates, int) or learning_updates < 0:
            learning_updates = sum(bucket.updates for bucket in buckets.values())

        return cls(
            buckets=buckets,
            samples=samples,
            total_samples=total_samples,
            learning_updates=learning_updates,
            last_sample_time=_parse_timestamp(stored.get("last_sample_time")),
            last_update_time=_parse_timestamp(stored.get("last_update_time")),
            last_room_error=_finite_number(stored.get("last_room_error")),
            last_adjustment=_finite_number(stored.get("last_adjustment")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-serializable learning state."""
        return {
            "buckets": {key: bucket.as_dict() for key, bucket in sorted(self.buckets.items())},
            "samples": [sample.as_dict() for sample in self.samples[-ADAPTIVE_MAX_STORED_SAMPLES:]],
            "total_samples": self.total_samples,
            "learning_updates": self.learning_updates,
            "last_sample_time": self.last_sample_time.isoformat() if self.last_sample_time else None,
            "last_update_time": self.last_update_time.isoformat() if self.last_update_time else None,
            "last_room_error": self.last_room_error,
            "last_adjustment": self.last_adjustment,
        }

    def estimate(self, ambient_temperature: float) -> AdaptiveEstimate:
        """Return a smoothly weighted estimate from nearby learned buckets."""
        ambient = _finite_number(ambient_temperature)
        if ambient is None:
            return AdaptiveEstimate(0.0, 0, "observing")

        weighted_correction = 0.0
        weighted_updates = 0.0
        total_weight = 0.0
        for key, bucket in self.buckets.items():
            center = float(key)
            distance = abs(center - ambient)
            weight = max(0.0, 1.0 - distance / (ADAPTIVE_BUCKET_WIDTH * 2))
            if weight == 0:
                continue
            weighted_correction += bucket.correction * weight
            weighted_updates += bucket.updates * weight
            total_weight += weight
        if total_weight == 0:
            return AdaptiveEstimate(0.0, 0, "observing")

        correction = _clamp(
            weighted_correction / total_weight,
            -ADAPTIVE_CORRECTION_LIMIT,
            ADAPTIVE_CORRECTION_LIMIT,
        )
        confidence = round(min(1.0, (weighted_updates / total_weight) / ADAPTIVE_FULL_CONFIDENCE_UPDATES) * 100)
        phase: AdaptiveLearningPhase = "active" if confidence >= 100 else "blending"
        return AdaptiveEstimate(round(correction, 2), confidence, phase)

    def observe(
        self,
        *,
        now: datetime,
        effective_ambient: float,
        indoor_temperature: float,
        indoor_target: float,
        response_hours: int,
    ) -> bool:
        """Record one passive observation and perform at most one hourly update."""
        if now.tzinfo is None:
            raise ValueError("Adaptive-learning timestamps must be timezone-aware")
        ambient = _finite_number(effective_ambient)
        indoor = _finite_number(indoor_temperature)
        target = _finite_number(indoor_target)
        if ambient is None or indoor is None or target is None or response_hours < 1:
            return False

        changed = self._prune_samples(now)
        reference_time = now - timedelta(hours=response_hours)
        reference = min(
            self.samples,
            key=lambda sample: abs((sample.timestamp - reference_time).total_seconds()),
            default=None,
        )
        update_due = self.last_update_time is None or now - self.last_update_time >= ADAPTIVE_UPDATE_INTERVAL
        if (
            update_due
            and reference is not None
            and reference.timestamp <= reference_time
            and abs(reference.timestamp - reference_time) <= ADAPTIVE_SAMPLE_TOLERANCE
            and self._has_continuous_history(reference.timestamp, now, target)
        ):
            room_error = target - indoor
            adjustment = 0.0
            if abs(room_error) > ADAPTIVE_ERROR_DEADBAND:
                adjustment = _clamp(
                    room_error * ADAPTIVE_LEARNING_RATE,
                    -ADAPTIVE_MAX_UPDATE_STEP,
                    ADAPTIVE_MAX_UPDATE_STEP,
                )
            key = _bucket_key(_bucket_center(reference.effective_ambient))
            previous = self.buckets.get(key, AdaptiveBucket())
            self.buckets[key] = AdaptiveBucket(
                correction=round(
                    _clamp(
                        previous.correction + adjustment,
                        -ADAPTIVE_CORRECTION_LIMIT,
                        ADAPTIVE_CORRECTION_LIMIT,
                    ),
                    3,
                ),
                updates=previous.updates + 1,
            )
            self.learning_updates += 1
            self.last_update_time = now
            self.last_room_error = round(room_error, 2)
            self.last_adjustment = round(adjustment, 3)
            changed = True

        if self.last_sample_time is None or now - self.last_sample_time >= ADAPTIVE_SAMPLE_INTERVAL:
            self.samples.append(AdaptiveSample(now, ambient, target))
            self.samples = self.samples[-ADAPTIVE_MAX_STORED_SAMPLES:]
            self.total_samples += 1
            self.last_sample_time = now
            changed = True
        return changed

    def _prune_samples(self, now: datetime) -> bool:
        cutoff = now - ADAPTIVE_HISTORY_RETENTION
        retained = [sample for sample in self.samples if cutoff <= sample.timestamp <= now]
        if len(retained) == len(self.samples):
            return False
        self.samples = retained
        return True

    def _has_continuous_history(
        self,
        start: datetime,
        end: datetime,
        indoor_target: float,
    ) -> bool:
        """Require uninterrupted valid observations and a stable room target."""
        window = [sample for sample in self.samples if start <= sample.timestamp <= end]
        if not window or any(abs(sample.indoor_target - indoor_target) > ADAPTIVE_ERROR_DEADBAND for sample in window):
            return False
        timestamps = [sample.timestamp for sample in window]
        timestamps.append(end)
        return all(right - left <= ADAPTIVE_CONTINUITY_MAX_GAP for left, right in pairwise(timestamps))

    def diagnostics(self) -> dict[str, Any]:
        """Return learning metadata without exposing an indoor-temperature history."""
        return {
            "bucket_count": len(self.buckets),
            "buckets": {key: bucket.as_dict() for key, bucket in sorted(self.buckets.items())},
            "retained_sample_count": len(self.samples),
            "total_samples": self.total_samples,
            "learning_updates": self.learning_updates,
            "last_sample_time": self.last_sample_time,
            "last_update_time": self.last_update_time,
            "last_room_error": self.last_room_error,
            "last_adjustment": self.last_adjustment,
        }
