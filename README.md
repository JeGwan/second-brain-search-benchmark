# 📊 Second Brain Search Engine Benchmark (SBSE-Bench)

세컨드 브레인 검색 엔진 벤치마크(SBSE-Bench)는 위키(Wiki)나 마크다운 폴더와 같은 비정형 지식 뭉치(세컨드 브레인)에서 정보와 맥락을 얼마나 정확하게 검색·추출하는지 평가하기 위한 오픈 소스 벤치마크 도구입니다.

이 리포지토리는 API 키(비용 지불) 없이, 사용자의 월 구독형 AI 에이전트(Claude Code, Antigravity 등)가 가진 로컬 실행 권한과 스킬 기능을 기반으로 완전 자동 벤치마크를 수행하도록 최적화되어 있습니다.

---

## 📂 리포지토리 폴더 구조 (Directory Structure)

```
second-brain-search-benchmark/
├── README.md               # 벤치마크 개요, 설치 및 실행 안내
├── evaluator.py            # 공통 평가 채점 엔진 (RAG 질의 및 에이전트 인터랙티브 중계)
├── installer.py            # 에이전트용 스킬 자동 설치 스크립트
├── questions.json          # 표준 벤치마크 평가 질문지 및 채점 루브릭 (5개 문항)
├── second_brain/           # 표준 테스트 데이터셋 (비정형 마크다운 폴더)
│   ├── 01_횡령의혹_내부감사보고서.md
│   ├── 02_재무팀_비밀_장부.md
│   ├── 03_인사기록_및_조직도.md
│   └── 04_사내_메신저_백업.md
├── skills/
│   └── sbse-bench/
│       └── SKILL.md        # 에이전트 스킬 설정 파일
├── engines/                # 각 검색 엔진별 플러그인 폴더
│   └── qmd/                
│       ├── README.md       
│       ├── search.py       # QMD 검색 연산 수행 및 stdout 출력 스크립트
│       └── answers.json    # 캐싱된 QMD 답변 결과 파일
└── results/                # 엔진별 최종 벤치마크 점수 보고서 보관함
    ├── .gitkeep
    └── qmd_report.md       # QMD의 공식 벤치마크 결과 보고서
```

---

## 🚀 벤치마크 구동 방법 (에이전트 사용자용)

### 1단계: 스킬 설치 (Install Skill)
터미널에서 에이전트를 통해 아래 설치 스크립트를 실행합니다.
```bash
# 워크스페이스에 스킬 설치 (기본값)
./installer.py --workspace-install

# 글로벌 에이전트 설정 디렉토리에 설치
./installer.py --global-install
```
설치 완료 시 에이전트가 새로운 명령어 `/sbse-bench`를 인식하게 됩니다.

### 2단계: 대상 검색 엔진 설정
테스트하려는 엔진 폴더(예: `engines/qmd/`)의 가이드에 따라 `second_brain/` 데이터셋을 인덱싱합니다.
(예: QMD의 경우 `npx @tobilu/qmd collection add second_brain` 및 `qmd embed` 실행)

### 3단계: 벤치마크 명령어 실행
에이전트와의 채팅창에 다음 명령어를 입력합니다.
```
/sbse-bench qmd
```
또는 "sbse-bench 스킬로 qmd 벤치마크 수행해줘"라고 한글로 요청하셔도 됩니다.

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
