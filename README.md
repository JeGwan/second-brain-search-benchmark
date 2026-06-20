# 📊 Second Brain Search Engine Benchmark (SBSE-Bench)

세컨드 브레인 검색 엔진 벤치마크(SBSE-Bench)는 위키(Wiki)나 마크다운 폴더와 같은 비정형 지식 뭉치(세컨드 브레인)에서 정보와 맥락을 얼마나 정확하게 검색·추출하는지 평가하기 위한 오픈 소스 벤치마크 도구입니다.

이 리포지토리는 API 키 발급 및 비용 지불 없이, 사용자가 월 구독형으로 사용하는 다양한 AI 에이전트(Antigravity, Claude Code, Codex 등)의 실행 권한을 활용하여 안전하게 격리된 무맥락 벤치마크를 수행할 수 있도록 설계되어 있습니다.

---

## 📂 리포지토리 폴더 구조 (Directory Structure)

```
second-brain-search-benchmark/
├── README.md               # 벤치마크 개요, 설치 및 실행 안내
├── evaluator.py            # 공통 평가 채점 엔진 (RAG 질의 및 에이전트 인터랙티브 중계)
├── questions.json          # 표준 벤치마크 평가 질문지 및 채점 루브릭 (5개 문항)
├── second_brain/           # 표준 테스트 데이터셋 (비정형 마크다운 폴더)
│   ├── 01_횡령의혹_내부감사보고서.md
│   ├── 02_재무팀_비밀_장부.md
│   ├── 03_인사기록_및_조직도.md
│   └── 04_사내_메신저_백업.md
├── scripts/
│   └── install.sh          # 에이전트 환경 자동 감지 및 통합 설치 스크립트
├── skills/
│   └── sbse-bench/
│       └── SKILL.md        # 에이전트 스킬 설정 파일
├── engines/                # 각 검색 엔진별 플러그인 폴더
│   └── qmd/                
│       ├── README.md       
│       └── search.py       # QMD 검색 연산 수행 및 stdout 출력 스크립트
└── results/                # 엔진별 최종 벤치마크 점수 보고서 보관함
    ├── .gitkeep
    └── qmd_report.md       # QMD의 공식 벤치마크 결과 보고서
```

---

## 🚀 에이전트별 설치 및 구동 방법 (Agent Setup Guide)

사용자는 로컬에 소스코드를 클론할 필요 없이, 자신이 사용하는 에이전트 환경에서 **한 줄의 설치 명령**을 통해 벤치마크 스킬과 필요 데이터를 자동으로 통합 구성할 수 있습니다.

### 1. 통합 설치 (Common Remote Install)
어떠한 에이전트를 사용하든 터미널 프롬프트(또는 쉘)에 다음 명령을 실행하여 설치합니다.
```bash
curl -fsSL https://raw.githubusercontent.com/JeGwan/second-brain-search-benchmark/main/scripts/install.sh | bash
```
*이 스크립트는 로컬의 Python 3 환경을 체크하고, 벤치마크에 필요한 데이터셋을 다운로드하며, 현재 활성화된 에이전트 환경(Gemini, Claude, Codex)을 감지하여 적절한 폴더에 스킬(`SKILL.md`)을 자동 설치/등록합니다.*

---

### 2. 에이전트별 구동 방법 (Running the Benchmark)

#### 🔹 Antigravity (Gemini-based Agent)
Antigravity CLI는 파일 구조 기반의 커스텀 **스킬(Skills)** 시스템을 기본 지원합니다.
*   **스킬 호출**: 채팅창에 아래와 같이 입력하여 실행합니다.
    ```
    /sbse-bench qmd
    ```
    *또는 "sbse-bench 스킬로 qmd 벤치마크 수행해줘"라고 한글로 자유롭게 입력해도 동작합니다.*

#### 🔹 Claude Code (Anthropic CLI Agent)
Claude Code는 터미널 실행에 특화되어 있으며, 쉘 명령어와의 연동이 매우 강력합니다.
*   **구동 방법**: Claude Code 프롬프트에 직접 아래 가이드와 명령어를 입력합니다.
    > "아래 명령어로 평가기를 구동하고, `=== SUBAGENT_PROMPT_START ===` 마커와 함께 질문이 제공되면 다른 문서를 직접 열지 말고(격리), 질문에 포함된 컨텍스트 정보만 참고하여 답변해줘."
    
    ```bash
    python3 evaluator.py --engine qmd --interactive-agent
    ```

#### 🔹 Codex (OpenAI Developer Agent Framework)
Codex 및 기타 개발자용 커스텀 에이전트 프레임워크 환경입니다.
*   **구동 방법**: Codex가 횡령 문서를 직접 읽는 치팅을 쓰지 않도록 실행 프롬프트를 지정하여 구동합니다.
    > "아래 명령어를 실행하고, `=== SUBAGENT_PROMPT` 마커가 감지되면 출력된 텍스트 범위 내에서만 100% 무맥락 격리 상태로 답변을 순차적으로 작성해서 stdin으로 입력해줘."
    
    ```bash
    python3 evaluator.py --engine qmd --interactive-agent
    ```

---

## 🧠 에이전트 격리 실행 원리 (How it Works)

에이전트는 벤치마크 실행 시 아래와 같이 철저히 통제된 샌드박스 루프를 돌며 답변과 채점을 수행합니다.

1.  **무맥락/격리 (No Context & Isolation)**:
    *   평가기(`evaluator.py`)가 검색 엔진의 `search.py`를 실행하여 검색 결과만 추출합니다.
    *   에이전트는 질문과 검색된 텍스트조각(Context) 정보만 담아 **독립된 `self` 서브에이전트**를 띄웁니다.
    *   서브에이전트는 이 대화가 벤치마크의 일부라는 정보나 전체 원본 마크다운 파일들의 위치를 모른 채 오로지 주어진 텍스트 내용에 기반해서만 답변을 작성하여 제출합니다 (LLM의 치팅 및 정보 추가 획득 원천 차단).
2.  **무비용 채점 (Zero-Cost Grading)**:
    *   답변 생성이 완료되면, 다시 독립된 서브에이전트를 띄워 채점 루브릭에 따라 답변을 1~3점으로 매기고 그 이유를 JSON 포맷으로 평가기에 전달합니다.
    *   사용자는 어떠한 API 키도 발급받을 필요가 없으며, 에이전트의 월 구독 크레딧으로 벤치마크 전체 연산이 완결됩니다.

---

## 🏆 공식 벤치마크 리더보드 (Leaderboard)

| 순위 | 검색 엔진 (Engine) | 전체 점수 (Score) | 달성도 (%) | 평가 일자 (Date) | 상세 보고서 (Report) |
| :---: | :--- | :---: | :---: | :---: | :---: |
| 🥇 | **QMD** (v2.5.3) | **13 / 15** | **86.7%** | 2026-06-20 | [보고서 보기](results/qmd_report.md) |
| - | *다음 엔진 기여를 기다립니다!* | - | - | - | - |
