---
name: sbse-bench
description: Runs the Second Brain Search Engine Benchmark (SBSE-Bench) on a specified engine (e.g., QMD) — a deterministic, model-independent measurement of the search layer (key-fact coverage, document recall, semantic consistency).
---

# Second Brain Search Engine Benchmark (SBSE-Bench) Skill

이 스킬은 사용자의 비정형 메모 뭉치(세컨드 브레인)를 다루는 검색 엔진(예: QMD)의 성능을
**결정론적으로** 측정합니다. LLM 답변 생성·채점이 없으므로 모델·에이전트 환경에 관계없이
동일한 숫자가 나옵니다.

사용자가 `/sbse-bench <엔진이름>` 명령을 입력하거나 특정 엔진에 대한 벤치마크 수행을
요청하면 이 스킬이 실행됩니다.

> **설계**: 평가기(`evaluator.py`)는 검색을 실행하고 3개 결정론적 지표를 계산해 보고서를
> 만드는 일만 합니다. 핵심사실 커버리지(헤드라인), 문서 재현율, 의미론적 일관성을 직접
> 문자열 매칭으로 산출하므로 **에이전트의 LLM 추론·격리 서브에이전트·작업 파일 핸드오프가
> 전혀 필요 없습니다.** 에이전트는 오직 엔진별 `search.py` 어댑터를 처음 한 번 작성할
> 때만 쓰입니다.

---

## 🚀 0단계: 어댑터 부트스트랩 (Adapter Bootstrap)

측정은 `engines/<엔진이름>/search.py` 라는 **고정된(pinned) 검색 호출**로 이루어집니다.
사용자가 손으로 짤 필요는 없으며 **에이전트가 1회 자동 생성**합니다.

1. `engines/<엔진이름>/search.py` 가 이미 있으면 **그대로 사용**(절대 매번 새로 만들지 않음).
2. 없으면 엔진 구동법을 조사: `which <엔진>`, `<엔진> --help`, `npm info`/`pip show`,
   README, MCP 스펙 등.
3. `engines/README.md` 규약에 맞게 `search.py` 생성: 질의를 `argv[1]` 로 받아 검색
   컨텍스트를 **stdout** 출력, top-N 등 파라미터 **고정**(무작위 요소 금지), 원본 문서명
   포함(재현율 측정용), 로컬 경로/`file://` 출력 금지.
4. 임의 질의로 한 번 실행해 확인하고(스모크테스트), 생성한 어댑터를 사용자에게 간단히 보여줍니다.
5. 평가할 엔진에 `second_brain/` 를 색인합니다(엔진별 방식 상이).

> **데이터셋 자기검증**: `engines/no-engine/` 은 전체 문서를 그대로 반환하므로 핵심사실
> 커버리지가 100% 여야 정상입니다. 모델 베이스라인이 아니라 **질문지/알리아스 정의가
> 코퍼스와 일치하는지** 점검하는 셀프테스트입니다(`engines/no-engine/README.md` 참고).

---

## 🛠️ 측정 실행 (단일 명령)

어댑터가 준비되면 단 한 번 실행합니다.

```bash
python3 evaluator.py run --engine <엔진이름>
```

이 명령이 원 질의와 변형 질의로 검색을 실행하고, 3지표를 계산해
`engines/<엔진이름>/report.md` 와 `engines/<엔진이름>/report.results.json` 을 생성합니다.
별도의 단계·작업 파일·반복 실행은 없습니다(검색이 결정론적이라 매번 동일).

---

## 📈 결과 해석 및 재현
1. 생성된 `engines/<엔진>/report.md` 링크를 제시하고, 터미널 요약을 브리핑합니다:
   - **핵심사실 커버리지(헤드라인, 마이크로 평균)** — 주 점수.
   - **평균 문서 재현율** — 정답 근거 문서를 회수했는가.
   - **평균 의미론적 일관성** — 변형 질의에서도 같은 사실을 회수했는가.
2. 책임 소재 해석: 문서 재현율은 100% 인데 핵심사실 커버리지가 낮으면 **문서는 찾았으나
   청크 경계가 정답 줄을 놓친** 경우(청크 커버리지 문제)입니다.
3. LLM 없이 보고서만 다시 만들려면:
   `python3 evaluator.py render engines/<엔진>/report.results.json`
