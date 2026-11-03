"""Cost build-up for the three-station pilot (feeds the proposal's costing section).

Local civil and installation items are priced from published Nigerian rate books; imported equipment has no public
price list among the sources consulted, so its figures are planning ASSUMPTIONS and are labelled as such.

Sources (accessed 2 Nov 2026):
  Buildocrat Rate Book, rates as at 24 Oct 2026, Abuja base, net of overheads and profit; N1,365 to the US dollar
  BuildMNO Rate Card, Q4 2026 (Lagos and South West baseline; Abuja about 1.2 to 1.3 times higher; professional fee ranges)
  National Bureau of Statistics home page: all-items inflation 14.63 %
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FX = 1365.0                      # NGN per USD (Buildocrat, 24 Oct 2026)
OHP, VAT, ESC, CONT, PROF = 0.15, 0.075, 0.15, 0.15, 0.05
EQUIP_PER_STATION = 30000.0 + 3000.0   # ASSUMPTION: WIM/classification equipment + temperature probe, gateway, modem
EQUIP_CONT = 0.15
ITEMS = [  # description, Buildocrat code, quantity, unit, rate in NGN
    ("Break up existing pavement for sensor slots (150 mm slab, six lanes)", "H02", 36, "m$^2$", 16942),
    ("Reinforced concrete 1:2:4 for sensor frames and cabinet base", "B02", 11, "m$^3$", 127723),
    ("Asphalt wearing course, 50 mm, reinstatement", "R06", 36, "m$^2$", 20481),
    ("Tack coat", "R05", 36, "m$^2$", 420),
    ("Cable trench by backhoe", "A09", 48, "m$^3$", 5277),
    ("Backfill and compaction of trench", "A04", 48, "m$^3$", 2899),
    ("Armoured power cable, 16 mm$^2$, four-core, laid", "F25", 150, "m", 24027),
    ("Earthing set (rod, conductor, inspection pit)", "F27", 2, "nr", 69839),
    ("5 kVA hybrid solar system with battery, installed", "F32", 1, "nr", 4960450),
    ("Precast concrete safety barrier around the cabinet", "R23", 30, "m", 105047),
    ("Retro-reflective road sign on post", "R26", 4, "m$^2$", 137810),
    ("Thermoplastic road marking, 100 mm line", "R12", 200, "m", 711),
    ("Setting out by surveyor and two chainmen", "Z08", 3, "day", 65237),
    ("Asphalt core and extraction tests", "Z14", 6, "nr", 40000),
    ("IP CCTV camera with cable and recorder share", "X16", 2, "nr", 113384),
]
OTHER_USD = [("Instrumented probe loggers (five, phone or inertial)", 5 * 300.0),
             ("Reference profilometer surveys (two campaigns)", 2 * 5000.0),
             ("Static axle-scale checks of the stations", 3000.0),
             ("Pilot server and uninterruptible power supply", 2500.0)]


def n(x):  # thousands with a thin space for LaTeX
    return f"{x:,.0f}".replace(",", "\\,")


net = sum(q * r for _, _, q, _, r in ITEMS)
ohp = OHP * net
sub = net + ohp
vat, esc, cont, prof = VAT * sub, ESC * sub, CONT * sub, PROF * net
station_ngn = sub + vat + esc + cont + prof
station_usd = station_ngn / FX
equip_station = EQUIP_PER_STATION * (1 + EQUIP_CONT)
pilot_local = 3 * station_usd
pilot_equip = 3 * equip_station
total = pilot_local + pilot_equip + sum(v for _, v in OTHER_USD)

rows = [f"{d} & {c} & {q} & {u} & {n(r)} & {n(q * r)}\\\\" for d, c, q, u, r in ITEMS]
rows += ["\\midrule", f"Net subtotal & & & & & {n(net)}\\\\",
         f"Contractor overhead and profit ({OHP*100:.0f}\\%) & & & & & {n(ohp)}\\\\",
         f"VAT ({VAT*100:.1f}\\%) & & & & & {n(vat)}\\\\",
         f"Price escalation ({ESC*100:.0f}\\%) & & & & & {n(esc)}\\\\",
         f"Contingency ({CONT*100:.0f}\\%) & & & & & {n(cont)}\\\\",
         f"Professional fees and project management ({PROF*100:.0f}\\% of net) & & & & & {n(prof)}\\\\", "\\midrule",
         f"\\textbf{{Local works per station}} & & & & & \\textbf{{{n(station_ngn)}}}\\\\"]
(ROOT / "docs" / "proposal" / "cost_boq.tex").write_text(
    "\\begin{tabularx}{\\textwidth}{@{}X l r l r r@{}}\n\\toprule\n\\textbf{Item} & \\textbf{Code} & \\textbf{Qty} & \\textbf{Unit} & \\textbf{Rate (NGN)} & \\textbf{Amount (NGN)}\\\\\n\\midrule\n"
    + "\n".join(rows) + "\n\\bottomrule\n\\end{tabularx}\n")
summ = [f"Local civil and installation works, three stations (NGN~{n(station_ngn)} each at NGN~{n(FX)}/USD) & {n(pilot_local)}\\\\",
        f"Imported equipment, three stations (USD {n(EQUIP_PER_STATION)} each plus {EQUIP_CONT*100:.0f}\\% contingency; \\emph{{assumed}}) & {n(pilot_equip)}\\\\"]
summ += [f"{d} & {n(v)}\\\\" for d, v in OTHER_USD]
(ROOT / "docs" / "proposal" / "cost_summary.tex").write_text(
    "\\begin{tabularx}{\\textwidth}{@{}X r@{}}\n\\toprule\n\\textbf{Item} & \\textbf{USD}\\\\\n\\midrule\n" + "\n".join(summ)
    + f"\n\\midrule\n\\textbf{{Total}} & \\textbf{{{n(round(total, -2))}}}\\\\\n\\bottomrule\n\\end{{tabularx}}\n")
md = [f"# Pilot cost build-up", "", f"Local works per station: N{station_ngn:,.0f} (USD {station_usd:,.0f} at N{FX:,.0f}/USD).",
      f"Equipment per station (assumption, incl. {EQUIP_CONT:.0%} contingency): USD {equip_station:,.0f}.",
      f"Pilot total: USD {total:,.0f}.", "", "Sources and caveats are in the module docstring of `scripts/cost_estimate.py`."]
(ROOT / "docs" / "costing.md").write_text("\n".join(md) + "\n")
print(f"station local N{station_ngn:,.0f} = USD {station_usd:,.0f}; equipment/station USD {equip_station:,.0f}; pilot USD {total:,.0f}")
