"""
plantsim.py - PlantGuard: simulated industrial plant + monitoring engine.

Pure Python, no UI code. The dashboard (plant_app.py) and the preview builder both
call this module, so what you see is exactly what the engine computes.

THE IDEA IN FIVE STEPS (each tick = one reading of every sensor, TICK_SECONDS apart)
  1. SIMULATE   every machine has sensors (temperature, vibration, pressure ...). A "fault"
                (overheating, bearing wear ...) pushes the matching sensors towards danger.
  2. SCORE      each sensor value -> risk 0-100 against its warn/critical limits. A machine's
                risk combines its sensors, plus a bonus when a reading is rising fast
                (the engine estimates "seconds to critical").
  3. DECIDE     plant risk % = worst machine (weighted by how much damage it could cause)
                blended with the average. The plant is in one of five MODES:
                NORMAL < WARNING < CRITICAL < FAILURE < EVACUATE (life risk).
  4. ALERT      when a machine or the plant escalates, the right people are notified
                (in-charge + maintenance -> everyone in the zone -> ALL employees).
  5. ADVISE     the engine suggests concrete actions; the operator can apply them and
                watch the readings recover.

IMPORTANT: this is a prototype with SIMULATED sensors. A real plant needs certified
safety systems (SIS / SIL-rated), not just a dashboard.
"""
from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass

TICK_SECONDS = 2        # plant time represented by one simulation step (display only)
HISTORY = 40            # ticks of history kept for sparklines

MODES = ["NORMAL", "WARNING", "CRITICAL", "FAILURE", "EVACUATE"]
MODE_RANK = {m: i for i, m in enumerate(MODES)}
MODE_LABEL = {
    "NORMAL": "Normal operation",
    "WARNING": "Warning",
    "CRITICAL": "Critical: failure risk",
    "FAILURE": "Plant failure",
    "EVACUATE": "Life risk: evacuate",
}
MODE_RISK_FLOOR = {"NORMAL": 0, "WARNING": 25, "CRITICAL": 55, "FAILURE": 72, "EVACUATE": 92}

# --------------------------------------------------------------------------- #
# Plant layout (used for the floor-plan drawing and employee positions)
# --------------------------------------------------------------------------- #
ZONES = {
    "A": ("Utilities", (10, 10, 190, 130)),
    "B": ("Power hall", (210, 10, 190, 130)),
    "C": ("Logistics", (410, 10, 220, 130)),
    "D": ("Press shop", (10, 150, 190, 140)),
    "E": ("Process bay", (210, 150, 190, 140)),
    "CR": ("Control room", (410, 150, 120, 140)),
}
MUSTER_RECT = (540, 150, 90, 140)
MUSTER_NAME = "Muster Point"


# --------------------------------------------------------------------------- #
# Sensors and machines
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SensorSpec:
    key: str
    label: str
    unit: str
    role: str            # temp | vib | pressure | current | structure | flow | level | gas | belt
    nominal: float
    warn: float
    crit: float
    low_bad: bool = False   # True when LOW readings are the dangerous ones (flow, level, integrity)
    noise: float = 0.01
    decimals: int = 0


@dataclass(frozen=True)
class MachineSpec:
    id: str
    name: str
    kind: str            # vessel | rotating | conveyor | press | tower
    zone: str
    consequence: float   # 0..1: how bad it is if this machine fails (weights the plant risk)
    sensors: tuple
    pos: tuple           # (x, y) on the floor plan


