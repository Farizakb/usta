# M0 smoke, 2026-10-09

Profile `dev-openai` (`openai/gpt-6-luna` through LiteLLM, effort `none`). Live test `pytest -m live tests/models/test_litellm_live.py`: 1 passed.

Command: `USTA_PROFILE=dev-openai uv run usta run "files/qeydler.txt faylını oxu, tapşırıqlardan todo siyahısı qur və qısa xülasə yaz."`

Note: LiteLLM printed a "Provider List" help banner several times per call on stderr (its cost lookup does not know the model); removed below as noise. Costs come from `config/models.toml`.

## CLI output

```
▶ run ed270f90-baf6-4cb6-a34b-31f1c1eea1da

[turn 1] gpt-6-luna · tool_use · $0.0001
  → file.read {"path": "files/qeydler.txt"}
  ← file.read: ok (103 chars)
  · $0.0001 so far

[turn 2] gpt-6-luna · tool_use · $0.0001
  → todo {"items": [{"content": "Yanacaq hesabatını yoxla", "status": "pending"}, {"content": "FMC130 qiymətini soruş", "status": "pending"}, {"content": "Müştəri şikayətinə cavab yaz", "status": "pending"}]}
  ☐ [pending] Yanacaq hesabatını yoxla | [pending] FMC130 qiymətini soruş | [pending] Müştəri şikayətinə cavab yaz
  ← todo: ok (106 chars)
  · $0.0001 so far

[turn 3] gpt-6-luna · end_turn · $0.0001
■ done · 3 turns · $0.0002

Todo siyahısı yaradıldı:

- [ ] Yanacaq hesabatını yoxla
- [ ] FMC130 qiymətini soruş
- [ ] Müştəri şikayətinə cavab yaz

Qısa xülasə: Həftəlik qeydlərdə yanacaq hesabatı, FMC130-un qiyməti və müştəri şikayətinə cavablandırma ilə bağlı üç tapşırıq var.
exit=0
```

## model_calls

```
model       | attempt | input_tokens | output_tokens |       cost_usd        | error 
-------------------+---------+--------------+---------------+-----------------------+-------
 openai/gpt-6-luna |       1 |          576 |            94 |             0.0001046 | 
 openai/gpt-6-luna |       1 |          469 |            62 | 7.790000000000001e-05 | 
 openai/gpt-6-luna |       1 |          393 |            22 |              5.03e-05 | 
(3 rows)

 count |          sum           
-------+------------------------
     3 | 0.00023280000000000002
(1 row)
```
