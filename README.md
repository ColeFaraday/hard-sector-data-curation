# Hard-sector data curation

Collection of hard-sector HEPData files. For use with jetscape-analysis (among other projects).

It's separated into a new repository since the multitude of (yaml) files per analysis mean that
the history of this project will get rather messy. So better to factor into another repo where
it's easier to control/clean the history as needed.


## Curated datasets (this fork)

On top of the raw records, this fork keeps a curated layer: one plain-text YAML file per
measured curve in `curated/`, in one format whatever the experiment called its columns and
errors. It is generated from the raw records by hand-written recipes in `recipes/`, copies
HEPData's numbers and signs verbatim, and makes no physics judgement: how to symmetrise an
error, how sources correlate and which overlapping classes to drop are left to the analysis.
Everything a recipe decides is written down in it, and `pytest` checks every curated number
against the raw file.

```python
from hsdc import read_datasets, tidy
datasets = read_datasets(observable="raa", system="PbPb", sqrt_s_nn=5020)
```

Charged-hadron R_AA, R_CP, v_n and the pp reference are curated so far. The format, the
vocabulary files and how to add a record are in [docs/format.md](docs/format.md).
`pip install -e .` installs the package `hsdc` (needs PyYAML and jsonschema).
