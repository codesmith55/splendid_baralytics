"""
BAR (Beyond All Reason) Economy Calculator
==========================================

Reads the BAR economy table (bar_eco_table.csv) and reports the energy
generators in the same format used in EcoGuide.md, e.g.:

    Solar : 150(155) M + 0 E + 2600 BP = 20 E/s : EROI = Build Time; TROI = 525s

Definitions used here (matching EcoGuide.md):
  * 70 E = 1 M     -- the T1 energy-converter "exchange rate"
  * EROI (Energy ROI) = time the generator takes to repay its OWN energy cost.
                        For zero-energy-cost gens (Solar) this collapses to
                        just Build Time.
  * TROI (Total ROI) = time to repay all input resources, expressed in
                        T1-converted Energy seconds:
                            (M_cost * 70 + E_cost) / output_E_per_s
  * Build Time     = BP_cost / builder_BP   (default builder = 300 BP T1 con)

Usage:
    python eco_calculator.py
    python eco_calculator.py --csv path/to/bar_eco_table.csv
    python eco_calculator.py --builder 300         # change builder BP
    python eco_calculator.py --wind 1.55           # override avg wind output
    python eco_calculator.py --md eco_extension.md # also write a markdown doc

CSV expected layout (side-by-side Armada | Cortex), columns:
    Name, E_cost, M_cost, BP_cost,  Name, E_cost, M_cost, BP_cost
"""

from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

ENERGY_PER_METAL = 70           # T1 energy-converter exchange rate
DEFAULT_BUILDER_BP = 300        # T1 constructor

# Known BAR energy-generator output rates (E/s).  Edit if the patch changes.
# Wind is variable: min/max are the in-game floor/ceiling; the actual rate
# depends on the map's wind speed (hover the windspeed box in-game).
ENERGY_OUTPUT = {
    "Solar":    {"type": "fixed",    "out": 20.0},
    "Wind":     {"type": "variable", "min": 0.6, "max": 2.5},
    "AdvSolar": {"type": "fixed",    "out": 75.0},
}


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class Building:
    faction: str
    name: str
    e_cost: int
    m_cost: int
    bp_cost: int

    def build_time(self, builder_bp: int = DEFAULT_BUILDER_BP) -> float:
        return self.bp_cost / builder_bp

    def eroi(self, output: float, builder_bp: int = DEFAULT_BUILDER_BP) -> float:
        """Time to repay the generator's own energy cost (seconds).

        For zero-energy-cost generators this is reported as build time
        (matching the convention in EcoGuide.md: 'EROI = Build Time')."""
        if self.e_cost == 0:
            return self.build_time(builder_bp)
        return self.e_cost / output

    def troi(self, output: float) -> float:
        """Total ROI in seconds: (M*70 + E) / output."""
        if output <= 0:
            return float("inf")
        return (self.m_cost * ENERGY_PER_METAL + self.e_cost) / output


# --------------------------------------------------------------------------
# CSV parsing
# --------------------------------------------------------------------------

def _to_int(s: str) -> int:
    s = (s or "").strip()
    return int(s) if s else 0


def parse_csv(path: Path) -> list[Building]:
    rows: list[Building] = []
    with path.open(newline="") as f:
        reader = csv.reader(f)
        # First row is the Armada/Cortex header label row -- skip it
        first = next(reader, None)
        if first and first[0].strip().lower() not in ("armada", "arm"):
            # No header -- treat as data
            _append_pair(rows, first)
        for row in reader:
            _append_pair(rows, row)
    return rows


def _append_pair(rows: list[Building], row: list[str]) -> None:
    if len(row) < 4:
        return
    arm_name = row[0].strip()
    if arm_name:
        rows.append(Building("Armada", arm_name,
                             _to_int(row[1]), _to_int(row[2]), _to_int(row[3])))
    if len(row) >= 8:
        cor_name = row[4].strip()
        if cor_name:
            rows.append(Building("Cortex", cor_name,
                                 _to_int(row[5]), _to_int(row[6]), _to_int(row[7])))


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def fmt_line(b: Building, output: float, builder_bp: int, label: str | None = None) -> str:
    bt = b.build_time(builder_bp)
    troi = b.troi(output)
    if b.e_cost == 0:
        eroi_str = f"Build Time ({bt:.1f}s)"
    else:
        eroi_str = f"{b.eroi(output, builder_bp):.1f}s"
    name = label or f"[{b.faction}] {b.name}"
    return (f"{name:<30} {b.m_cost:>4} M + {b.e_cost:>5} E + {b.bp_cost:>5} BP "
            f"= {output:>5.2f} E/s  |  EROI = {eroi_str:<18} TROI = {troi:>6.0f}s   "
            f"(BuildTime {bt:.1f}s @ {builder_bp} BP)")


def expand_generator(b: Building, builder_bp: int, wind_avg: float | None) -> Iterable[str]:
    cfg = ENERGY_OUTPUT.get(b.name)
    if cfg is None:
        return  # not an energy generator we know how to score

    if cfg["type"] == "fixed":
        yield fmt_line(b, cfg["out"], builder_bp)
        return

    # Variable (Wind)
    yield f"\n[{b.faction}] {b.name} -- variable, depends on map windspeed:"
    rates = [("min wind", cfg["min"]),
             ("max wind", cfg["max"])]
    if wind_avg is not None:
        rates.insert(1, (f"avg ~{wind_avg:.2f}", wind_avg))
    else:
        avg = (cfg["min"] + cfg["max"]) / 2.0
        rates.insert(1, (f"avg {avg:.2f} (mid)", avg))
    for label, out in rates:
        yield "  " + fmt_line(b, out, builder_bp, label=f"{b.name} @ {label}")


