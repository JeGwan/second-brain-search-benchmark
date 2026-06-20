# no-engine — 검색엔진 없이 순수 모델만 돌리는 베이스라인 (템플릿)

`no-engine` 어댑터는 쿼리를 무시하고 `second_brain/` 의 **모든 문서를 그대로 반환**합니다.
즉 "**검색 엔진을 쓰지 않고**, 답변 에이전트(모델)에게 폴더 전체를 그대로 넘겨 읽게 하는"
조건을 재현합니다. 검색 단계가 없으므로 검색 변수가 제거됩니다.

## ⚠️ 이 점수는 '검색 엔진'이 아니라 '답변 agent-model'을 측정합니다
컨텍스트가 항상 완전하므로, 여기서 나오는 점수는 검색 품질이 아니라 **답변을 작성하는
에이전트 모델의 읽기·추론 능력**을 반영합니다. 따라서 같은 `no-engine` 어댑터라도
**답변 모델이 다르면 점수가 다릅니다.** (이름을 `perfect`/오라클로 부르지 않는 이유:
'완벽한 정답'이 아니라 '검색 없이 모델만'의 베이스라인이기 때문입니다.)

### → 모델마다 별도 엔진으로 등록하세요
하나의 `no-engine` 항목으로 뭉뚱그리지 말고, 답변에 사용한 agent-model 을 식별자로 하는
**별도 엔진 폴더**를 만들어 결과를 분리 보관합니다. `no-engine/` 은 그 출발점이 되는
**어댑터 템플릿**입니다. 예:

```
engines/
├── no-engine/                     # 어댑터 템플릿(전체 문서 반환) — 복사해서 사용
├── agy-gemini-3.5-pro-medium/     # 무검색 베이스라인 @ Gemini 3.5 Pro (medium)
│   ├── search.py                  #   (no-engine/search.py 와 동일 — 전체 문서 반환)
│   ├── report.md
│   └── report.results.json
└── cc-opus-4.8/                    # 무검색 베이스라인 @ Claude Opus 4.8
    └── ...
```

등록 절차(예: Gemini 3.5 Pro, medium):
```bash
cp -r engines/no-engine engines/agy-gemini-3.5-pro-medium
# 해당 agent-model 로 평가를 구동 (답변 서브에이전트가 그 모델이어야 함)
python3 evaluator.py prepare --engine agy-gemini-3.5-pro-medium --answer-source "Gemini 3.5 Pro (medium)"
#   → (에이전트) 격리 답변/채점 서브에이전트 수행
python3 evaluator.py grade-prompts --engine agy-gemini-3.5-pro-medium
python3 evaluator.py assemble --engine agy-gemini-3.5-pro-medium
```
> 명명 규약(권장): `<agent>-<model>-<effort>` 형태로 답변 모델을 명확히 식별
> (예: `agy-gemini-3.5-pro-medium`, `cc-opus-4.8`, `codex-gpt-...`).

## 검색 실패 vs 생성 실패 분리 (보너스)
실제 검색 엔진(예: QMD)의 점수와 위 무검색 베이스라인을 대조하면, 각 문항의 점수 손실
책임이 **검색(랭킹)** 에 있는지 **생성/추론(모델)** 에 있는지 분리해 읽을 수 있습니다.
무검색 베이스라인이 만점이 아니라면 그 문항은 모델의 읽기/추론 한계이고, 검색 엔진에서만
점수가 깎이면 검색 단계 문제입니다. (`no-engine` 의 검색 재현율은 항상 100%.)
