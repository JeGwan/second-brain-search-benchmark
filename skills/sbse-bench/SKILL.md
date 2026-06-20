---
name: sbse-bench
description: Runs the Second Brain Search Engine Benchmark (SBSE-Bench) on a specified engine (e.g., QMD) by querying the engine, answering questions in isolation via clean subagents, and grading the answers.
---

# Second Brain Search Engine Benchmark (SBSE-Bench) Skill

이 스킬은 사용자의 비정형 메모 뭉치(세컨드 브레인)를 다루는 검색 엔진(예: QMD)의 성능을
격리된 AI 에이전트 파이프라인으로 평가합니다.

사용자가 `/sbse-bench <엔진이름>` 명령을 입력하거나 특정 엔진에 대한 벤치마크 수행을
요청하면 이 스킬이 실행됩니다.

> **설계**: 평가기(`evaluator.py`)는 결정론적인 일만 합니다 — 검색 실행, 프롬프트 생성,
> 검색 재현율 계산, 집계·보고서. **답변/채점처럼 '에이전트가 필요한' 일은 평가기가
> 직접 하지 않고**, 오케스트레이터(당신)가 격리 서브에이전트를 띄워 수행합니다. 둘은
> 단일 작업 파일 `engines/<엔진>/run.json` 으로 주고받습니다. (stdin 중계·마커 프로토콜 없음)

---

## 🔒 격리 원칙 (Isolation Invariants)

순수한 검색 엔진 성능만 측정하기 위해 **답변 서브에이전트**와 **채점 서브에이전트**를
격리합니다. 항상 지키세요.

1. **주어진 프롬프트만 전달**: 답변에는 `run.json` 의 `answer_prompt`, 채점에는
   `grade_prompt` **그 텍스트만** 서브에이전트에 넘깁니다.
2. **누수 금지**: 벤치마크 파일 경로, `second_brain/` 위치, 원본 파일 목록, 질문 ID,
   정답(ground truth), 이 작업이 벤치마크라는 사실, run.json 의 다른 항목을 답변
   서브에이전트에 **절대 포함하지 않습니다.** (채점 서브에이전트는 정답·루브릭을 봐도 됨.)
3. **추가 조회 금지**: 답변 서브에이전트는 주어진 컨텍스트 외에 어떤 파일/검색/웹도
   쓰지 않습니다. 서브에이전트에 "도구 사용 금지, 답변 텍스트만 출력"을 명시하세요.
4. **항목 간 분리**: 한 답변 서브에이전트는 **하나의 항목**만 봅니다(다른 질문/컨텍스트
   혼입 금지). 여러 항목은 별개의 서브에이전트로 병렬 처리합니다.

---

## 🚀 0단계: 어댑터 부트스트랩 (Adapter Bootstrap)

평가는 `engines/<엔진이름>/search.py` 라는 **고정된(pinned) 검색 호출**로 이루어집니다.
사용자가 손으로 짤 필요는 없으며 **에이전트가 1회 자동 생성**합니다.

1. `engines/<엔진이름>/search.py` 가 이미 있으면 **그대로 사용**(절대 매번 새로 만들지 않음).
2. 없으면 엔진 구동법을 조사: `which <엔진>`, `<엔진> --help`, `npm info`/`pip show`,
   README, MCP 스펙 등.
3. `engines/README.md` 규약에 맞게 `search.py` 생성: 질의를 `argv[1]` 로 받아 검색
   컨텍스트를 **stdout** 출력, top-N 등 파라미터 **고정**(무작위 요소 금지), 원본 문서명
   포함(재현율 측정용), 로컬 경로/`file://` 출력 금지.
4. 임의 질의로 한 번 실행해 확인하고, 생성한 어댑터를 사용자에게 간단히 보여줍니다.
5. 평가할 엔진에 `second_brain/` 를 색인합니다(엔진별 방식 상이).

> **무검색 베이스라인**(검색엔진 없이 모델만): `engines/no-engine/` 를 답변 모델 이름의
> 폴더로 복사해 사용합니다. 점수가 agent-model 종속이므로 모델별로 분리합니다.

---

## 🛠️ 평가 실행 (5단계 파이프라인)

### 1단계 — prepare (검색 + 프롬프트 생성)
```bash
python3 evaluator.py prepare --engine <엔진이름> --stability-runs 2 --answer-source "<답변 모델명>"
```
`engines/<엔진>/run.json` 이 생성됩니다. `items` 배열의 각 항목에는 `answer_prompt`,
`context`, `retrieval_recall` 이 채워지고 `answer`/`score` 는 비어 있습니다.
(`--stability-runs N`: 같은 질문을 N회 반복해 결정론적 일관성을 측정. 변형질문도 포함됨.)

### 2단계 — 격리 답변 (에이전트가 수행)
`run.json` 을 읽고, **각 항목마다 별개의 격리 서브에이전트**를 띄워 그 항목의
`answer_prompt` 로 답변을 받습니다(여러 항목 병렬 권장). 받은 답변 텍스트를 해당 항목의
`answer` 필드에 채워 `run.json` 을 저장합니다.

플랫폼별 서브에이전트:
* **Antigravity / Gemini CLI**: TypeName `self` 서브에이전트, Prompt = `answer_prompt`.
* **Claude Code**: `Task`(subagent_type: `general-purpose`), prompt = `answer_prompt`.
* **Codex / 기타**: 각 프레임워크의 격리 서브에이전트/프로세스.
공통: "도구 사용하지 말고 답변 텍스트만 출력"을 지시하고, `answer_prompt` 외 어떤
메타데이터도 넣지 않습니다.

### 3단계 — grade-prompts (채점 프롬프트 생성)
```bash
python3 evaluator.py grade-prompts --engine <엔진이름>
```
모든 항목의 `answer` 가 채워져 있어야 하며(아니면 거부됨), 각 항목에 컨텍스트를 포함한
`grade_prompt` 가 생성됩니다.

### 4단계 — 격리 채점 (에이전트가 수행)
각 항목마다 격리 채점 서브에이전트를 띄워 `grade_prompt` 로 채점합니다. 서브에이전트는
`{"score": 1|2|3, "reason": "..."}` JSON 을 반환합니다. 이를 파싱해 각 항목의 `score`(정수)
와 `reason`(문자열)에 채워 `run.json` 을 저장합니다. (여러 항목을 한 채점 서브에이전트가
배치로 처리해도 무방 — 답변 서브에이전트와 달리 채점은 정답을 봐도 됩니다.)

### 5단계 — assemble (집계 + 보고서)
```bash
python3 evaluator.py assemble --engine <엔진이름>
```
`engines/<엔진>/report.md` 와 `engines/<엔진>/report.results.json` 이 생성됩니다.

---

## 📈 결과 해석 및 재현
1. 생성된 `engines/<엔진>/report.md` 링크를 제시하고, 터미널 요약(헤드라인 평균 점수,
   영역별 달성도, 평균 검색 재현율)을 사용자에게 브리핑합니다.
2. **헤드라인 점수는 stability-runs 평균**이며 표본이 작으므로 소수점 차이는 노이즈로
   설명합니다. 점수 손실의 책임 소재는 "검색 재현율 분석" 표(검색 vs 생성)로 짚어줍니다.
   (재현율 100%인데 점수가 낮으면 검색은 성공했고 청크 커버리지/생성 측 문제.)
3. LLM 없이 보고서만 다시 만들려면:
   `python3 evaluator.py render engines/<엔진>/report.results.json`
