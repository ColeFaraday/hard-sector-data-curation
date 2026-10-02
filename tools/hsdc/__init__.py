"""Curated experimental datasets: build them from HEPData records, and read them.

The reader is importable without the build tools' dependencies beyond PyYAML:

    from hsdc import read_datasets, tidy
"""

from .reader import (
    Bin,
    Dataset,
    FormatError,
    dataset_files,
    final_kind,
    find_root,
    read_dataset,
    read_datasets,
    tidy,
    tidy_errors,
)

__all__ = [
    "Bin",
    "Dataset",
    "FormatError",
    "dataset_files",
    "final_kind",
    "find_root",
    "read_dataset",
    "read_datasets",
    "tidy",
    "tidy_errors",
]
