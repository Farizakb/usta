---
name: xlsx
description: Read and write Excel workbooks (tables with headers, several sheets) in code_exec.
---
# xlsx

**Reading:** use pandas: `pd.read_excel("/workspace/cihazlar.xlsx", sheet_name=None)` gives every sheet.
Print `df.columns` and `df.head()` first; column names are often Azerbaijani (`Qalıq`, `Anbar`).
Strip spaces and compare text with `str.casefold()` only after replacing `İ→i`, `I→ı`.

**Writing:** use `/skills/xlsx/scripts/usta_xlsx.py`. It writes a bold, frozen header row and sets column widths.

```python
import sys
sys.path.insert(0, "/skills/xlsx/scripts")
from usta_xlsx import write_xlsx

write_xlsx("/out/uygunsuzluqlar.xlsx", {
    "Uyğunsuzluqlar": [["Anbar", "Model", "Siyahıda", "Qalıq", "Fərq"], ["Gəncə anbarı", "FMB920", 3, 1, -2]],
})
```

- The first row of each sheet is the header. Keep numbers as numbers (not strings).
- Sheet names: up to 31 characters; `[]:*?/\` are replaced.
- Write computed values, not formulas: compute in pandas, then write the numbers. The verifier cannot evaluate formulas, so any cell starting with `=` fails.
- The verifier runs `/skills/xlsx/check.py` on every `.xlsx` in `/out`. Empty workbooks, error values (`#REF!`, `#DIV/0!` ...) and formulas fail.
