# ADR-030: English instructions + Azerbaijani examples + glossary   (resolves D-29)
Status: accepted
Date: 2026-10-07

## Context
Azerbaijani costs 1.6–2.7× English tokens on measured tokenizers (F4); Claude unmeasured.

## Options considered
A English only; B Azerbaijani instructions; C English + Azerbaijani style examples + glossary skill.

## Decision
C. 2–3 short Azerbaijani output samples in the cached prefix; tool and skill descriptions in English; `company-glossary` maps English → Azerbaijani terms. Reply language follows the user.

## Consequences
Deep dive C measures Claude token parity (count_tokens), A vs C on the Azerbaijani T2 subset, and drift rate.

## Revisit when
A vs C shows no quality difference (drop examples) or C still drifts.
