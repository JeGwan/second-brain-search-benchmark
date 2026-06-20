# QMD 검색 엔진 벤치마크 러너 (QMD Search Engine Benchmark Runner)

이 디렉토리는 [QMD(Query Markup Documents)](https://github.com/tobi/qmd) 검색 엔진을 사용하여 벤치마크 평가를 수행하기 위한 스크립트와 가이드를 포함합니다.

---

## 🚀 구동 방법

### 1단계: QMD 및 의존성 설치
QMD가 로컬 시스템에 설치되어 있어야 합니다.
```bash
# npx를 사용하므로 별도 글로벌 설치 없이 실행 가능합니다.
# 만약 전역 설치를 원할 경우:
npm install -g @tobilu/qmd
```

### 2단계: 로컬 인덱스 생성 및 문서 색인
벤치마크 루트 디렉토리(`Second Brain 벤치마크/`)에서 QMD를 초기화하고 문서들을 색인합니다.
```bash
# 벤치마크 루트 폴더에서 실행
qmd init
qmd collection add second_brain
qmd embed
```

### 3단계: RAG 답변 생성 실행
이 폴더의 `run_qmd.py` 스크립트를 실행하여 질문에 대한 답변을 생성합니다. 스크립트는 QMD로 관련 컨텍스트를 검색한 뒤, LLM(Gemini 또는 OpenAI)을 사용해 답변을 작성합니다.
```bash
# API 키 설정 (둘 중 하나 필수)
export GEMINI_API_KEY="your-gemini-api-key"
# 또는
export OPENAI_API_KEY="your-openai-api-key"

# 스크립트 실행
python3 run_qmd.py
```
*실행이 완료되면 본 디렉토리에 `answers.json` 파일이 생성됩니다.*

### 4단계: 평가 및 보고서 생성
루트 디렉토리의 `evaluator.py`를 실행하여 답변을 채점하고 보고서를 만듭니다.
```bash
# 벤치마크 루트 폴더에서 실행
python3 evaluator.py --answers engines/qmd/answers.json --output results/qmd_report.md
```
*채점이 완료되면 `results/qmd_report.md`에 최종 벤치마크 점수 보고서가 기록됩니다.*
