---
name: sbse-bench
description: Runs the Second Brain Search Engine Benchmark (SBSE-Bench) on a specified engine (e.g., QMD) by querying the engine, answering questions in isolation via clean subagents, and grading the answers.
---

# Second Brain Search Engine Benchmark (SBSE-Bench) Skill

이 스킬은 사용자의 비정형 메모 뭉치(세컨드 브레인)를 다루는 검색 엔진(예: QMD)의 성능을
격리된 AI 에이전트 파이프라인을 통해 평가합니다.

사용자가 `/sbse-bench <엔진이름>` 명령을 입력하거나 특정 엔진에 대한 벤치마크 수행을
요청하면 이 스킬이 실행됩니다.

---

## 🔒 격리 원칙 (Isolation Invariants) — 모든 에이전트 공통

본 벤치마크는 **답변 작성용 LLM**과 **채점용 LLM**을 격리하여, 순수한 검색 엔진의
성능만 측정합니다. 아래 규칙은 어떤 에이전트에서든 반드시 지켜야 합니다.

1. **마커 사이 텍스트만 사용**: stdout 에 나타나는 `=== SUBAGENT_PROMPT_START ===` 와
   `=== SUBAGENT_PROMPT_END ===` **사이의 텍스트만** 서브에이전트에 전달합니다.
2. **누수 금지**: 벤치마크 파일 경로, `second_brain/` 위치, 원본 마크다운 파일 목록,
   질문 ID, 정답(ground truth), 이 대화가 벤치마크라는 사실을 서브에이전트에 **절대
   포함하지 않습니다.** 서브에이전트에게 "로컬 경로/파일 위치를 추측해 적지 말라"고
   명시하세요. (평가기도 컨텍스트의 절대경로/file:// URI 를 자동 마스킹하지만,
   오케스트레이터 단에서 한 번 더 차단합니다.)
3. **추가 조회 금지**: 답변 서브에이전트는 주어진 컨텍스트 외에 어떤 파일도 열거나
   검색하지 않습니다.
4. **출력 그대로 전달**: 서브에이전트의 출력 텍스트를 가공 없이 평가기 stdin 으로
   전달합니다(채점은 JSON 그대로).

---

## 🚀 0단계: 어댑터 부트스트랩 (Adapter Bootstrap)

이 벤치마크는 **엔진-agnostic** 입니다. 평가는 `engines/<엔진이름>/search.py` 라는
**고정된(pinned) 검색 호출**을 통해 이루어집니다. 사용자가 이 파일을 손으로 짤
필요는 없으며, **에이전트가 엔진 인자를 받아 1회 자동 생성**합니다. 단, 생성 후에는
그 파일을 그대로 재사용하여 실행이 결정론적·재현 가능하도록 유지합니다.

`/sbse-bench <엔진이름>` 을 받으면 다음을 수행합니다.

1. **기존 어댑터 확인**: `engines/<엔진이름>/search.py` 가 이미 있으면 **그대로 사용**
   합니다(절대 매 실행마다 새로 만들지 않음 — 고정이 핵심).
2. **없으면 조사(Investigate)**: 엔진의 구동 방식을 파악합니다. 예:
   `which <엔진>`, `<엔진> --help`, `<엔진> query --help`, `npm info`/`pip show`,
   README, MCP 서버 스펙 등. (CLI·라이브러리·MCP·API 어떤 형태든 가능.)
3. **어댑터 생성(Generate)**: 조사 결과를 바탕으로 `engines/<엔진이름>/search.py` 를
   `engines/README.md` 규약에 맞게 작성합니다. 반드시:
   * 질의를 `argv[1]` 로 받아 **검색된 컨텍스트를 stdout** 으로 출력.
   * **결정론 고정**: top-N·정렬·온도 등 검색 파라미터를 코드에 하드코딩하거나
     환경변수 기본값으로 고정. 실행마다 달라지는 무작위 요소를 넣지 않음.
   * 출력에 **원본 문서명/제목 포함**(검색 재현율 측정용), 로컬 절대경로/`file://`
     **출력 금지**.
4. **검증 + 사용자 확인**: 임의 질의로 한 번 실행해(`python3 engines/<엔진>/search.py "테스트"`)
   stdout 에 컨텍스트가 나오는지 확인하고, 생성한 어댑터 내용을 사용자에게 간단히
   보여준 뒤 진행합니다. (사용자가 직접 작성하고 싶다면 `engines/README.md` 규약을 안내.)
5. **색인**: 평가할 엔진에 `second_brain/` 를 색인합니다(엔진별 방식 상이).