def cortex_bp_sanity(buildings: list[Building]) -> list[str]:
    """The provided CSV had a few suspiciously short Cortex BP values
    (e.g. 28 vs Armada's 2800).  Flag any case where the Cortex BP is
    smaller than 1/10 of its Armada twin so the user can double-check."""
    by_name: dict[str, dict[str, Building]] = {}
    for b in buildings:
        by_name.setdefault(b.name, {})[b.faction] = b
    warnings = []
    for name, pair in by_name.items():
        a, c = pair.get("Armada"), pair.get("Cortex")
        if a and c and c.bp_cost and a.bp_cost / max(c.bp_cost, 1) >= 10:
            warnings.append(f"  ! {name}: Armada BP={a.bp_cost} vs Cortex BP={c.bp_cost} "
                            f"(looks truncated -- verify the source table)")
    return warnings


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="BAR energy generator economy report.")
    parser.add_argument("--csv", default=str(Path(__file__).with_name("bar_eco_table.csv")),
                        help="Path to bar_eco_table.csv")
    parser.add_argument("--builder", type=int, default=DEFAULT_BUILDER_BP,
                        help="Builder BP (default 300, the T1 con)")
    parser.add_argument("--wind", type=float, default=None,
                        help="Override average wind E/s (e.g. 1.55)")
    parser.add_argument("--md", default=None, help="Optional path to write a markdown report")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    buildings = parse_csv(csv_path)

    header = [
        "=" * 100,
        "BAR Energy Generator Economy Report",
        f"  Conversion: {ENERGY_PER_METAL} E = 1 M   |   Builder: {args.builder} BP",
        "  EROI = time to repay E_cost (or Build Time when E_cost = 0)",
        "  TROI = (M*70 + E) / output_E_per_s   -- time to repay everything in E-seconds",
        "=" * 100,
    ]
    print("\n".join(header))

    lines: list[str] = []
    gen_order = ["Solar", "Wind", "AdvSolar"]
    for name in gen_order:
        for b in buildings:
            if b.name == name:
                for line in expand_generator(b, args.builder, args.wind):
                    print(line)
                    lines.append(line)
        print()
        lines.append("")

    warns = cortex_bp_sanity(buildings)
    if warns:
        print("Data sanity warnings (CSV may be truncated):")
        for w in warns:
            print(w)

    if args.md:
        write_markdown(Path(args.md), buildings, args.builder, args.wind)
        print(f"\nWrote markdown report to {args.md}")


def write_markdown(path: Path, buildings: list[Building], builder_bp: int,
                   wind_avg: float | None) -> None:
    out = ["# BAR Energy Generators -- Expanded ROI Table",
           "",
           f"_Conversion: {ENERGY_PER_METAL} E = 1 M.  Builder = {builder_bp} BP._",
           "",
           f"`Build Time = BP_cost / {builder_bp}`  ",
           "`EROI = E_cost / output`  (or Build Time if E_cost = 0)  ",
           f"`TROI = (M*{ENERGY_PER_METAL} + E) / output`",
           "",
           "| Faction | Generator | Output (E/s) | M | E | BP | Build Time | EROI | TROI |",
           "|---|---|---:|---:|---:|---:|---:|---:|---:|"]

    def row(b: Building, out: float, label: str = "") -> str:
        bt = b.build_time(builder_bp)
        eroi = "Build Time" if b.e_cost == 0 else f"{b.eroi(out, builder_bp):.1f}s"
        troi = b.troi(out)
        gen = f"{b.name}{(' (' + label + ')') if label else ''}"
        return (f"| {b.faction} | {gen} | {out:.2f} | {b.m_cost} | {b.e_cost} "
                f"| {b.bp_cost} | {bt:.1f}s | {eroi} | {troi:.0f}s |")

    for name in ["Solar", "Wind", "AdvSolar"]:
        for b in buildings:
            if b.name != name:
                continue
            cfg = ENERGY_OUTPUT[name]
            if cfg["type"] == "fixed":
                out.append(row(b, cfg["out"]))
            else:
                avg = wind_avg if wind_avg is not None else (cfg["min"] + cfg["max"]) / 2
                out.append(row(b, cfg["min"], "min wind"))
                out.append(row(b, avg,        f"avg {avg:.2f}"))
                out.append(row(b, cfg["max"], "max wind"))

    out += ["",
            "## Reading the numbers",
            "",
            "* **Solar** has E_cost = 0, so its EROI is just its build time.  TROI is the same",
            "  for both factions in *practice* because the M cost difference is tiny "
            "(150 vs 155).",
            "* **Wind** has the worst EROI when wind is low (energy paid up front, slow trickle",
            "  back), but on a windy map (>1.55 avg) its TROI beats Solar by a wide margin -- ",
            "  this is why Wind is the default if avg wind on the map is > ~1.1.",
            "* **AdvSolar** repays its huge E up-front cost in roughly a minute, but its TROI is",
            "  long because of the metal cost.  Build it for E/s density on a fortified base,",
            "  not for early-game ROI.",
            ""]
    path.write_text("\n".join(out))


if __name__ == "__main__":
    main()