S = SensorSpec
SPECS = [
    MachineSpec("B-1", "Boiler", "vessel", "A", 0.90, (
        S("temp", "Shell temp", "°C", "temp", 180, 215, 240, noise=1.2),
        S("pressure", "Steam pressure", "bar", "pressure", 10, 12.5, 14, noise=0.08, decimals=1),
        S("level", "Water level", "%", "level", 62, 42, 30, low_bad=True, noise=0.6),
        S("structure", "Wall integrity", "%", "structure", 100, 90, 78, low_bad=True, noise=0.15, decimals=1),
    ), (28, 48)),
    MachineSpec("C-1", "Compressor", "rotating", "A", 0.60, (
        S("temp", "Discharge temp", "°C", "temp", 85, 105, 120, noise=0.8),
        S("vib", "Vibration", "mm/s", "vib", 2.0, 4.5, 7.1, noise=0.08, decimals=1),
        S("current", "Motor current", "A", "current", 42, 52, 60, noise=0.5),
        S("structure", "Bearing health", "%", "structure", 100, 86, 72, low_bad=True, noise=0.2, decimals=1),
    ), (112, 86)),
    MachineSpec("G-1", "Turbine-Generator", "rotating", "B", 0.85, (
        S("temp", "Bearing temp", "°C", "temp", 70, 90, 105, noise=0.7),
        S("vib", "Vibration", "mm/s", "vib", 1.8, 4.0, 6.5, noise=0.07, decimals=1),
        S("current", "Load current", "A", "current", 310, 380, 430, noise=3),
        S("structure", "Rotor integrity", "%", "structure", 100, 88, 72, low_bad=True, noise=0.15, decimals=1),
    ), (230, 48)),
    MachineSpec("P-1", "Cooling Pump", "rotating", "B", 0.50, (
        S("temp", "Seal temp", "°C", "temp", 55, 72, 85, noise=0.6),
        S("vib", "Vibration", "mm/s", "vib", 1.5, 3.8, 6.0, noise=0.06, decimals=1),
        S("flow", "Flow", "m³/h", "flow", 120, 92, 72, low_bad=True, noise=1.2),
        S("current", "Motor current", "A", "current", 28, 36, 42, noise=0.4),
    ), (316, 86)),
    MachineSpec("CV-1", "Conveyor", "conveyor", "C", 0.35, (
        S("temp", "Motor temp", "°C", "temp", 60, 80, 95, noise=0.6),
        S("current", "Motor current", "A", "current", 18, 26, 32, noise=0.3),
        S("belt", "Belt offset", "mm", "belt", 2, 8, 15, noise=0.15, decimals=1),
        S("structure", "Roller health", "%", "structure", 100, 86, 70, low_bad=True, noise=0.2, decimals=1),
    ), (430, 48)),
    MachineSpec("T-1", "Cooling Tower", "tower", "C", 0.30, (
        S("temp", "Basin temp", "°C", "temp", 32, 40, 46, noise=0.3),
        S("vib", "Fan vibration", "mm/s", "vib", 1.2, 3.5, 5.8, noise=0.05, decimals=1),
        S("flow", "Water flow", "m³/h", "flow", 300, 240, 190, low_bad=True, noise=3),
        S("structure", "Gearbox health", "%", "structure", 100, 87, 72, low_bad=True, noise=0.2, decimals=1),
    ), (535, 86)),
    MachineSpec("H-1", "Hydraulic Press", "press", "D", 0.60, (
        S("pressure", "Hydraulic press.", "bar", "pressure", 200, 235, 255, noise=1.2),
        S("temp", "Oil temp", "°C", "temp", 50, 70, 85, noise=0.5),
        S("vib", "Vibration", "mm/s", "vib", 2.2, 4.8, 7.5, noise=0.08, decimals=1),
        S("structure", "Frame integrity", "%", "structure", 100, 88, 74, low_bad=True, noise=0.15, decimals=1),
    ), (50, 190)),
    MachineSpec("R-1", "Chemical Reactor", "vessel", "E", 1.00, (
        S("temp", "Core temp", "°C", "temp", 120, 150, 170, noise=0.9),
        S("pressure", "Pressure", "bar", "pressure", 6, 8, 9.5, noise=0.05, decimals=1),
        S("gas", "Toxic gas", "ppm", "gas", 0.5, 10, 25, noise=0.15, decimals=1),
        S("structure", "Vessel wall", "%", "structure", 100, 90, 78, low_bad=True, noise=0.15, decimals=1),
    ), (250, 190)),
]
SPEC_BY_ID = {m.id: m for m in SPECS}


# --------------------------------------------------------------------------- #
# Faults: which sensor roles each fault pushes, and how hard (1.0 = strongest)
# At fault intensity i, a sensor moves  gain * i * 1.35 * (crit - nominal)  from nominal.
# "primary" = the sensor roles a machine needs for the fault to make sense (no gas leak on a pump).
# --------------------------------------------------------------------------- #
FAULTS = {
    "overheat": {"label": "Overheating", "primary": ("temp",),
                 "gains": {"temp": 1.0, "current": 0.35, "vib": 0.2, "pressure": 0.45}},
    "bearing_wear": {"label": "Bearing wear / vibration", "primary": ("vib",),
                     "gains": {"vib": 1.0, "temp": 0.55, "structure": 0.55, "current": 0.2}},
    "overpressure": {"label": "Overpressure", "primary": ("pressure",),
                     "gains": {"pressure": 1.0, "temp": 0.35, "structure": 0.2}},
    "coolant_loss": {"label": "Coolant / flow loss", "primary": ("flow", "level"),
                     "gains": {"flow": 1.0, "temp": 0.75, "level": 0.8, "pressure": 0.2}},
    "structural_crack": {"label": "Structural crack", "primary": ("structure",),
                         "gains": {"structure": 1.0, "vib": 0.5, "pressure": 0.15}},
    "gas_leak": {"label": "Toxic gas leak", "primary": ("gas",),
                 "gains": {"gas": 1.0, "structure": 0.3}},
    "overload": {"label": "Overload / jam", "primary": ("current",),
                 "gains": {"current": 1.0, "temp": 0.6, "vib": 0.35, "belt": 0.85}},
}
FAULT_RATES = {"slow": 0.025, "normal": 0.05, "fast": 0.09}   # intensity added per tick

ACTION_LABELS = {
    "reduce_load": "Reduce load",
    "boost_cooling": "Boost cooling",
    "isolate_vent": "Isolate & vent",
    "dispatch_crew": "Send maintenance crew",
    "emergency_stop": "Emergency stop",
    "restart": "Restart machine",
}
# How strongly each action fights each fault, as a multiple of the fault's growth rate.
# 1.0 = holds it steady, above 1.0 = the fault shrinks.
RELIEF = {
    "reduce_load": {"overheat": 0.7, "bearing_wear": 0.5, "overpressure": 0.4, "coolant_loss": 0.4,
                    "structural_crack": 0.5, "gas_leak": 0.0, "overload": 1.6},
    "boost_cooling": {"overheat": 1.7, "coolant_loss": 1.3, "bearing_wear": 0.3, "overpressure": 0.2,
                      "structural_crack": 0.0, "gas_leak": 0.0, "overload": 0.3},
    "isolate_vent": {"overpressure": 2.0, "gas_leak": 2.2, "structural_crack": 0.4, "overheat": 0.0,
                     "bearing_wear": 0.0, "coolant_loss": 0.0, "overload": 0.0},
}
CREW_ARRIVAL_TICKS = 6

