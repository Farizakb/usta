---
name: charts
description: Draw bar and line charts as PNG with Azerbaijani-safe fonts, for reports or on their own.
---
# charts

Make charts inside `code_exec` with `/skills/charts/scripts/usta_charts.py` (matplotlib, DejaVu Sans,
150 dpi PNG).

```python
import sys
sys.path.insert(0, "/skills/charts/scripts")
from usta_charts import bar_chart, line_chart

bar_chart("/out/qrafik.png", ["Bakı", "Gəncə"], [12, 7], "Cihazlar", ylabel="Say")
line_chart("/out/trend.png", ["B.e", "Ç.a", "Ç"], {"FMB920": [3, 4, 6]}, "Həftəlik trend")
```

- Titles and labels in the user's language. One message per chart.
- To put a chart in a PDF, pass its path to `build_pdf` (pdf-report skill).
- The verifier runs `/skills/charts/check.py` on every PNG in `/out`. Blank or tiny images fail.
