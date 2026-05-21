"""Config-driven mapper: translates normalized EEG data into synth set_param() calls."""

import math
from typing import Any, Callable, Dict, List, Optional


# --- Curve functions ---

def curve_linear(t: float) -> float:
    return t

def curve_exponential(t: float) -> float:
    return t ** 2.0

def curve_logarithmic(t: float) -> float:
    return math.log1p(t * (math.e - 1))

def curve_scurve(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)

CURVES: Dict[str, Callable[[float], float]] = {
    "linear": curve_linear,
    "exponential": curve_exponential,
    "logarithmic": curve_logarithmic,
    "scurve": curve_scurve,
}


class ParamMapping:
    """A single data-source → synth-param mapping rule."""

    def __init__(
        self,
        source_key: str,
        target_param: str,
        range_min: float,
        range_max: float,
        curve: str = "linear",
        invert: bool = False,
    ):
        self.source_key = source_key
        self.target_param = target_param
        self.range_min = range_min
        self.range_max = range_max
        self.curve_fn = CURVES.get(curve, curve_linear)
        self.invert = invert

    def apply(self, normalized_value: float) -> float:
        """Map a 0-1 normalized input to the output range using the curve."""
        t = max(0.0, min(1.0, normalized_value))
        if self.invert:
            t = 1.0 - t
        t = self.curve_fn(t)
        return self.range_min + t * (self.range_max - self.range_min)

    def __repr__(self) -> str:
        return f"ParamMapping({self.source_key!r} → {self.target_param!r})"


class EventMapping:
    """Fires a synth trigger when a value crosses a threshold."""

    def __init__(
        self,
        source_key: str,
        trigger_target: str,
        threshold: float = 1.5,
        direction: str = "above",  # "above" or "below"
        cooldown_seconds: float = 1.0,
    ):
        self.source_key = source_key
        self.trigger_target = trigger_target
        self.threshold = threshold
        self.direction = direction
        self.cooldown = cooldown_seconds
        self._last_trigger: float = 0.0
        self._was_triggered: bool = False

    def check(self, value: float, now: float) -> bool:
        """Returns True if event should fire."""
        import time
        if now - self._last_trigger < self.cooldown:
            return False
        triggered = value > self.threshold if self.direction == "above" else value < self.threshold
        if triggered and not self._was_triggered:
            self._was_triggered = True
            self._last_trigger = now
            return True
        if not triggered:
            self._was_triggered = False
        return False


class MappingEngine:
    """Loads mapping rules from a config dict and applies them to incoming data.

    Typical usage:
        engine = MappingEngine.from_config(config["mapping"])
        # Each data tick:
        calls = engine.process(normalized_data, now=time.monotonic())
        for path, value in calls:
            synth.set_param(path, value)
        for trigger in engine.get_pending_triggers():
            synth.trigger(trigger)
    """

    def __init__(self, param_mappings: List[ParamMapping], event_mappings: List[EventMapping]):
        self.param_mappings = param_mappings
        self.event_mappings = event_mappings
        self._pending_triggers: List[str] = []

    @classmethod
    def from_config(cls, mapping_config: Dict[str, Any]) -> "MappingEngine":
        """Build from the 'mapping' section of a YAML config dict."""
        params = []
        events = []

        # Study mode: structured per-stream mapping
        for stream_name, stream_map in mapping_config.items():
            if stream_name == "events":
                for event_name, event_cfg in stream_map.items():
                    events.append(EventMapping(
                        source_key=event_cfg.get("source", event_name),
                        trigger_target=event_cfg["trigger"],
                        threshold=event_cfg.get("threshold", 1.5),
                        direction=event_cfg.get("direction", "above"),
                        cooldown_seconds=event_cfg.get("cooldown", 1.0),
                    ))
            else:
                for source_key, rule in stream_map.items():
                    if isinstance(rule, dict) and "target" in rule:
                        rng = rule.get("range", [0.0, 1.0])
                        params.append(ParamMapping(
                            source_key=source_key,
                            target_param=rule["target"],
                            range_min=rng[0],
                            range_max=rng[1],
                            curve=rule.get("curve", "linear"),
                            invert=rule.get("invert", False),
                        ))

        return cls(params, events)

    def process(
        self, data: Dict[str, float], now: float
    ) -> List[tuple]:
        """Returns list of (param_path, value) tuples to pass to synth.set_param()."""
        self._pending_triggers.clear()
        results = []

        for mapping in self.param_mappings:
            value = data.get(mapping.source_key)
            if value is not None:
                results.append((mapping.target_param, mapping.apply(value)))

        for event in self.event_mappings:
            value = data.get(event.source_key)
            if value is not None and event.check(value, now):
                self._pending_triggers.append(event.trigger_target)

        return results

    def get_pending_triggers(self) -> List[str]:
        return list(self._pending_triggers)
