# Curated experimental data: format and workflow

This fork of `raymondEhlers/hard-sector-data-curation` keeps the upstream raw HEPData
records under `data/` and adds a curated layer on top, so that an analysis reads every
measurement the same way. Two jobs, kept apart:

1. **Curation** writes down what the experiments published, in one fixed, plain-text
   format. It is lossless and makes no physics judgement: no symmetrising, no correlation
   model, no selection, no cuts.
2. **Analysis** (a Bayesian config, a plotting script) decides how to use it: which
   datasets, which pT range, how asymmetric and signed errors are treated, how sources
   correlate, which overlapping classes to drop.

The only judgement curation makes is light and recorded: which table holds which class,
what a raw error label is called in common, and values typed in from a description or a
paper. All of it is in a recipe.

```
data/                        upstream: raw unpacked HEPData, by sqrt(s)/class/observable
hepdata_database.yaml        upstream
curated/                     generated, never edited: the product others read
  raa/PbPb5020/raa__PbPb5020__CMS__charged__0-5.yaml
recipes/                     hand-written, one per record: ins1496050.yaml
manual/                      hand-typed datasets with no HEPData record (validated, never generated)
aliases.yaml                 raw error labels, x names and units -> common names
centrality_definitions.yaml  what each experiment ranked events by
observables.yaml             the observables, the fields they take, the spectrum conventions
inspire.yaml                 INSPIRE keys of the pinned records (filled by `hsdc fill-inspire`)
schema/dataset.schema.json   generated from the three files above
tools/hsdc/                  the package: build, validate, reader
tests/
```

```sh
pip install -e .                  # PyYAML and jsonschema; pandas for the tidy tables
python3 -m hsdc build             # recipes -> curated/ (byte-identical on a rebuild)
python3 -m hsdc build --check     # fail if curated/ is not what the recipes make
python3 -m hsdc validate          # every file in curated/ and manual/ against the schema
python3 -m pytest                 # the tools, and every curated number against the raw files
```

## A dataset file

One file per dataset, where a dataset is one curve: one observable, one class, one
selection. It is one column of a HEPData table with the vocabulary fixed.

```yaml
format_version: 1
key: raa__PbPb5020__CMS__charged__0-5
observable: raa
system: PbPb
sqrt_s_nn: 5020
experiment: CMS
particle: charged
centrality: [0, 5]
centrality_definition: CMS_HF_ENERGY      # a name in centrality_definitions.yaml
acceptance: { eta_range: [-1.0, 1.0] }
source:
  hepdata: { inspire_id: 1496050, version: 2, table: Table 8, column: 0, location: ..., doi: ... }
  paper: "arXiv:1611.01664"
  inspireHEPKey: "CMS:2016xef"
note: "free text about the dataset as a whole"
x: { name: pt, units: GeV }
y: { name: raa }
errors:
  stat: { label: stat }
  sys: { label: sys }
  taa: { label: "sys,TAA", note: "what the paper says about this source" }
  lumi: { label: "sys,lumi" }
bins:
  - { low: 0.7, high: 0.8, value: 0.312275,
      errors: { stat: 1.9e-05, sys: 0.024457, taa: [-0.009368, 0.00562], lumi: 0.007182 } }
```

Rules:

- **Numbers are copied verbatim**, with the digits HEPData has, so a regenerated file only
  changes when the data does. A value HEPData gives as a string (`'1.4166e-03'`) is read as
  the number it is.
- **Signs are kept as published.** A number is a symmetric error, `[minus, plus]` an
  asymmetric one, both exactly as HEPData stores them. Some records give signed per-source
  shifts (ALICE jet substructure has negative symmetric errors; CMS gamma-jet has both
  sides negative), which carry the direction of a correlated shift. What a sign means is
  an analysis question.
- **Percent errors become absolute**, `|value| * percent / 100` with the percent's own
  sign, rounded to 12 significant digits, and the source gets `percent: true`.
