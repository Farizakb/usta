# M1 proof, 2026-10-13

SPEC §16 M1: a T-c-style task on a real model ends `done` and verified, and its xlsx and PDF pass the checks.

**Result: passed on the first attempt with a valid key.** The `dev-api` fallback was not needed.

| | |
|---|---|
| Run | `deafd444-ac76-4b54-b320-38bd81dcaac2` |
| Profile / engine | `dev-openai` (`openai/gpt-6-luna` through LiteLLM) / `own` |
| Sandbox runtime | `runsc-kvm` (gVisor) |
| Status | `finished`, stop reason `done` |
| Turns | 13 |
| Model calls | 14: 13 agent turns plus 1 verifier LLM judge (prompt `verify-f85738994f19`, verdict `pass`). All on attempt 1, 0 errors. |
| Tokens | 7,805 input, 50,099 cache read, 2,734 output |
| Cost | **$0.0026** (prices from `config/models.toml`) |
| Wall time | 60.6 s (43.8 s of it in model calls) |
| Tool calls | 15 calls (30 rows: one `intent` and one `done` row each): `todo`, `skill.load` ×2 (`xlsx`, `pdf-report`), `code_exec` ×2, `todo`, `code_exec` ×3, `todo`, `code_exec` ×4, `todo` |
| Tool errors | 2 `code_exec` calls hit `NameError: name 'y' is not defined`. The model assumed interpreter state carried over between calls, but state lives only in files (ADR-024). It recovered on the next turn by recomputing. |
| Output | `out/uygunsuzluqlar.xlsx` (5,262 B) and `out/uygunsuzluqlar_hesabati.pdf` (45,847 B, 1 page) |
| Verification | `✓ verified`: both files' `check.py` returned ok, and the judge passed |
| T-c checker | `T-c check passed` (5 mismatches, matching the fixture ground truth) |

PDF glyphs: the text layer contains `ə ğ ı ş`, and a 80 dpi render of page 1 shows them correctly with no missing-glyph boxes. `İ` does not occur in this report's text, so this run does not exercise it. It is covered by the pdf-report skill tests (`tests/skills/test_pdf_charts.py`).

Command: `scripts/m1_proof.sh dev-openai` (loads `.env` without printing it; `USTA_GVISOR_RUNTIME=runsc-kvm`).

## Earlier attempts

1. **Run `60e3dc7a`, `dev-openai`:** `ProviderError` 401 `expired_secret_key` on the first call. 0 turns, $0. The key was renewed, then a `/v1/models` request returned 200.
2. **`dev-api` fallback:** startup refused (`ANTHROPIC_API_KEY` not set). No run was created, $0.
3. **2026-10-13, first try with the renewed key:** the CLI did not start. An uncommitted stray character in `usta/core/messages.py` caused an `IndentationError` at import. It was removed (the file matches HEAD again), and there was no model spend.

## CLI transcript

LiteLLM printed its "Provider List" help banner 72 times on stderr; its own cost lookup does not know the model. That noise and blank lines are removed. Nothing else is cut, and the transcript holds no secrets.