# --------------------------------------------------------------------------- #
# People
# --------------------------------------------------------------------------- #
# id, name, role, zone, home (x, y), ticks they take to react to an alert
ROSTER = [
    ("E01", "Meera Nair", "Plant In-Charge", "CR", (440, 200), 2),
    ("E02", "Arjun Rao", "Safety Officer", "CR", (480, 245), 1),
    ("E03", "Kavya Iyer", "Shift Supervisor", "A", (45, 118), 3),
    ("E04", "Rahul Menon", "Shift Supervisor", "C", (430, 120), 2),
    ("E05", "Sana Khan", "Shift Supervisor", "E", (230, 270), 4),
    ("E06", "Dev Patel", "Maintenance Engineer", "B", (360, 40), 3),
    ("E07", "Lena Fischer", "Maintenance Engineer", "D", (30, 260), 2),
    ("E08", "Imran Sheikh", "Operator", "A", (150, 50), 1),
    ("E09", "Priya Das", "Operator", "A", (185, 120), 5),
    ("E10", "Tomas Reyes", "Operator", "B", (250, 115), 3),
    ("E11", "Anita Joseph", "Operator", "C", (520, 40), 2),
    ("E12", "Vikram Singh", "Operator", "D", (170, 180), 4),
    ("E13", "Hana Kim", "Operator", "E", (350, 190), 3),
    ("E14", "Ola Adeyemi", "Operator", "E", (360, 260), 5),
]
SAMPLE_PHONE_EMPLOYEE = "E11"     # whose phone the dashboard shows by default

CHANNELS = {
    "WARNING": ["App push"],
    "CRITICAL": ["App push", "SMS", "PA announcement"],
    "FAILURE": ["App push", "SMS", "PA announcement", "Beacon light"],
    "EVACUATE": ["App push", "SMS", "PA siren", "Beacon light", "Auto-call"],
    "INFO": ["App push"],
    "CLEAR": ["App push", "SMS", "PA announcement"],
}


class Notifier:
    """Delivers alerts. In this prototype it only records them.

    To make alerts real, subclass it and send via SMS (Twilio), Telegram, e-mail or a
    PA/siren controller inside `send()`. Nothing else in the engine needs to change.
    """

    def __init__(self):
        self.sent = []

    def send(self, alert: dict) -> None:
        self.sent.append(alert)


# --------------------------------------------------------------------------- #
# Scenarios: scripted stories used by the preview and the "Run scenario" button
# event = (tick, kind, machine_id, thing, extra)
# --------------------------------------------------------------------------- #
SCENARIOS = {
    "normal": {
        "title": "Normal day",
        "desc": "All machines healthy. Baseline monitoring with no alerts.",
        "ticks": 24,
        "events": [],
    },
    "overheat": {
        "title": "Overheating caught early",
        "desc": "The compressor starts overheating. Warnings go out, the operator reduces load and boosts cooling, and it recovers.",
        "ticks": 32,
        "events": [
            (5, "inject", "C-1", "overheat", "normal"),
            (15, "act", "C-1", "boost_cooling", None),
            (16, "act", "C-1", "reduce_load", None),
        ],
    },
    "bearing": {
        "title": "Bearing failure, left unchecked",
        "desc": "The turbine bearing wears out and nobody acts in time. Warning, then critical, then the machine trips: plant failure.",
        "ticks": 46,
        "events": [
            (4, "inject", "G-1", "bearing_wear", "fast"),
            (36, "act", "G-1", "dispatch_crew", None),
        ],
    },
    "gas": {
        "title": "Toxic gas leak: evacuation",
        "desc": "The reactor starts leaking toxic gas. Everyone is told to evacuate. The leak is isolated and the all-clear follows.",
        "ticks": 42,
        "events": [
            (5, "inject", "R-1", "gas_leak", "fast"),
            (22, "act", "R-1", "isolate_vent", None),
        ],
    },
}

