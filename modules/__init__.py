"""DEPORT modules: data loading, parsing, impact, risk, recommendations and visuals."""
import pandas as pd

# pandas 3 reads an empty text value (e.g. the ETA of an unassigned order) as NaN, which counts as "true" in
# `if eta:` checks; pandas 2 reads it as None. The app is built on None, so keep that on every pandas version.
pd.set_option("future.infer_string", False)