```
▶ run deafd444-ac76-4b54-b320-38bd81dcaac2
[turn 1] gpt-6-luna · tool_use · $0.0002
  → todo {"items": [{"content": "Excel fayllarının quruluşunu yoxlamaq və məlumatları müqayisə etmək", "status": "in_progress"}, {"content": "Uyğunsuzluqlar cədvəlini Excel faylına yazmaq", "status": "pending"}, {"content": "Nəticələri PDF hesabatına hazırlamaq və yoxlamaq", "status": "pending"}]}
  ☐ [in_progress] Excel fayllarının quruluşunu yoxlamaq və məlumatları müqayisə etmək | [pending] Uyğunsuzluqlar cədvəlini Excel faylına yazmaq | [pending] Nəticələri PDF hesabatına hazırlamaq və yoxlamaq
  ← todo: ok (196 chars)
  · $0.0002 so far
[turn 2] gpt-6-luna · tool_use · $0.0001
  → skill.load {"name": "xlsx"}
  ← skill.load: ok (1011 chars)
  → skill.load {"name": "pdf-report"}
  ← skill.load: ok (1435 chars)
  → code_exec {"code": "import os\nfrom openpyxl import load_workbook\nfor f in ['/workspace/cihazlar.xlsx','/workspace/anbar_qaliqlari.xlsx']:\n print('\\nFILE',f,os.path.exists(f))\n if os.path.exists(f):\n  wb=load_workbook(f,data_only=True,read_only=True)\n  for ws in wb.worksheets:\n   print('SHEET',ws.title,ws.max_row,ws.max_column)\n   for row in ws.iter_rows(min_row=1,max_row=min(ws.max_row,8),values_only=True): print(row)\n"}
  ← code_exec: ok (865 chars)
  · $0.0003 so far
[turn 3] gpt-6-luna · tool_use · $0.0002
  → code_exec {"code": "import pandas as pd\nfor f in ['cihazlar.xlsx','anbar_qaliqlari.xlsx']:\n d=pd.read_excel('/workspace/'+f)\n print('\\n',f,d.columns.tolist(),d.shape)\n print(d.to_string(index=False))"}
  ← code_exec: ok (2878 chars)
  · $0.0005 so far
[turn 4] gpt-6-luna · tool_use · $0.0002
  → todo {"items": [{"content": "Excel fayllarının quruluşunu yoxlamaq və məlumatları müqayisə etmək", "status": "done"}, {"content": "Uyğunsuzluqlar cədvəlini Excel faylına yazmaq", "status": "in_progress"}, {"content": "Nəticələri PDF hesabatına hazırlamaq və yoxlamaq", "status": "pending"}]}
  ☐ [done] Excel fayllarının quruluşunu yoxlamaq və məlumatları müqayisə etmək | [in_progress] Uyğunsuzluqlar cədvəlini Excel faylına yazmaq | [pending] Nəticələri PDF hesabatına hazırlamaq və yoxlamaq
  ← todo: ok (193 chars)
  · $0.0007 so far
[turn 5] gpt-6-luna · tool_use · $0.0002
  → code_exec {"code": "import pandas as pd\nc=pd.read_excel('/workspace/cihazlar.xlsx')\nq=pd.read_excel('/workspace/anbar_qaliqlari.xlsx')\na=c.groupby(['Anbar','Model']).size().rename('Cihaz siyahısı').reset_index()\nx=q.merge(a,on=['Anbar','Model'],how='outer')\nx['Qalıq']=x['Qalıq'].fillna(0).astype(int); x['Cihaz siyahısı']=x['Cihaz siyahısı'].fillna(0).astype(int)\nx['Fərq (siyahı − qalıq)']=x['Cihaz siyahısı']-x['Qalıq']\ny=x[x['Fərq (siyahı − qalıq)']!=0].sort_values(['Anbar','Model'])\nprint(y.to_string(index=False)); print('total mismatch rows',len(y),'total devices',len(c),'sum stock',q.Qalıq.sum())\n"}
  ← code_exec: ok (511 chars)
  · $0.0008 so far
[turn 6] gpt-6-luna · tool_use · $0.0002
  → code_exec {"code": "import sys\nsys.path.insert(0,'/skills/xlsx/scripts')\nfrom usta_xlsx import write_xlsx\nrows=[['Anbar','Model','Cihaz siyahısında (ədəd)','Anbar qalığı (ədəd)','Fərq (siyahı − qalıq)']]\nfor _,r in y.iterrows(): rows.append([r['Anbar'],r['Model'],int(r['Cihaz siyahısı']),int(r['Qalıq']),int(r['Fərq (siyahı − qalıq)'])])\nwrite_xlsx('/out/uygunsuzluqlar.xlsx',{'Uyğunsuzluqlar':rows})\nprint('saved rows',len(rows)-1)"}
  ← code_exec: error (129 chars)
  · $0.0010 so far
[turn 7] gpt-6-luna · tool_use · $0.0002
  → code_exec {"code": "import pandas as pd,sys\nsys.path.insert(0,'/skills/xlsx/scripts')\nfrom usta_xlsx import write_xlsx\nc=pd.read_excel('/workspace/cihazlar.xlsx'); q=pd.read_excel('/workspace/anbar_qaliqlari.xlsx')\na=c.groupby(['Anbar','Model']).size().rename('Cihaz siyahısı').reset_index()\nx=q.merge(a,on=['Anbar','Model'],how='outer')\nx['Qalıq']=x['Qalıq'].fillna(0).astype(int); x['Cihaz siyahısı']=x['Cihaz siyahısı'].fillna(0).astype(int)\nx['Fərq (siyahı − qalıq)']=x['Cihaz siyahısı']-x['Qalıq']\ny=x[x['Fərq (siyahı − qalıq)']!=0].sort_values(['Anbar','Model'])\nrows=[['Anbar','Model','Cihaz siyahısında (ədəd)','Anbar qalığı (ədəd)','Fərq (siyahı − qalıq)']]\nfor _,r in y.iterrows(): rows.append([r['Anbar'],r['Model'],int(r['Cihaz siyahısı']),int(r['Qalıq']),int(r['Fərq (siyahı − qalıq)'])])\nwrite_xlsx('/out/uygunsuzluqlar.xlsx',{'Uyğunsuzluqlar':rows})\nprint('saved',len(rows)-1)"}
  ← code_exec: ok (91 chars)
  · $0.0012 so far
[turn 8] gpt-6-luna · tool_use · $0.0001
  → todo {"items": [{"content": "Excel fayllarının quruluşunu yoxlamaq və məlumatları müqayisə etmək", "status": "done"}, {"content": "Uyğunsuzluqlar cədvəlini Excel faylına yazmaq", "status": "done"}, {"content": "Nəticələri PDF hesabatına hazırlamaq və yoxlamaq", "status": "in_progress"}]}
  ☐ [done] Excel fayllarının quruluşunu yoxlamaq və məlumatları müqayisə etmək | [done] Uyğunsuzluqlar cədvəlini Excel faylına yazmaq | [in_progress] Nəticələri PDF hesabatına hazırlamaq və yoxlamaq
  ← todo: ok (190 chars)
  · $0.0014 so far
[turn 9] gpt-6-luna · tool_use · $0.0003
  → code_exec {"code": "import sys\nsys.path.insert(0,'/skills/pdf-report/scripts')\nfrom usta_pdf import build_pdf, table\nrows=[['Anbar','Model','Siyahıda','Qalıq','Fərq']]\nfor _,r in y.iterrows(): rows.append([r['Anbar'],r['Model'],str(int(r['Cihaz siyahısı'])),str(int(r['Qalıq'])),f\"{int(r['Fərq (siyahı − qalıq)']):+d}\"])\n# Count over/under totals\nmore=int((y['Fərq (siyahı − qalıq)']>0).sum()); less=int((y['Fərq (siyahı − qalıq)']<0).sum())\nparts=[\n '## Xülasə',\n f\"Cihaz siyahısında {len(c)} cihaz qeydə alınıb. Anbar qalığı ilə Anbar və Model üzrə müqayisədə {len(y)} uyğunsuzluq aşkarlanıb: {more} mövqedə siyahı sayı qalıqdan çox, {less} mövqedə isə azdır.\",\n 'Fərq sütunu “cihaz siyahısındakı say − anbar qalığı” kimi hesablanıb. Müsbət fərq artıqlığı, mənfi fərq çatışmazlığı göstərir.',\n '## Uyğunsuzluqlar',\n table(rows),\n '## Qeyd',\n 'Müqayisə cihazların anbarda statusu olan siyahı üzrə, Anbar və Model kombinasiyasına əsasən aparılıb.'\n]\nbuild_pdf('/out/uygunsuzluqlar_hesabati.pdf','Cihaz siyahısı və anbar qalıqları üzrə uyğunsuzluqlar',parts)\nprint('created')"}
  ← code_exec: error (129 chars)
  · $0.0016 so far
[turn 10] gpt-6-luna · tool_use · $0.0004
  → code_exec {"code": "import pandas as pd,sys\nsys.path.insert(0,'/skills/pdf-report/scripts')\nfrom usta_pdf import build_pdf, table\nc=pd.read_excel('/workspace/cihazlar.xlsx'); q=pd.read_excel('/workspace/anbar_qaliqlari.xlsx')\na=c.groupby(['Anbar','Model']).size().rename('Cihaz siyahısı').reset_index()\nx=q.merge(a,on=['Anbar','Model'],how='outer')\nx['Qalıq']=x['Qalıq'].fillna(0).astype(int); x['Cihaz siyahısı']=x['Cihaz siyahısı'].fillna(0).astype(int)\nx['Fərq (siyahı − qalıq)']=x['Cihaz siyahısı']-x['Qalıq']\ny=x[x['Fərq (siyahı − qalıq)']!=0].sort_values(['Anbar','Model'])\nrows=[['Anbar','Model','Siyahıda','Qalıq','Fərq']]\nfor _,r in y.iterrows(): rows.append([r['Anbar'],r['Model'],str(int(r['Cihaz siyahısı'])),str(int(r['Qalıq'])),f\"{int(r['Fərq (siyahı − qalıq)']):+d}\"])\nmore=int((y['Fərq (siyahı − qalıq)']>0).sum()); less=int((y['Fərq (siyahı − qalıq)']<0).sum())\nparts=['## Xülasə',f\"Cihaz siyahısında {len(c)} cihaz qeydə alınıb. Anbar qalığı ilə Anbar və Model üzrə müqayisədə {len(y)} uyğunsuzluq aşkarlanıb: {more} mövqedə siyahı sayı qalıqdan çox, {less} mövqedə isə azdır.\",'Fərq sütunu “cihaz siyahısındakı say − anbar qalığı” kimi hesablanıb. Müsbət fərq artıqlığı, mənfi fərq çatışmazlığı göstərir.','## Uyğunsuzluqlar',table(rows),'## Qeyd','Müqayisə cihaz siyahısındakı qeydlər üzrə Anbar və Model kombinasiyasına əsasən aparılıb.']\nbuild_pdf('/out/uygunsuzluqlar_hesabati.pdf','Cihaz siyahısı və anbar qalıqları üzrə uyğunsuzluqlar',parts)\nprint('created mismatch',len(y))"}
  ← code_exec: ok (111 chars)
  · $0.0020 so far
[turn 11] gpt-6-luna · tool_use · $0.0002
  → code_exec {"code": "import subprocess,sys,os\nfor f in ['/out/uygunsuzluqlar.xlsx','/out/uygunsuzluqlar_hesabati.pdf']:\n print('\\n',f,os.path.getsize(f))\nscript='/skills/xlsx/check.py'\nr=subprocess.run([sys.executable,script,'/out/uygunsuzluqlar.xlsx'],capture_output=True,text=True)\nprint('xlsx verifier',r.returncode,r.stdout,r.stderr)"}
  ← code_exec: ok (379 chars)
  → code_exec {"code": "import subprocess,sys\nr=subprocess.run([sys.executable,'/skills/pdf-report/check.py','/out/uygunsuzluqlar_hesabati.pdf'],capture_output=True,text=True)\nprint('pdf verifier',r.returncode,r.stdout,r.stderr)"}
  ← code_exec: ok (752 chars)
  · $0.0022 so far
[turn 12] gpt-6-luna · tool_use · $0.0002
  → todo {"items": [{"content": "Excel fayllarının quruluşunu yoxlamaq və məlumatları müqayisə etmək", "status": "done"}, {"content": "Uyğunsuzluqlar cədvəlini Excel faylına yazmaq", "status": "done"}, {"content": "Nəticələri PDF hesabatına hazırlamaq və yoxlamaq", "status": "done"}]}
  ☐ [done] Excel fayllarının quruluşunu yoxlamaq və məlumatları müqayisə etmək | [done] Uyğunsuzluqlar cədvəlini Excel faylına yazmaq | [done] Nəticələri PDF hesabatına hazırlamaq və yoxlamaq
  ← todo: ok (183 chars)
  · $0.0024 so far
[turn 13] gpt-6-luna · end_turn · $0.0001
  ✓ verified
■ done · 13 turns · $0.0026
Müqayisə nəticəsində **5 uyğunsuzluq** aşkarlandı: 4 mövqedə cihaz siyahısındakı say qalıqdan çox, 1 mövqedə isə azdır.
- [Uyğunsuzluqlar cədvəli — Excel](out/uygunsuzluqlar.xlsx)
- [Uyğunsuzluqlar hesabatı — PDF](out/uygunsuzluqlar_hesabati.pdf)
total 64
drwxr-xr-x 2 farizakbarzada farizakbarzada  4096 Oct 13 10:20 .
drwxr-xr-x 3 farizakbarzada farizakbarzada  4096 Oct 13 10:20 ..
-rw-r--r-- 1 farizakbarzada farizakbarzada  5262 Oct 13 10:20 uygunsuzluqlar.xlsx
-rw-r--r-- 1 farizakbarzada farizakbarzada 45847 Oct 13 10:20 uygunsuzluqlar_hesabati.pdf
T-c check passed
run: deafd444-ac76-4b54-b320-38bd81dcaac2  truth: /tmp/tmp.88DJV52q4p/ground_truth.json
run exit: 0
```

## Sandbox escapes (T3a)

- Local, `runsc-kvm`, 2026-10-13 on 61e0b4b: `USTA_TEST_SANDBOX_RUNTIME=runsc-kvm uv run pytest -m sandbox -q`: **39 passed**, including every test in `tests/sandbox/test_escapes.py`.
- CI, `runsc` (systrap) on GitHub VMs: job `t3a` green on 61e0b4b and on f1a3865 (https://github.com/Farizakb/usta/actions/runs/38256976086).
- Default suite on 61e0b4b: `uv run pytest -q`: 335 passed.
