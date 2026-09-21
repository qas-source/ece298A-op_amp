# AGENTS.md — working on gf180mcuD analog Tiny Tapeout projects

A field guide for agents building **analog** Tiny Tapeout projects on the **gf180mcuD** PDK
(the `ttgf` shuttles): **(A)** porting an existing analog design (IHP sg13g2 / sky130), or
**(B)** creating a new one. It captures the flows, the device/verification techniques the working
gf180 analog projects use, and the **pitfalls that pass `magic` DRC and still fail the foundry**.
Distilled from the shuttle's analog projects (555 timer, OTA test buffer, R2R DAC, MOM cap, analog
factory test, and the `oscillating-bones` ring-oscillator port).

---

## TL;DR — the things that bite

1. **The KLayout `gf180mcu.drc` deck is the sign-off; the TT precheck runs it.**
   `magic DRC = 0` is a *weaker* separate check — it does **not** verify off-grid vertices, exact cut
   sizes, or metal slotting, and a layout can have thousands of KLayout violations while magic reports
   zero. The precheck runs the full deck (FEOL+BEOL+connectivity), so a **green precheck = clean
   sign-off**. Run the same deck locally (`make drc_klayout`) for fast iteration instead of waiting on
   CI.
2. **Density (PL.8 / M*.4 / MT.3) is not your problem** — ignore density violations. They're met by
   dummy fill added *after* precheck (the precheck explicitly excludes the density rules). Don't try
   to fill a single macro to 30%.
3. **Scaling a foreign layout breaks the grid and the cuts.** A 130nm→180nm port scales geometry
   (~1.45×), which pushes every vertex off the **5 nm** grid and makes contacts/vias the wrong size.
   gf180 cuts are **fixed-size** (Contact 0.22, Via1/2/3 0.26 µm — *exact*). Fix with
   `scripts/sanitize_gf180.py`.
4. **Write your final GDS at 1 nm DB precision** (geometry on the 5 nm grid, file precision 1 nm).
   5 nm file precision makes magic mis-recognize PDK std cells and flatten them → LVS blow-up.
5. **You provide the substrate/well taps.** The harness gives you nothing. Verify by *extraction*
   that every nfet body reaches VGND and every pfet body its positive rail.

---

## Pick a flow

Analog TT projects on this shuttle use one of three layout flows. All three deliver a committed
`gds/<top>.gds` + `lef/<top>.lef` that `TinyTapeout/tt-gds-action/custom_gds@<ttgf-ref>` packages —
**CI does not harden your layout**, so DRC/LVS must be clean before you push.

1. **Magic + xschem + netgen (the dominant analog methodology).** Hand-draw each block as a `.mag`
   in magic with a matching xschem `.sch`/`.sym`; LVS reconciles the two. Reusable, near
   project-agnostic harness lives in `mag/Makefile` + `mag/tcl/*.tcl` (see the **555** and
   **analog_factory_test** repos — only `PROJECT_NAME` changes). This is schematic-first: every
   device cell is a `.mag` + `.sch` + `.sym` triple verified by LVS.
2. **OpenLane/LibreLane for the digital part + magic assembly (mixed-signal).** Harden the digital
   block with `librelane` on a `config.tcl`, then `use`-instance the resulting GDS as a child cell
   in magic next to hand-drawn analog inside the TT frame (see the **R2R DAC**). Key config:
   `RT_MAX_LAYER Metal4`, `DESIGN_IS_CORE 0` (no core power rings, no Metal5), `FP_PIN_ORDER_CFG` to
   steer outputs to the analog-facing edge, `PL_RESIZER_BUFFER_OUTPUT_PORTS 0` (don't buffer
   analog-bound outputs). **Watch: copied OpenLane configs leak sky130 cell names** (`sky130_fd_sc_*`
   decap) — strip them; the gf180 SC lib is `gf180mcu_fd_sc_mcu7t5v0` (7-track, 5V).
