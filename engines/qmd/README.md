# QMD 검색 엔진 어댑터 (예제)

이 디렉토리는 [QMD(Query Markup Documents)](https://github.com/tobi/qmd) 검색 엔진을
평가하기 위한 **참고용 어댑터 예제**입니다. (벤치마크는 엔진-agnostic 하며, 설치
스크립트는 이 어댑터를 배포하지 않습니다. 어댑터 규약은 `../README.md` 참고.)

본 벤치마크는 **API 키를 사용하지 않습니다.** 답변/채점은 에이전트의 월구독
크레딧으로 도는 격리 서브에이전트(`--interactive-agent`)가 수행합니다.

---

## 🚀 구동 방법

### 1단계: QMD 설치
```bash
# npx 로 별도 글로벌 설치 없이 실행 가능. (전역 설치를 원하면: npm install -g @tobilu/qmd)
```

### 2단계: 로컬 인덱스 생성 및 문서 색인
벤치마크 루트 디렉토리에서 QMD를 초기화하고 `second_brain/` 을 색인합니다.
```bash
qmd init
qmd collection add second_brain
qmd embed
```

### 3단계: 벤치마크 실행 (격리 에이전트 모드)
루트에서 평가기를 격리 에이전트 모드로 구동합니다. 검색은 `search.py` 어댑터가
수행하고(top-N 은 `QMD_TOP_N` 환경변수로 조정, 기본 5), 답변/채점은 격리 서브에이전트가
담당합니다.
```bash
python3 evaluator.py --engine qmd --interactive-agent
```
실행이 끝나면 `engines/qmd/` 한 폴더에 `answers.json`(답변 캐시), `contexts.json`
(검색 컨텍스트 캐시), `report.md`(보고서), `report.results.json`(채점 결과 캐시)이
생성됩니다.

### 4단계: 보고서 재생성 (LLM/엔진 불필요)
채점 결과 캐시로부터 보고서만 다시 만들 수 있습니다.
```bash
python3 evaluator.py --from-results engines/qmd/report.results.json
```