# --------------------------------------------------------------------------- #
# Advice: what to do, from what the sensors show (the system doesn't "know" the fault)
# role -> (text when WARNING, action), (text when CRITICAL, action)
# --------------------------------------------------------------------------- #
ADVICE = {
    "temp": (("Reduce load on {m} to about 70% and check cooling and airflow.", "reduce_load"),
             ("Boost cooling on {m} and prepare a controlled shutdown. Keep people 5 m away.", "boost_cooling")),
    "vib": (("Inspect bearings, alignment and mounts on {m}. Lubricate and schedule maintenance.", "dispatch_crew"),
            ("Shut {m} down (damaging vibration) and lock it out for inspection.", "emergency_stop")),
    "pressure": (("Reduce feed or load on {m} and check the relief valve.", "reduce_load"),
                 ("Open the relief or vent per SOP and isolate {m}. Never exceed set pressure.", "isolate_vent")),
    "current": (("Check {m} for a jam or overload and reduce load.", "reduce_load"),
                ("Stop {m} and inspect for a jam or short before any restart.", "emergency_stop")),
    "structure": (("Restrict access near {m}, reduce load and book an ultrasonic inspection.", "reduce_load"),
                  ("Stop {m}, isolate it and clear the immediate area: structural damage suspected.", "emergency_stop")),
    "flow": (("Check pumps, valves and strainers for blockage and restore flow to {m}.", "dispatch_crew"),
             ("Boost cooling for {m} and stop it if flow cannot be restored.", "boost_cooling")),
    "level": (("Check the feed-water supply to {m}.", "dispatch_crew"),
              ("Stop firing {m}: low water causes overheating and rupture.", "emergency_stop")),
    "gas": (("Increase ventilation and check seals and flanges around {m}.", "isolate_vent"),
            ("Isolate the feed and vent {m}. Only a trained team with breathing apparatus goes near.", "isolate_vent")),
    "belt": (("Re-align the belt and idlers on {m}.", "dispatch_crew"),
             ("Stop {m}: a misaligned belt can jam or catch fire.", "emergency_stop")),
}

_IDLE_FACTOR = {"temp": 0.45, "vib": 0.05, "current": 0.03, "pressure": 0.25, "flow": 0.0}


# --------------------------------------------------------------------------- #
# Scoring helpers
# --------------------------------------------------------------------------- #
def _distances(spec: SensorSpec, v: float):
    """(how far the reading is into danger, warn distance, crit distance), direction-aware."""
    if spec.low_bad:
        return spec.nominal - v, spec.nominal - spec.warn, spec.nominal - spec.crit
    return v - spec.nominal, spec.warn - spec.nominal, spec.crit - spec.nominal


def sensor_risk(spec: SensorSpec, v: float) -> float:
    """0 at nominal, 35 at the warn limit, 75 at the critical limit, 100 well beyond."""
    d, w, c = _distances(spec, v)
    if d <= 0:
        return 0.0
    if d < w:
        return 35.0 * d / w
    if d < c:
        return 35.0 + 40.0 * (d - w) / (c - w)
    return min(100.0, 75.0 + 25.0 * (d - c) / (c - w))


def sensor_status(spec: SensorSpec, v: float) -> str:
    d, w, c = _distances(spec, v)
    return "crit" if d >= c else "warn" if d >= w else "ok"


def eta_seconds(spec: SensorSpec, hist) -> int | None:
    """Straight-line forecast: seconds until the critical limit, or None if not heading there."""
    n = len(hist)
    if n < 5:
        return None
    xs = range(n)
    mx, my = (n - 1) / 2, sum(hist) / n
    den = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, hist)) / den
    worsening = -slope if spec.low_bad else slope
    span = abs(spec.crit - spec.nominal)
    if worsening < span * 0.012:
        return None
    v = hist[-1]
    remaining = (v - spec.crit) if spec.low_bad else (spec.crit - v)
    if remaining <= 0:
        return None
    ticks = remaining / worsening
    return int(ticks * TICK_SECONDS) if ticks <= 60 else None


def clock(tick: int) -> str:
    s = tick * TICK_SECONDS
    return f"{s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}"