3. **Programmatic GDS.** Generate the artwork in code — `gdstk` (the oscillating-bones port) or even Python
   that prints magic ASCII (the **MOM cap**'s `gen_momcap.py`). Use the template's
   `scripts/sanitize_gf180.py` afterward for grid/cut/implant clean-up.

### The TT-analog frame bootstrap (all flows start here)
The canonical entry point is the analog DEF frame, **not** a blank canvas. It fixes the exact port
positions, the `FIXED_BBOX` (the 1×2 tile, ~`69328 × 65072` magic units), and the power stripes:

- `def read tt_analog_1x2.def` (or `tt_analog_1x2_3v3.def` for a VAPWR design) from
  `tt-support-tools/tech/gf180mcuD/def/analog/`, then **rename `tt_um_template` → your `tt_um_*` top**.
- Draw power stripes on **Metal4**, width **2 µm** (min 1.2 µm), spanning ~5..220 µm:
  `VDPWR` and `VGND` always; **`VAPWR` only for the `_3v3` frame**. Make each a `port` with
  `port use power|ground`, `port class bidirectional`, `port connections n s e w`.
- See `r2r_dac/mag/tcl/tt-analog-draw.tcl` for a ready-made `make start` that does all of this.

---

## Build & verify commands

This template ships a generic `Makefile` (for the programmatic/gdstk flow; `TOP` is auto-read from
`info.yaml`). For the magic+xschem flow, copy the `mag/Makefile` + `mag/tcl/*` harness from the 555
or factory-test repo and adjust `PROJECT_NAME`.

```
make drc_klayout   # the sign-off DRC: full KLayout gf180mcu.drc deck (deep), invoked as the precheck does
make drc_summary   # split the last KLayout run into real violations vs. (ignorable) density
make antenna       # the antenna check (the precheck runs it as a separate pass)
make drc           # magic DRC — fast, but WEAKER (no off-grid / exact-cut / slot checks)
make sanitize      # 5nm-grid + exact-cut + implant-merge an already-remapped/hand-drawn gf180 GDS
make precheck      # the Tiny Tapeout precheck (= magic DRC + full KLayout deck + antenna + structural)
```

**Verification harness (magic + netgen + xschem), reusable from the reference repos:**
- **DRC**: magic `drc(full)` for a fast local check; the **KLayout deck (via `make drc_klayout` or
  the precheck) is the gate.** It excludes density (filled later) and runs antenna separately.
- **LVS**: `netgen` with `-blackbox`. Magic side: `ext2spice lvs; ext2spice cthresh infinite;
  ext2spice short resistor` (the `short resistor` keeps parasitic R from breaking the match). The
  netgen *source* side is a **mix**: standard-cell SPICE + the **gate-level PnL Verilog** of any
  OpenLane block + the **xschem-exported SPICE** of each analog leaf cell + the `tt_um_*` Verilog
  top. The `tt_um_*` Verilog top doubles as the golden netlist, so express the design's structure
  (and supply-domain split) there. Grep the report for `match uniquely` / property / pin / port.
- **Sim**: xschem testbenches in **ngspice**. Load models via a `TT_MODELS` block —
  `.include $PDK_ROOT/gf180mcuD/libs.tech/ngspice/design.ngspice` +
  `.lib $PDK_ROOT/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical` (plus `res_typical`,
  `moscap_typical` corners). Bias each rail with an explicit DC `vsource` to a star `VGND`; current
  bias via `isource`. **Short ngspice ammeter probes for LVS** (`lvs_ignore=short`).
- **Mixed-signal sim**: ngspice `d_cosim` driving a **Verilator-compiled gate-level `.so`** feeding
  the extracted analog netlist (`r2r_dac/sim/mixed.cir`). Model the TT analog output path with a
  **~500 Ω series + ~5 pF** load to check settling.
- **Emit artifacts**: `gds write` + `lef write -pinonly -hide`. **Commit** `.mag`/`.sch`/`.sym` and
  the final `gds/`+`lef/`; **gitignore** all extraction intermediates (`*.lvs.spice`, `*.pex.spice`,
  `ext/`, `simulation/`, `*.raw`, `lvs.report`).

---

## Tools & environment

You need `magic`, `netgen`, `klayout`, `ngspice`, and (for the magic+xschem flow) `xschem` and
`librelane`, plus the gf180mcuD PDK and a checkout of `tt-support-tools`. Get them however your
environment provides them — the rest of this guide is agnostic to which:

- **Tools**: a system/package install (apt, conda, a from-source build), the TT/OpenLane **Docker**
  images (which bundle the toolchain), or **Nix / nix-portable** (e.g. `nix shell nixpkgs#klayout`,
  optionally wrapped in a small `klayout` script on `PATH`). **Regardless of setup, the KLayout
  *binary* is required** to run the DSL DRC deck — the `pya`/`klayout.db` Python module alone is not
  enough (it's fine for scripting geometry checks).
- **PDK**: install gf180mcuD with **`ciel`** (the PDK manager). Don't pull `open_pdks` directly and
  don't use `volare` (deprecated) — that way lies a rabbit hole. Set `PDK_ROOT` to the install dir
  and `PDK=gf180mcuD`. Everything the flow needs lives under it:
  magicrc `$PDK_ROOT/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc`, ngspice models
  `$PDK_ROOT/gf180mcuD/libs.tech/ngspice/`, netgen setup
  `$PDK_ROOT/gf180mcuD/libs.tech/netgen/gf180mcuD_setup.tcl`, DRC decks
  `$PDK_ROOT/gf180mcuD/libs.tech/klayout/tech/drc/`, and the SC library under
  `$PDK_ROOT/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/`. Prefer the **latest** PDK/deck — the
  foundry runs the latest at tapeout, which can be newer than a given precheck pin.
- **tt-support-tools** (the precheck + analog DEF frames): clone
  `https://github.com/TinyTapeout/tt-support-tools` — always use the **`main`** branch (it is not
  shuttle-specific). Point the `Makefile`'s `TT_TOOLS` at it.
- **CI**: in `.github/workflows/gds.yaml`, pin the **`tt-gds-action` ref to your shuttle** (e.g.
  `ttgf26a` / `ttgf0p3`) and use the `custom_gds` entrypoint. (Only the action ref is
  shuttle-specific; the tools it pulls track `tt-support-tools` `main`.)

---

## Device & verification techniques

- **Voltage domains pick the device flavor.** Analog on **VAPWR (5 V)** → use **5 V/6 V** devices
  (`*_05v0`/`*_06v0`); their magic `.mag` uses MV layers (`mvnmos`, `mvpmos`, `mvndiff`,
  `mvpsubdiff`, `mvnsubdiffcont`, etc.) — a gdstk layer map must distinguish MV from LV. Digital on
  **VDPWR (3.3 V)** → `*_03v3`. For 3.3V custom FETs do **NOT** add Dualgate(55/0) (it extracts 6 V
  devices, min gate 0.55/0.70 µm → ~2.5× blow-up); plain `nfet_03v3`/`pfet_03v3` give min gate 0.28.
- **Level-shift across supplies.** Never drive a **VAPWR(5 V)-domain gate directly from a VDPWR(3.3 V)
  logic pin** — insert a level shifter (`lv2hv`: 3.3 V input inverter → cross-coupled 5 V latch,
  output swings VGND↔VAPWR). See `analog_factory_test`.
- **Body/bulk handling — two valid styles.** Either 4-terminal symbols (`nfet_06v0`) with the bulk
  brought out as a routed `B` pin tied to a rail in schematic, **or** 3-terminal `nfet3_*`/`pfet3_*`
  with a `body=<rail>` parameter (no routed bulk — simplest when bulk = the nearest rail).
- **Substrate & well taps are yours to draw.** Per-device tap rings (`mvpsubdiff`+`mvpsubdiffcont`
  for NMOS→GND, `nwell`+`mvnsubdiff`+`mvnsubdiffcont` for PMOS→VDD), or a **continuous substrate
  guard ring** with contiguous contacts around large multi-finger devices. Verify by extraction:
  every `nfet_*` bulk → `VGND`, every `pfet_*` bulk → `VDPWR`/`VAPWR`, **no `VSUBS`** node, no
  floating `w_*` wells. (If sim ties the substrate by *renaming* a `VSUBS` net, it's masking a
  missing tap.)
- **Matching by construction**, not by trusting a value: build from a **unit device** and use integer
  ratios — `m=` multiplicity, `nf=` fingers, and series/parallel of the unit. R-2R = one unit "R" and
  **two units in series** for "2R" (never a 2×-sized resistor). Carry the canonical gf180 parasitic
  area/perimeter formulas on every FET (`ad="'int((nf+1)/2)*W/nf*0.18u'"`, matching `pd/as/ps`,
  `nrd/nrs="'0.18u/W'"`). Include **explicit dummy devices** in the schematic so they appear in LVS
  and match the layout.
- **Resistors**: gf180 unsalicided p+ poly `ppolyf_u_1k` (~1 kΩ/sq, layer `nhighres`) as magic
  *gencells* inside a `pwell`+`psubdiff` guard ring; value comes from W/L (`r_width`/`r_length`).
- **MOM cap**: interdigitated comb across **Metal1–Metal4** stitched with via1/2/3 (vertical +
  lateral field); a **fine-pitch finger grid auto-satisfies metal density/slotting** (no wide
  plates). Report the magic-extracted capacitance in the datasheet.
- **Bias & stimulus**: bring an external current bias (e.g. 5 µA) in on an analog pin and mirror it
  internally, or self-bias a reference (poly R + diode-connected FET). You can reuse your own analog
  block + an on-chip RC as a self-clocking oscillator for a free stimulus output.

---

## Instantiating standard cells inside an analog macro

You can drop **gf180 digital standard cells** into an analog macro for control logic (counters,
dividers, FSMs, decoders) instead of hand-drawing gates — very useful for mixed-signal designs. The
library is **`gf180mcu_fd_sc_mcu7t5v0`** (7-track, 5 V) under
`$PDK_ROOT/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/` (`mag/`, `gds/`, `lef/`, `spice/`).

- **Place them**: in magic, `addpath $PDK_ROOT/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/mag` then
  `use gf180mcu_fd_sc_mcu7t5v0__<cell> <inst>` and abut them into a row; in gdstk, read
  `$PDK_ROOT/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/gds/gf180mcu_fd_sc_mcu7t5v0.gds` and place the
  cells you need as references. OpenLane (flow 2) places/routes them for you.
- **The wells float without tap cells — this is the gotcha.** The SC cells expose `VNW` (n-well) and
  `VPW` (p-well) as **well layers only**, with no taps. Put a **`filltie`** cell between every cell
  and an **`endcap`** at each row end — these tie VNW→VDD and VPW→VSS. Then **strap the row's VDD/VSS
  rails to your VDPWR/VGND** (the macro's power stripes). Without this the cells don't work and
  extraction shows floating wells.
- **Do NOT scale std cells.** They are pre-built DRC-clean — place them **unscaled and on-grid**,
  even when you are scaling/remapping foreign artwork around them.
- **Write the macro at 1 nm precision** or magic won't recognize the cells and will flatten them
  (Pitfall 2 → LVS device-count blow-up).
- **5 V cells run fine on the 3.3 V VDPWR core** (just not at max speed) — no separate supply needed.
- **gf180 DFFs have no `QN` output.** To build a toggle/ripple stage, feed `D = ~Q` through an `inv`
  cell (e.g. `dffrnq_1` + `inv_2`, as in the oscillating-bones divider).
- **LVS**: the cells appear as subckt instances; add the SC SPICE
  (`$PDK_ROOT/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/spice/gf180mcu_fd_sc_mcu7t5v0.spice`) to the
  netgen source side, and they cross-check by name.

## Power / pins / supply domains

- **Common VGND.** Put the quiet analog signal path on **VAPWR**, any digital/switching block on
  **VDPWR**, and express the split **structurally** — separate child modules each taking a single
  `.VDD`. The `tt_um_*` Verilog top encodes this and is the LVS golden netlist. `info.yaml`:
  `uses_vapwr: true` only if you actually use the 2nd analog supply; `analog_pins` = the count you
  use; `tiles: "1x2"`.
- **Tie every unused output bit low, in Verilog.** This includes unused `uo_out` bits — not only
  `uio_out`/`uio_oe` — so tie exactly the bits your design doesn't drive (e.g.
  `assign uo_out[7:1] = {7{VGND}};` if only `uo_out[0]` is used, or `assign uo_out = {8{VGND}};` if
  none are). Set `uio_oe` low on unused bidir bits (low OE keeps the pad in input/high-Z). In xschem,
  put a `noconn`
  on every unused analog/digital pin to silence floating-pin warnings.
- **Pins on Metal4** at the DEF-template positions; in magic the `flabel`/`port` direction keyword
  (`signal` / `bidirectional` / `input` / `output`) matters for LVS and the emitted LEF. Keep
  `FIXED_BBOX` set so frame placement is deterministic.
  Power stripes span >90 % of die height. **Sense/Kelvin trick**: route raw rails out to `ua[*]`
  (`ua=VGND/VDPWR/VAPWR`) to measure IR drop; an `ua[i]=ua[j]` loopback characterizes the analog mux.
- Cross-check **LEF == GDS == DEF** (pin names, Metal4, positions; LEF `SIZE`/`DIRECTION`/
  `USE POWER|GROUND`).

---

## Pitfalls (the expensive ones)

1. **Trust the KLayout deck, not `magic DRC`.** magic snaps to its own grid and treats cuts as a
   *type*, so it misses off-grid, exact-cut-size, and slotting. Run the full KLayout deck (it's what
   the precheck runs); treat everything except density as real.
2. **Write the GDS at 1 nm precision.** A 5 nm DB precision (e.g. inherited from reading a
   5 nm-precision sub-cell) makes magic fail to recognize the PDK std cells and flatten them into raw
   transistors, so the extracted device count balloons and LVS no longer matches. Keep geometry on
   the 5 nm grid *by construction*; set `lib.precision = 1e-9`.
3. **Off-grid + wrong-size cuts from scaling.** Any non-integer scale lands vertices on 1 nm not
   5 nm (`*_OFFGRID`), and turns fixed cuts into garbage (Contact 0.232 not 0.22 → `CO.1`; Via 0.275
   not 0.26 → `V*.1`). Fix: snap to 5 nm; **replace** each cut with an exact on-grid square (don't
   scale it). Guard against cuts drawn as bars (those need array fill).
4. **Hand-placed cell coordinate frames.** A hand-built sub-cell (buffer/pad) is often **centred at
   the origin**, and an assembly script's pin offsets depend on that frame. Regenerating it from
   source with the source's native origin silently misplaces it by microns → floating nets,
   spacing/antenna violations, LVS net mismatches. Sanitize such cells **in place**.
5. **Metal5 forbidden, MetalTop unreachable.** Usable routing = **Metal1–Metal4**. Collapse a foreign
   5–7 metal stack onto Metal4, and watch that collapsed power rings don't bridge VGND↔VDPWR. In
   OpenLane this is `RT_MAX_LAYER Metal4` + `DESIGN_IS_CORE 0`.
6. **Implants from p-select, then merge & clip.** Build Pplus = COMP∩pSD, Nplus = COMP−pSD (the bare
   n+ COMP inside Nwell are the **n-well taps** — keying implants off Nwell membership buries them and
   floats pfet bodies). Merge same-type implants (`NP.2`/`PP.2`, 0.40 µm) and clip each off the
   opposite COMP (`NP.3a`/`PP.3a`, 0.16 µm).
7. **MSLOT — slot wide metal minimally.** Solid metal >30 µm in **both** axes trips `MSLOT.1`. The
   rule's opening removes metal ≤30 µm in **either** axis, so a **single** slot in one direction is
   enough — *not a cross/grid*. Cut the fewest slots, only over the wide cores. Foundry's nominal min
   slot is 2 µm (`MSLOT.2`); a thinner hole passes the geometric check but gives ~no real CMP relief.
8. **`magic DRC` / a green precheck cover geometry, not your circuit.** Always also confirm by
   *extraction + sim* that bodies/wells are tied and nothing floats, and run **LVS separately** —
   never run `sim` and `lvs` concurrently (they share magic extraction temp files and corrupt each
   other; a bogus count like `77 vs 60` means re-run alone).
9. **Boilerplate leakage**: copied OpenLane configs carry **sky130** cell names; pin the wrong TT
   action branch and CI breaks. Strip sky130 refs; use `gf180mcu_fd_sc_mcu7t5v0` and the ttgf ref.

---

## gf180mcuD cheat-sheet

| thing | value |
|---|---|
| Manufacturing grid | **5 nm** (`layer.ongrid(0.005)`) |
| Contact (`CO.1`) | **exactly 0.22 µm** square; Via1/2/3 (`V*.1`) **exactly 0.26 µm** |
| Contact / via spacing | 0.25 / 0.26 µm |
| Metal4 width / spacing | 0.28 / 0.28 µm (wide-metal `M4.2b` 0.30) |
| Implant enclosure / same-type spacing | 0.16 / 0.40 µm (`NP.2`/`PP.2`) |
| Max solid metal w/o slots (`MSLOT.1`) | 30 µm; min slot width (`MSLOT.2`) 2 µm |
| Density (`PL.8`/`M*.4`/`MT.3`) | **ignore — fill at integration** (precheck excludes them) |
| Usable routing metals | **Metal1–Metal4** (Metal5 `81` forbidden, MetalTop unreachable) |
| 3.3 V custom FETs | `nfet_03v3`/`pfet_03v3`, **no Dualgate**; 5 V analog → `*_05v0`/`*_06v0` (MV layers) |
| SC library | `gf180mcu_fd_sc_mcu7t5v0` (7-track, 5 V); poly R `ppolyf_u_1k` (~1 kΩ/sq) |
| Power stripes | Metal4, width 2 µm (min 1.2); `VDPWR`+`VGND` always, `VAPWR` for 3v3 frame |
| Key layers | COMP 22/0, Poly2 30/0, Contact 33/0, M1 34/0, Via1 35/0, M2 36/0, Via2 38/0, Via3 40/0, M3 42/0, M4 46/0, pin dt `10`, Nwell 21/0, Pplus 31/0, Nplus 32/0, LVPWELL 204/0 |

## Pre-submission checklist

- [ ] **Precheck green** (= magic DRC + full KLayout FEOL/BEOL/conn deck + antenna + structural) —
      run it locally and/or in CI. Ignore density violations; fix everything else.
- [ ] Post-layout sim passes with the testbench supplying **only** the rails (+ substrate bias) — no
      forced std-cell rails or wells; behaviour reflects real extracted connectivity.
- [ ] Extraction shows every body tied (nfet→VGND, pfet→VDPWR/VAPWR), **no `VSUBS`**, no floating
      `w_*` wells.
- [ ] LVS matches device-class + net counts (run LVS **alone**).
- [ ] LEF == GDS == DEF; power pins span >90 %; every unused output bit tied low (`uo_out` bits too,
      not just `uio_out`/`uio_oe`).
- [ ] `info.yaml` (`analog_pins`, `uses_vapwr`, `tiles`, `top_module`, pinout) correct; `src/project.v`
      is a black-box / structural interface only.
- [ ] Committed: `.mag`/`.sch`/`.sym` (magic flow) and the final `gds/`+`lef/`; intermediates ignored.

A fully worked reference (a gdstk port with all of the above) is `ttgf-oscillating-bones`; the
magic+xschem harness lives in the `tt_tnt_gf_555` and `ttgf_analog_factory_test` repos; the
OpenLane-analog + mixed-signal-sim flow in `gf-r2r-dac`; a metal-only passive in `ttgf0p3-momcap`.
