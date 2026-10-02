Datasets with no HEPData record, typed in from a paper or sent by a collaboration.

They have the same format as the files in `curated/` (see `../docs/format.md`) and are
validated by `python3 -m hsdc validate`, but never generated, so they are edited by hand. A
value taken from a paper carries `origin: paper` and a `reference`; one from a collaborator
carries `origin: manual` and `entered_by`.