> 왜 매번 에이전트가 직접 검색하지 않고 어댑터로 고정하나? 결정론적 일관성(Stability)
> 축과 검색 재현율 지표는 검색 호출이 **실행 간 동일**해야 성립합니다. 매번 즉흥적으로
> 질의하면 측정 대상이 '엔진'이 아니라 '에이전트의 변덕'이 되어 벤치마크가 무의미해집니다.

---

## 🛠️ 에이전트별 구동 (Execution by Agent)

위 0단계로 어댑터와 색인이 준비되면, 아래 에이전트별 흐름으로 평가기를 구동합니다.

### Case A / Case B 공통 — 프롬프트 블록 식별
평가기 stdout 에 마커 블록이 나타납니다.
* 블록 첫 줄이 `[답변 지시사항]` → **Case A (답변 생성)**: `QA Reader Assistant` 역할로
  격리 서브에이전트를 띄워 답변을 생성합니다.
* 블록 첫 줄이 `[채점 지시사항]` → **Case B (채점)**: `Benchmark Grader` 역할로 격리
  서브에이전트를 띄워 `{"score": .., "reason": ".."}` JSON 을 생성합니다.
두 경우 모두 결과 텍스트를 실행 중인 평가기 태스크의 stdin 으로 전달합니다.

### 🔹 Antigravity / Gemini CLI
```bash
python3 evaluator.py --engine <엔진이름> --interactive-agent
# 산출물은 engines/<엔진이름>/ 아래로: report.md, report.results.json, answers.json, contexts.json
```
* 서브에이전트: **TypeName `self`** 로 호출, Prompt = 마커 사이 텍스트.
* 입력 전달: `manage_task` → `send_input` 로 평가기 태스크에 결과 전달.

### 🔹 Claude Code (Anthropic)
Claude Code 는 `Task` 도구로 격리 서브에이전트를 띄웁니다. `self`/`manage_task` 같은
도구는 없으므로 아래 흐름을 사용하세요.
```bash
python3 evaluator.py --engine <엔진이름> --interactive-agent
# 산출물은 engines/<엔진이름>/ 아래로: report.md, report.results.json, answers.json, contexts.json
```
* 평가기를 **백그라운드 Bash**(`run_in_background: true`)로 실행하고 `BashOutput` 으로
  마커 블록을 폴링합니다.
* 블록을 감지하면 `Task`(subagent_type: `general-purpose`)로 **마커 사이 텍스트만**
  넘겨 격리 답변/채점을 받습니다.
* 받은 텍스트는 백그라운드 프로세스의 stdin 으로 전달합니다.
* (API 키는 사용하지 않습니다. 모든 답변/채점은 격리 서브에이전트로 수행합니다.
  stdin 중계가 어려운 환경이라면, `--interactive-agent` 없이 실행해 **수동 채점**으로
  대체할 수 있습니다.)

### 🔹 Codex / 기타 개발자 에이전트
* 위 Claude Code 흐름과 동일한 원칙(격리 서브에이전트 + stdin 전달)을 각 프레임워크의
  서브에이전트/프로세스 도구로 구현합니다. 마커 사이 텍스트 외에는 어떤 메타데이터도
  넣지 않습니다.

---

## 📈 결과 해석 및 재현
평가가 끝나면 평가기는 한 폴더에 모든 산출물을 생성합니다:
`engines/<엔진>/report.md`(보고서), `engines/<엔진>/report.results.json`(채점 캐시),
`answers.json`, `contexts.json`.
1. 생성된 보고서 링크를 제시하고, 터미널 요약(헤드라인 평균 점수, 영역별 달성도,
   평균 검색 재현율)을 사용자에게 브리핑합니다.
2. **헤드라인 점수는 stability-runs 평균**이며 표본이 작으므로 소수점 차이는 노이즈로
   설명합니다. 점수 손실의 책임 소재는 "검색 재현율 분석" 표(검색 vs 생성)로 짚어줍니다.
3. LLM 없이 보고서만 다시 만들려면:
   `python3 evaluator.py --from-results engines/<엔진>/report.results.json`
4. **무검색(full-context) 베이스라인**: 검색엔진 없이 전체 폴더를 그대로 답변 에이전트에
   주는 경우의 성능을 보려면 `engines/no-engine/` 어댑터를 사용합니다. 단 이 점수는 검색
   엔진이 아니라 **답변 agent-model 의 읽기·추론 능력**을 재므로, 모델별로 다릅니다.
   따라서 모델마다 별도 엔진 폴더로 등록하세요(예: `engines/agy-gemini-3.5-pro-medium/`).
   자세한 규약은 `engines/no-engine/README.md` 참고.