- **Placeholders** (`''`, `--`, NaN) become `null`, so the point can still be plotted.
- **Each point has edges, a position, or both**: `low` and `high` for a bin, `centre` for a
  position (HEPData's `value`). The same form for every point of a dataset; bins increase
  and do not overlap.
- **Ranges are `[lo, hi]`**, never `|eta| < x`: `eta_range: [-1.0, 1.0]`, `y_range`,
  `pt_range`. A window `lo < |eta| < hi` with `lo > 0` is two windows, so it is
  `abs_eta_range: [lo, hi]`. An eta gap is `delta_eta_gap`. HEPData's `location` ("Data from
  Fig. 3 Top Left Panel") is kept under `source.hepdata`.
- **Minimum bias is a class like any other**: `centrality: [0, 100]` with a definition that
  says how the sample was selected (`CMS_OO_MINIMUM_BIAS`), since 0-100% means different
  things in O+O and p+Pb.

### Where free text goes

`note` at the top is about the dataset as a whole: a caveat, how the pp reference was
obtained, which other datasets it overlaps. `errors.<name>.note` is about one source: what
the paper says about it. Both are written in the recipe and copied into the file. They are
never read by code, so they are written for the person reading the file: only what the
HEPData description says, or what was read in the paper and cited by arXiv number.

### Where an error source came from

`errors.<name>` carries one of:

| Field | Meaning |
|---|---|
| `label: "<raw>"` | from the HEPData table, under that label (`""` if it had none) |
| `origin: description` | typed in from the HEPData table description |
| `origin: paper`, `reference: "Sec. 7"` | typed in from the paper, not on HEPData |
| `origin: manual`, `entered_by: <name>` | from a collaborator or digitised |

A typed-in source also has `relative` (a fraction of the value, a number or `[minus, plus]`),
or one number per bin; see Recipes.

## Keys

`{observable}__{system}{sqrt_s}__{experiment}__{particle}__{class}`, where class is
`lo-hi`; pp datasets have none. The fields the observable's `distinguish` list names follow,
in that order: `vn__PbPb5020__CMS__charged__0-5__SP__n2__gap3`. Fields are separated by
`__`, so field values may contain `_` but never `__`. The key is an identifier: code reads
the metadata fields and never splits the key.

If two datasets would get the same key the build fails. A free `variant` token (letters,
digits, `.` and `-`) tells apart datasets that differ only in an acceptance window, such as
`abseta0.5-1`; the widest or default window has none.

## Vocabulary

**`aliases.yaml`** maps every raw spelling to a common name, once, for all records, in three
sections: `errors` (`taa: ["sys,TAA", "syst, TAA", "sys,TpA"]`), `x` (`pt: ["PT", "$p_{T}$"]`)
and `units`. An unknown spelling fails the build and names the record, so it is added once
and every later record benefits. A recipe can name a source for one record where a label
means something else there. Common names are what an analysis config refers to ("all `taa`
sources").

**`centrality_definitions.yaml`** says what the experiment ranked events by, with the paper
it comes from. A dataset naming an entry that does not exist fails the build. The model
ranks events by a `[Centrality.<NAME>]` block, and the analysis config maps definition to
block, so which model estimator stands in for which experimental one is written down once.

**`observables.yaml`** has one entry per observable, and a `fields` catalogue they draw
from. Adding an observable is adding an entry; the schema is generated from it.

| Observable | Quantity | `final` (CapeTownEloss) |
|---|---|---|
| `raa` | nuclear modification factor, including R_pPb | `HADRON_RAA` |
| `rcp` | central-to-peripheral ratio; `reference_centrality` is the denominator class | `HADRON_RAA` with `reference` |
| `vn` | flow harmonic `harmonic` by `method` (SP, EP, 2PC, cumulant2, cumulant4, ...) | `HADRON_VN_SP` for SP only |
| `pp_cross_section` | the pp reference spectrum | `HADRON_CROSS_SECTION` for the cross-section conventions |

`y.definition` of a spectrum is one of twelve conventions, with `y.units` as published:
`CROSS_SECTION_DPT_DETA`, `CROSS_SECTION_DPT_DY`, `INVARIANT_CROSS_SECTION_DETA` and
`INVARIANT_CROSS_SECTION_DY` (1/(2 pi pT) of either); the same four per event
(`YIELD_DPT_DETA`, ..., `INVARIANT_YIELD_DY`); and per event over <T_AA> or <T_pA>
(`YIELD_PER_TAA_*`, `INVARIANT_YIELD_PER_TAA_*`). Values are never rescaled in curation.

## Recipes

One per record, hand-written, the only place judgement is recorded. Fields set at the top
apply to every dataset; a dataset entry overrides them (`acceptance` merges key by key; a
field set to `null` drops the default).

```yaml
record: { inspire_id: 1496050, version: 2 }     # the pin; `hsdc build --update` moves it
paper: "arXiv:1611.01664"
experiment: CMS
particle: charged
sqrt_s_nn: 5020
acceptance: { eta_range: [-1.0, 1.0] }
datasets:
  - { table: Table 8, observable: raa, system: PbPb, centrality: [0, 5], centrality_definition: CMS_HF_ENERGY }
  - table: Table 14                              # overlaps 0-5 and 5-10: say so
    ...
    note: "Overlaps the 0-5% and 5-10% datasets of this record."
errors:                                          # notes, and a source's label for this record
  lumi: { note: "..." }
additional:                                      # sources not in the table
  norm:
    - origin: description
      for: { table: Table 8 }                    # which datasets (any dataset field, or table)
      relative: { "0-5": [-0.027, 0.027] }       # per class; a number or [minus, plus]
```

Every table that may be compared to is listed, overlapping classes included. `additional`
values are never edited into generated files: they are written in the recipe, and the build
adds them to the dataset marked with their origin. A paper value never replaces a source
that HEPData has: if the two disagree both are kept, under different names. `origin:
description` values are checked: the number must be on a line of the table's description
that names the dataset's class (or contains `sample: "P-PB NSD"` for a minimum-bias
sample).

## The build

The build only checks the format, never the physics:

- every raw label has an alias;
- every point has edges or a centre, one form per dataset, increasing and not overlapping;
- every `centrality_definition` exists, and belongs to the dataset's experiment;
- a centrality qualifier in the table, where there is one, matches the recipe (and the
  classes of a ratio qualifier `0-5%/50-90%` match `centrality` and `reference_centrality`);
- a value typed in from a description is on the line naming its class;
- the key is unique;
- the result passes the schema.

It warns when the table's eta window disagrees with the recipe's `eta_range`. The tests
check the other direction: `tests/test_curated.py` rebuilds everything and compares it to
`curated/` byte for byte, and re-reads every curated number from the raw files by a second
route.

| Command | Does |
|---|---|
| `hsdc build` | applies the recipes, writes `curated/` and the schema; removes files no recipe makes |
| `hsdc build --recipe R` | builds one recipe and removes nothing |
| `hsdc build --check` | builds in memory and compares; exit 1 on any difference |
| `hsdc build --update` | moves every pin to the newest HEPData version, downloads it next to the old one, rebuilds; the diff is then reviewed |
| `hsdc validate [files]` | schema and format checks on `curated/` and `manual/` |
| `hsdc tables ID VERSION [TABLE...]` | lists a record's tables, columns, qualifiers and error labels |
| `hsdc check-updates` | reports records with a newer HEPData version than pinned |
| `hsdc fetch ID VERSION data/<sqrt_s>/<class>/<observable>` | downloads and unpacks one record |
| `hsdc fill-inspire` | fetches the INSPIRE keys into `inspire.yaml` |

Only `check-updates`, `build --update`, `fetch` and `fill-inspire` use the network, so a build
is reproducible offline. `manual/` files are validated, never generated.

## Adding a record

1. `hsdc fetch <id> <version> data/...` (or copy an unpacked record in), then
   `hsdc tables <id> <version>` to see its tables.
2. Write `recipes/ins<id>.yaml`: the tables you want, and for each its observable, system,
   energy, class, acceptance and centrality definition. New raw labels go in `aliases.yaml`,
   a new centrality estimator in `centrality_definitions.yaml` with its paper.
3. `hsdc build --recipe recipes/ins<id>.yaml` and fix what it reports. Treat every warning
   as something to fix or explain.
4. `hsdc build` and `python3 -m pytest`.

## Reading

```python
from hsdc import read_datasets, tidy, tidy_errors

datasets = read_datasets(observable="raa", system="PbPb", sqrt_s_nn=5020, centrality=[0, 5])
points = tidy(datasets)           # one row per bin
sources = tidy_errors(datasets)   # one row per bin and error source, as published
```

Filters match any field; a list means "any of". The repository is found from `HSDC_ROOT`, the
current directory, or the package's own checkout.

## Not here

- Correlation models, symmetrising, signed-error interpretation, overlap exclusion, pT cuts:
  the analysis config.
- Derived data, such as an R_AA computed from published spectra.
- Published correlation matrices: added as a sidecar file when the first record with one is
  curated. Today only jet records have them, all statistical (ATLAS jet R_CP 2.76 TeV,
  ATLAS jet spectra 5.02 TeV, CMS gamma-jet girth/R_g with data and MC matrices).