# --------------------------------------------------------------------------- #
# Runtime state of one machine
# --------------------------------------------------------------------------- #
class Machine:
    def __init__(self, spec: MachineSpec, rng: random.Random):
        self.spec = spec
        self.values = {s.key: float(s.nominal) for s in spec.sensors}
        self.hist = {s.key: deque([float(s.nominal)] * 6, maxlen=6) for s in spec.sensors}
        self.fault = None            # {"kind", "i", "rate"}
        self.actions = set()
        self.stopped = False
        self.failed = False
        self.crew_eta = 0
        self.trip_count = 0
        self.phase = rng.uniform(0, 6.28)
        self.risk = 0.0
        self.risk_hist = deque([0.0] * 12, maxlen=HISTORY)
        self.state = "OK"
        self.sensor_info = []

    # ---- fault dynamics ---------------------------------------------------
    def advance_fault(self, log):
        f = self.fault
        if not f:
            return
        i = f["i"]
        if self.crew_eta > 0:
            self.crew_eta -= 1
            if self.crew_eta == 0:
                self.actions.add("crew_on_site")
                log("INFO", f"{self.spec.id}: maintenance crew on site, repairing {FAULTS[f['kind']]['label'].lower()}.")
        if "crew_on_site" in self.actions:
            i *= 0.55
        elif self.failed:
            pass                                            # frozen until repaired
        elif self.stopped:
            if f["kind"] != "structural_crack":
                i -= 0.10                                   # cools down; cracks do not heal
        else:
            relief = sum(RELIEF[a].get(f["kind"], 0.0) for a in self.actions if a in RELIEF)
            i += f["rate"] * (1.0 - relief)
        f["i"] = max(0.0, min(1.6, i))
        if f["i"] <= 0.03:
            was_failed = self.failed
            self.fault = None
            self.actions.clear()
            self.crew_eta = 0
            if was_failed:
                self.failed = False
                self.stopped = True
                log("INFO", f"{self.spec.id}: repaired. Machine is stopped and ready to restart.")
            elif not self.stopped:
                log("INFO", f"{self.spec.id}: fault cleared, readings returning to normal.")

    # ---- sensors ----------------------------------------------------------
    def _target(self, s: SensorSpec, tick: int, rng: random.Random) -> float:
        offline = self.stopped or self.failed
        if offline:
            if s.role == "structure":
                return self.values[s.key]                   # damage does not disappear
            if s.role in ("level", "gas", "belt"):
                return float(s.nominal)
            return s.nominal * _IDLE_FACTOR.get(s.role, 0.5)
        v = s.nominal + 0.6 * s.noise * math.sin(tick / 7 + self.phase) + rng.gauss(0, s.noise)
        if self.fault:
            gain = FAULTS[self.fault["kind"]]["gains"].get(s.role, 0.0)
            v += gain * self.fault["i"] * 1.35 * (s.crit - s.nominal)
        return max(0.0, v)

    def update_sensors(self, tick: int, rng: random.Random):
        alpha = 0.25 if (self.stopped or self.failed) else 0.6
        for s in self.spec.sensors:
            v = self.values[s.key]
            v += (self._target(s, tick, rng) - v) * alpha
            self.values[s.key] = v
            self.hist[s.key].append(v)

    # ---- evaluation -------------------------------------------------------
    def evaluate(self):
        offline = self.stopped or self.failed
        info, risks, bonus = [], [], 0.0
        for s in self.spec.sensors:
            v = self.values[s.key]
            r = 0.0 if offline else sensor_risk(s, v)
            status = "off" if offline else sensor_status(s, v)
            eta = None if offline else eta_seconds(s, self.hist[s.key])
            if eta is not None and status != "crit":
                bonus = max(bonus, 10.0 * max(0.0, min(1.0, 1 - (eta / TICK_SECONDS) / 15)))
            risks.append(r)
            info.append({"key": s.key, "label": s.label, "unit": s.unit, "role": s.role,
                         "value": v, "text": f"{v:.{s.decimals}f}", "status": status, "risk": r,
                         "eta": eta, "low_bad": s.low_bad,
                         "warn": s.warn, "crit": s.crit, "nominal": s.nominal})
        top = max(risks) if risks else 0.0
        combined = top + 0.3 * (sum(risks) - top) + bonus
        if self.failed:
            self.risk = 100.0
        elif self.stopped:
            self.risk = 0.0
        else:
            self.risk = min(100.0, combined)
        self.sensor_info = info
        if self.failed:
            self.state = "FAILED"
        elif self.stopped:
            self.state = "STOPPED"
        elif any(x["status"] == "crit" for x in info) or self.risk >= 70:
            self.state = "CRIT"
        elif any(x["status"] == "warn" for x in info) or self.risk >= 30:
            self.state = "WARN"
        else:
            self.state = "OK"
        self.risk_hist.append(self.risk)

    def worst_sensor(self):
        live = [x for x in self.sensor_info if x["status"] != "off"]
        return max(live, key=lambda x: x["risk"]) if live else None


# --------------------------------------------------------------------------- #
# The plant
# --------------------------------------------------------------------------- #
_STATE_RANK = {"OK": 0, "STOPPED": 0, "WARN": 1, "CRIT": 2, "FAILED": 3}


