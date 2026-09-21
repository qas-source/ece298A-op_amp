# SPDX-License-Identifier: Apache-2.0
#
# gf180mcuD analog Tiny Tapeout — DRC / sanitize / precheck helpers.
# Operates on a hardened GDS at $(GDS); set TOP to your top_module (must match info.yaml).
# See AGENTS.md for the full workflow and the pitfalls these targets exist to catch.
#
#   make drc_klayout   # THE sign-off DRC (full KLayout FEOL/BEOL/conn deck, deep mode)
#   make drc_summary   # real violations vs. density-fill, from the last run
#   make drc           # magic DRC (fast, weaker — does NOT catch off-grid/exact-cut/slot)
#   make sanitize      # grid-snap + exact-cut + implant-merge an already-remapped gf180 GDS
#   make precheck      # the Tiny Tapeout precheck (magic DRC + full KLayout deck + antenna + structural)

# Read top_module from info.yaml unless overridden:  make TOP=tt_um_yourname ...
TOP ?= $(shell sed -n 's/^[[:space:]]*top_module:[[:space:]]*"\{0,1\}\([^" ]*\).*/\1/p' info.yaml)
TOP := $(if $(TOP),$(TOP),tt_um_example)
GDS ?= gds/$(TOP).gds

PDK       := gf180mcuD
MAGIC_RC  := $(PDK_ROOT)/$(PDK)/libs.tech/magic/$(PDK).magicrc
DRC_DECK  := $(PDK_ROOT)/$(PDK)/libs.tech/klayout/tech/drc/gf180mcu.drc
# tt-support-tools checkout (for the precheck). Override if it lives elsewhere.
TT_TOOLS  ?= /workspace/tt-support-tools

# --- authoritative sign-off DRC -------------------------------------------------------------------
# The full KLayout gf180mcu.drc deck (FEOL + BEOL + connectivity) — the same deck the Tiny Tapeout
# precheck runs, so this IS the sign-off; run it locally for fast iteration. It catches off-grid,
# exact-cut-size and metal-slotting that magic DRC silently passes. Needs the klayout binary on PATH
# (not just the python module). We keep density in the local report for visibility (the precheck
# excludes it — it's filled at chip integration); `make drc_summary` splits real violations from
# density. Antenna has its own pass — see `make antenna`.
define need_gds
	@test -f $(GDS) || { echo "ERROR: $(GDS) not found. Harden your design first, then set TOP=<module> or GDS=<path>."; exit 1; }
endef

KLAYOUT_DRC = klayout -b -zz -r $(DRC_DECK) -rd input=$(abspath $(GDS)) -rd topcell=$(TOP) \
	-rd variant=gf180mcuD -rd run_mode=deep -rd thr=16

drc_klayout:
	$(need_gds)
	mkdir -p drc
	$(KLAYOUT_DRC) -rd report=$(abspath drc/gf180_drc.lyrdb) -rd decks=all,-antenna
	@$(MAKE) --no-print-directory drc_summary
.PHONY: drc_klayout

# Antenna check (the precheck runs this separately from the main deck).
antenna:
	$(need_gds)
	mkdir -p drc
	$(KLAYOUT_DRC) -rd report=$(abspath drc/gf180_antenna.lyrdb) -rd decks=antenna
.PHONY: antenna

drc_summary:
	@python3 scripts/drc_summary.py drc/gf180_drc.lyrdb
.PHONY: drc_summary

# --- magic DRC (fast, WEAKER) ---------------------------------------------------------------------
drc:
	$(need_gds)
	echo "gds read $(GDS); load $(TOP); select top cell; drc euclidean on; drc check; drc catchup; \
		puts \"magic DRC violations: [drc list count total] (NOT sign-off — see make drc_klayout)\"" | \
		magic -rcfile $(MAGIC_RC) -noconsole -dnull
.PHONY: drc

# --- geometry sanitizer (for ported / hand-drawn artwork) -----------------------------------------
sanitize:
	python3 scripts/sanitize_gf180.py $(GDS) $(GDS)
.PHONY: sanitize

# --- Tiny Tapeout precheck (same checks as CI) ----------------------------------------------------
precheck:
	$(need_gds)
	cd $(TT_TOOLS)/precheck && python3 precheck.py --gds $(abspath $(GDS))
.PHONY: precheck
