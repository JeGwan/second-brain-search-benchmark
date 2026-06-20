---
name: sbse-bench
description: Runs the Second Brain Search Engine Benchmark (SBSE-Bench) on a specified engine (e.g., QMD) by querying the engine, answering questions in isolation via clean subagents, and grading the answers.
---

# Second Brain Search Engine Benchmark (SBSE-Bench) Skill

이 스킬은 사용자의 비정형 메모 뭉치(세컨드 브레인)를 다루는 검색 엔진(예: QMD)의 성능을 격리된 AI 에이전트 파이프라인을 통해 평가합니다. 

사용자가 `/sbse-bench <엔진이름>` 명령을 입력하거나 특정 엔진에 대한 벤치마크 수행을 요청하면 이 스킬이 실행됩니다.

---

## 🛠️ 에이전트 구동 지침 (Execution Guidelines)

본 벤치마크는 **답변 작성용 LLM**과 **채점용 LLM**을 격리하여, 에이전트가 벤치마크 진행 상황이나 다른 문서를 참조하지 못하게 차단(무맥락 격리)하고 순수한 검색 엔진의 성능을 측정해야 합니다.

### 1단계: 벤치마크 평가기 기동
1.  벤치마크 작업 디렉토리(설치된 리포지토리 폴더)로 이동합니다.
2.  사용자가 지정한 엔진명(예: `qmd`)을 기반으로 아래 명령어를 백그라운드로 실행(Propose)합니다.
    ```bash
    python3 evaluator.py --engine <엔진이름> --interactive-agent --output results/<엔진이름>_report.md
    ```

### 2단계: 실시간 프롬프트 브래킷 대응 (Interactive Loop)
명령어가 실행되면서 표준 출력(stdout)에 `=== SUBAGENT_PROMPT_START ===` 및 `=== SUBAGENT_PROMPT_END ===` 블록이 나타납니다. 에이전트는 이를 감지하고 다음과 같이 상호작용해야 합니다.

#### Case A: 답변 생성 프롬프트 감지 (`[답변 지시사항]`)
출력 블록의 첫 내용이 `[답변 지시사항]`인 경우:
1.  두 마커(`=== SUBAGENT_PROMPT_START ===`와 `=== SUBAGENT_PROMPT_END ===`) **사이의 텍스트만**을 정확히 추출합니다. (기타 벤치마크 파일 경로나 파일 목록, 질문 ID 등은 절대 포함해서는 안 됩니다.)
2.  **새로운 `self` 서브에이전트(Subagent)**를 다음 조건으로 호출합니다.
    *   **TypeName**: `self`
    *   **Prompt**: 추출한 프롬프트 텍스트 전체
    *   **Role**: `QA Reader Assistant`
3.  서브에이전트가 답변을 생성하면, 그 답변 텍스트 전체를 구동 중인 평가기 태스크의 입력으로 전달합니다. (툴: `manage_task` -> `send_input`)

#### Case B: 채점 프롬프트 감지 (`[채점 지시사항]`)
출력 블록의 첫 내용이 `[채점 지시사항]`인 경우:
1.  두 마커 사이의 프롬프트 텍스트를 추출합니다.
2.  **새로운 `self` 서브에이전트(Subagent)**를 호출합니다.
    *   **TypeName**: `self`
    *   **Prompt**: 추출한 프롬프트 텍스트 전체 (JSON 형식의 출력 유도)
    *   **Role**: `Benchmark Grader`
3.  서브에이전트가 채점 결과 JSON(예: `{"score": 3, "reason": "..."}`)을 출력하면, 이 JSON 텍스트를 그대로 평가기 태스크의 입력으로 전달합니다. (툴: `manage_task` -> `send_input`)

### 3단계: 보고서 요약 및 출력
평가기가 모든 문항의 처리를 완료하고 성공적으로 종료되면:
1.  생성된 `results/<엔진이름>_report.md` 결과 파일 링크를 제시합니다.
2.  터미널에 출력된 요약 통계(총점 및 달성도)를 사용자에게 간략히 브리핑합니다.