class Plant:
    def __init__(self, seed: int = 7, notifier: Notifier | None = None):
        self.seed = seed
        self.notifier = notifier or Notifier()
        self.reset()

    # ---- lifecycle ----------------------------------------------------------
    def reset(self):
        self.rng = random.Random(self.seed)
        self.tick = 0
        self.machines = [Machine(spec, self.rng) for spec in SPECS]
        self.by_id = {m.spec.id: m for m in self.machines}
        self.mode = "NORMAL"
        self._down = 0
        self.alerts = []                       # newest last
        self.log_items = []                    # newest last
        self.risk_hist = deque([2.0] * 12, maxlen=HISTORY)
        self.prev_rank = {m.spec.id: 0 for m in self.machines}
        self.script = []
        self.scenario = None
        self.hazard = None
        self.evac_start = None
        self.progress = {e[0]: 0.0 for e in ROSTER}
        self.notifier.sent.clear()
        for m in self.machines:                # first readings, no alerts
            m.evaluate()
        self._plant_eval()

    def load_scenario(self, name: str):
        sc = SCENARIOS[name]
        self.reset()
        self.scenario = name
        self.script = list(sc["events"])
        self._log("INFO", f"Scenario started: {sc['title']}.")

    # ---- operator / simulation controls ---------------------------------------
    def applicable_faults(self, machine_id: str):
        roles = {s.role for s in SPEC_BY_ID[machine_id].sensors}
        return [k for k, f in FAULTS.items() if any(r in roles for r in f["primary"])]

    def inject(self, machine_id: str, kind: str, speed: str = "normal") -> str:
        m = self.by_id[machine_id]
        if kind not in self.applicable_faults(machine_id):
            return f"{FAULTS[kind]['label']} does not apply to {m.spec.name}."
        if m.failed:
            return f"{machine_id} has already failed."
        m.fault = {"kind": kind, "i": 0.0, "rate": FAULT_RATES.get(speed, FAULT_RATES["normal"])}
        m.actions.clear()
        m.crew_eta = 0
        m.stopped = False
        self._log("SIM", f"[simulation] {FAULTS[kind]['label']} started on {machine_id}.")
        return "ok"

    def act(self, machine_id: str, action: str) -> str:
        m = self.by_id[machine_id]
        name = ACTION_LABELS.get(action, action)
        if action == "restart":
            if not m.stopped or m.failed:
                return f"{machine_id} is not stopped."
            if m.fault and m.fault["i"] > 0.15:
                return f"{machine_id} still has a fault: send a crew before restarting."
            m.stopped = False
            m.actions.discard("emergency_stop")
            self._log("OPERATOR", f"Operator restarted {machine_id}.")
            return "ok"
        if m.failed and action != "dispatch_crew":
            return f"{machine_id} has failed: only a maintenance crew can fix it."
        if action == "emergency_stop":
            m.stopped = True
            m.actions.add("emergency_stop")
        elif action == "dispatch_crew":
            if m.crew_eta == 0 and "crew_on_site" not in m.actions:
                m.crew_eta = CREW_ARRIVAL_TICKS
        elif action in RELIEF:
            m.actions.add(action)
        else:
            return f"Unknown action {action}."
        self._log("OPERATOR", f"Operator: {name} on {machine_id}.")
        return "ok"

    # ---- one step -----------------------------------------------------------
    def step(self) -> dict:
        self.tick += 1
        for ev in [e for e in self.script if e[0] == self.tick]:
            _, kind, mid, thing, extra = ev
            if kind == "inject":
                self.inject(mid, thing, extra or "normal")
            elif kind == "act":
                self.act(mid, thing)
        for m in self.machines:
            m.advance_fault(self._log)
            m.update_sensors(self.tick, self.rng)
            m.evaluate()
            leaking = bool(m.fault) and m.fault["kind"] == "gas_leak"     # a leak is a hazard, not a breakdown
            if m.state not in ("FAILED", "STOPPED") and m.risk >= 97 and not leaking:
                m.trip_count += 1
            else:
                m.trip_count = 0
            if m.trip_count >= 2 and not m.failed:
                m.failed = True
                m.stopped = True
                m.actions.discard("crew_on_site")
                m.evaluate()
        self._plant_eval()
        self._alerts()
        self._move_people()
        return self.snapshot()

    # ---- plant-level evaluation -----------------------------------------------
    def _life_hazard(self):
        for m in self.machines:
            sp = m.spec
            st = {x["role"]: x["status"] for x in m.sensor_info}
            if m.failed and sp.kind == "vessel":
                return m.spec.id, f"Vessel failure at {sp.name} ({sp.id}): rupture and release hazard"
            if st.get("gas") == "crit":
                return sp.id, f"Toxic gas above the safe limit in {ZONES[sp.zone][0]} ({sp.name})"
            if sp.kind == "vessel" and st.get("pressure") == "crit" and "crit" in (st.get("temp"), st.get("structure")):
                return sp.id, f"Possible rupture or explosion at {sp.name} ({sp.id})"
        return None

    def _plant_eval(self):
        weighted = [m.spec.consequence * m.risk / 100 for m in self.machines]
        total_w = sum(m.spec.consequence for m in self.machines)
        raw = 100 * (0.65 * max(weighted) + 0.35 * sum(weighted) / total_w)
        self.hazard = self._life_hazard()
        states = [m.state for m in self.machines]
        if self.hazard:
            raw_mode = "EVACUATE"
        elif "FAILED" in states:
            raw_mode = "FAILURE"
        elif "CRIT" in states or raw >= 55:
            raw_mode = "CRITICAL"
        elif "WARN" in states or raw >= 25:
            raw_mode = "WARNING"
        else:
            raw_mode = "NORMAL"
        self.prev_mode = self.mode
        if MODE_RANK[raw_mode] > MODE_RANK[self.mode]:          # escalate at once
            self.mode, self._down = raw_mode, 0
        elif MODE_RANK[raw_mode] < MODE_RANK[self.mode]:        # de-escalate only after 3 calm ticks
            self._down += 1
            if self._down >= 3:
                self.mode, self._down = raw_mode, 0
        else:
            self._down = 0
        self.risk = int(round(min(99, max(2, raw, MODE_RISK_FLOOR[self.mode]))))
        self.risk_hist.append(self.risk)

    # ---- alerts ------------------------------------------------------------------
    def _log(self, level: str, text: str):
        self.log_items.append({"tick": self.tick, "clock": clock(self.tick), "level": level, "text": text})
        del self.log_items[:-60]

    def _group(self, kind: str, zone: str | None = None):
        ids = []
        for eid, _, role, z, _, _ in ROSTER:
            if kind == "all":
                ok = True
            elif kind == "management":
                ok = role in ("Plant In-Charge", "Maintenance Engineer", "Shift Supervisor")
            elif kind == "zone":
                ok = z == zone or role in ("Plant In-Charge", "Maintenance Engineer", "Safety Officer")
            else:
                ok = False
            if ok:
                ids.append(eid)
        return ids

    def _raise(self, level, title, body, recipients, group, machine=None):
        alert = {"id": len(self.alerts) + 1, "tick": self.tick, "clock": clock(self.tick), "level": level,
                 "title": title, "body": body, "recipients": recipients, "group": group,
                 "channels": CHANNELS[level], "machine": machine}
        self.alerts.append(alert)
        self.notifier.send(alert)
        self._log(level, f"{title}. Sent to {group} ({len(recipients)}).")

    def _alerts(self):
        evac_now = self.mode == "EVACUATE" and self.prev_mode != "EVACUATE"
        for m in self.machines:
            rank = _STATE_RANK[m.state]
            prev = self.prev_rank[m.spec.id]
            self.prev_rank[m.spec.id] = rank
            sp = m.spec
            if rank > prev and not (evac_now and self.hazard and self.hazard[0] == sp.id):
                w = m.worst_sensor()
                if m.state == "WARN" and w:
                    eta = f" About {w['eta']} s to critical at this rate." if w["eta"] else ""
                    self._raise("WARNING", f"{sp.name} ({sp.id}): {w['label'].lower()} abnormal",
                                f"{w['label']} is {w['text']} {w['unit']} (limit {w['warn']:g}).{eta}",
                                self._group("management"), "in-charge, maintenance and supervisors", sp.id)
                elif m.state == "CRIT" and w:
                    eta = f" Failure possible in about {w['eta']} s." if w["eta"] else ""
                    self._raise("CRITICAL", f"CRITICAL: {sp.name} ({sp.id})",
                                f"{w['label']} {w['text']} {w['unit']} is beyond the safe limit.{eta} "
                                f"Everyone in {ZONES[sp.zone][0]} stay clear.",
                                self._group("zone", sp.zone), f"{ZONES[sp.zone][0]} + maintenance + safety", sp.id)
                elif m.state == "FAILED":
                    self._raise("FAILURE", f"FAILURE: {sp.name} ({sp.id}) has tripped",
                                f"{sp.name} stopped. {ZONES[sp.zone][0]} is restricted; lock-out in progress.",
                                self._group("all"), "all employees", sp.id)
            elif rank < prev and m.state == "OK":
                self._log("INFO", f"{sp.id} is back to normal.")
        if evac_now:
            self.evac_start = self.tick
            self._raise("EVACUATE", "EVACUATE NOW",
                        f"{self.hazard[1]}. Leave immediately and go to the {MUSTER_NAME}. Do not use lifts.",
                        self._group("all"), "ALL employees", self.hazard[0])
        if self.mode != "EVACUATE" and self.prev_mode == "EVACUATE":
            self.evac_start = None
            self._raise("INFO", "Hazard cleared",
                        f"The life-risk condition has ended. Stay at the {MUSTER_NAME} until the Safety Officer confirms.",
                        self._group("all"), "ALL employees")
        if self.mode == "NORMAL" and MODE_RANK[self.prev_mode] >= MODE_RANK["WARNING"] and self.prev_mode != "EVACUATE":
            level_all = MODE_RANK[self.prev_mode] >= MODE_RANK["CRITICAL"]
            self._raise("CLEAR", "All clear: plant back to normal",
                        "All readings are back within safe limits. Resume normal work.",
                        self._group("all" if level_all else "management"),
                        "all employees" if level_all else "in-charge, maintenance and supervisors")

    def _acked(self, alert) -> int:
        delays = {e[0]: e[5] for e in ROSTER}
        return sum(1 for r in alert["recipients"] if self.tick >= alert["tick"] + delays[r])

    def _move_people(self):
        for eid, _, _, _, _, delay in ROSTER:
            target = 1.0 if (self.mode == "EVACUATE" and self.evac_start is not None
                             and self.tick >= self.evac_start + delay) else 0.0
            p = self.progress[eid]
            step = 0.2
            self.progress[eid] = min(target, p + step) if target > p else max(target, p - step)

    # ---- advice --------------------------------------------------------------------
    def advice(self) -> list:
        out = []
        for m in sorted(self.machines, key=lambda x: -x.risk):
            sp = m.spec
            if m.state == "FAILED":
                done = m.crew_eta > 0 or "crew_on_site" in m.actions
                out.append({"prio": 3 if done else 1, "machine": sp.id, "action": None if done else "dispatch_crew",
                            "text": (f"Crew is repairing {sp.id}. Keep {ZONES[sp.zone][0]} restricted until it is signed off."
                                     if done else
                                     f"Lock out and tag out {sp.name} ({sp.id}), keep {ZONES[sp.zone][0]} restricted and send a crew.")})
            elif m.state == "STOPPED" and m.fault and not m.crew_eta and "crew_on_site" not in m.actions:
                out.append({"prio": 2, "machine": sp.id, "action": "dispatch_crew",
                            "text": f"{sp.id} is stopped but still faulty. Send a crew to repair it before restarting."})
            elif m.state in ("WARN", "CRIT"):
                w = m.worst_sensor()
                text, action = ADVICE[w["role"]][1 if m.state == "CRIT" else 0]
                done = action in m.actions or (action == "emergency_stop" and m.stopped) or (action == "dispatch_crew" and m.crew_eta > 0)
                if done:
                    out.append({"prio": 3, "machine": sp.id, "action": None,
                                "text": f"Done: {ACTION_LABELS[action].lower()} on {sp.id}. Keep watching {w['label'].lower()}."})
                else:
                    eta = f" (about {w['eta']} s to critical)" if w["eta"] else ""
                    out.append({"prio": 1 if m.state == "CRIT" else 2, "machine": sp.id, "action": action,
                                "text": text.format(m=f"{sp.name} ({sp.id})") + eta})
        mode_adv = {
            "EVACUATE": [(1, f"Sound the alarm and move everyone to the {MUSTER_NAME}. Complete the roll call."),
                         (1, f"Call the fire brigade / emergency services and brief them: {self.hazard[1] if self.hazard else 'life-risk condition'}."),
                         (1, "Nobody re-enters until the Safety Officer gives the all-clear.")],
            "FAILURE": [(1, "Keep the failed machine's zone restricted and its power locked out."),
                        (2, "Switch to standby equipment or shed load to keep the rest of the plant stable."),
                        (2, "Log the failure and start a root-cause review.")],
            "CRITICAL": [(1, "Keep non-essential staff out of the affected zone and prepare a controlled shutdown.")],
            "WARNING": [(3, "Log the event and plan an inspection before the end of the shift.")],
            "NORMAL": [(3, "All readings normal. Keep to the routine inspection schedule.")],
        }
        for prio, text in mode_adv[self.mode]:
            out.append({"prio": prio, "machine": None, "action": None, "text": text})
        out.sort(key=lambda a: a["prio"])
        return out[:7]

    # ---- snapshot ---------------------------------------------------------------------
    def snapshot(self, phone_employee: str = SAMPLE_PHONE_EMPLOYEE) -> dict:
        recent = [a for a in self.alerts if self.tick - a["tick"] <= 14 and a["level"] in ("CRITICAL", "FAILURE", "EVACUATE", "WARNING")]
        emp_alert = {}
        for a in recent:
            for r in a["recipients"]:
                emp_alert[r] = a
        employees = []
        for eid, name, role, zone, home, delay in ROSTER:
            p = self.progress[eid]
            mx = MUSTER_RECT[0] + 16 + (int(eid[1:]) - 1) % 3 * 28
            my = MUSTER_RECT[1] + 20 + (int(eid[1:]) - 1) // 3 * 24
            x, y = home[0] + (mx - home[0]) * p, home[1] + (my - home[1]) * p
            a = emp_alert.get(eid)
            if self.mode == "EVACUATE" and p >= 1.0:
                status = "safe"
            elif a and self.tick >= a["tick"] + delay:
                status = "acked"
            elif a:
                status = "notified"
            else:
                status = "ok"
            employees.append({"id": eid, "name": name, "role": role, "zone": zone, "x": x, "y": y, "status": status})
        alerts_out = []
        for a in reversed(self.alerts[-8:]):
            d = dict(a)
            d["acked"] = self._acked(a) if a["level"] != "CLEAR" else 0
            d["total"] = len(a["recipients"])
            alerts_out.append(d)
        phone_alert = None
        for a in reversed(self.alerts):
            if phone_employee in a["recipients"]:
                phone_alert = dict(a)
                break
        pe = next(e for e in ROSTER if e[0] == phone_employee)
        counts = {k: sum(1 for m in self.machines if m.state == k) for k in ("OK", "WARN", "CRIT", "STOPPED", "FAILED")}
        return {
            "tick": self.tick, "clock": clock(self.tick), "mode": self.mode, "mode_label": MODE_LABEL[self.mode],
            "risk": self.risk, "risk_history": list(self.risk_hist), "hazard": self.hazard[1] if self.hazard else None,
            "machines": [{
                "id": m.spec.id, "name": m.spec.name, "kind": m.spec.kind, "zone": m.spec.zone,
                "zone_name": ZONES[m.spec.zone][0], "state": m.state, "risk": int(round(m.risk)),
                "risk_history": list(m.risk_hist), "sensors": m.sensor_info, "pos": m.spec.pos,
                "notes": self._notes(m),
            } for m in self.machines],
            "alerts": alerts_out,
            "phone": {"name": pe[1], "role": pe[2], "zone": ZONES[pe[3]][0], "alert": phone_alert},
            "log": list(reversed(self.log_items[-10:])),
            "employees": employees,
            "advice": self.advice(),
            "counts": counts,
            "people": {"total": len(ROSTER), "at_muster": sum(1 for e in employees if e["status"] == "safe"),
                       "acked": sum(1 for e in employees if e["status"] in ("acked", "safe")),
                       "notified": sum(1 for e in employees if e["status"] != "ok")},
            "scenario": self.scenario,
        }

    def _notes(self, m: Machine) -> list:
        notes = []
        if "reduce_load" in m.actions:
            notes.append("Load reduced")
        if "boost_cooling" in m.actions:
            notes.append("Cooling boosted")
        if "isolate_vent" in m.actions:
            notes.append("Isolated / venting")
        if m.crew_eta > 0:
            notes.append(f"Crew arriving in {m.crew_eta * TICK_SECONDS} s")
        if "crew_on_site" in m.actions:
            notes.append("Crew repairing")
        return notes
