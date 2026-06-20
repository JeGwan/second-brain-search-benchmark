# 엔진 어댑터 규약 (Engine Adapter Contract)

SBSE-Bench는 **엔진-agnostic** 합니다. 어떤 검색 엔진을 평가할지는 전적으로
사용자의 선택이며, 벤치마크는 특정 엔진 어댑터를 기본 제공하지 않습니다.
평가하려는 엔진마다 아래 규약을 만족하는 **얇은 어댑터** 하나가 필요합니다.

> **손으로 짤 필요는 없습니다.** `/sbse-bench <엔진이름>` 을 호출하면 에이전트가
> 0단계에서 엔진의 `--help`/문서/MCP 스펙을 조사해 이 규약에 맞는 `search.py` 를
> **1회 자동 생성**하고, 이후에는 그 파일을 고정 재사용합니다(`SKILL.md` 0단계 참고).
> 아래 규약은 그 자동 생성 결과를 검수하거나 직접 작성할 때의 기준입니다.

## 1. 디렉토리 규약
```
engines/
└── <your_engine>/
    └── search.py        # 필수: 평가기가 호출하는 검색 어댑터
```
`evaluator.py --engine <your_engine>` 는 `engines/<your_engine>/search.py` 를 호출합니다.

## 2. search.py 인터페이스 (계약)
* **입력**: 첫 번째 명령행 인자 `argv[1]` 로 검색 질의(query) 문자열을 받는다.
* **출력**: 검색된 컨텍스트(원문 스니펫/문서)를 **stdout** 으로 출력한다.
  * 평가기는 이 stdout 전체를 "검색된 컨텍스트"로 사용해 핵심사실 커버리지·문서 재현율을
    문자열 매칭으로 계산한다(LLM 개입 없음).
  * 출력에 **원본 문서명/제목**을 포함하면 검색 재현율(Document Recall) 측정에
    유리하다. 평가기는 `questions.json` 의 `reference_notes`(예: `02_재무팀_비밀_장부.md`)
    파일명(또는 숫자 프리픽스를 뗀 핵심 토큰)이 컨텍스트에 등장하는지로 재현율을 계산한다.
* **누수 금지**: 로컬 절대경로/`file://` URI 등은 출력하지 않는다(보고서 가독성·재현율
  토큰 매칭을 위해 어댑터 단에서 피한다).
* **종료 코드**: 성공 시 0. 실패 시 stderr 에 오류를 쓰고 0이 아닌 코드로 종료.

### 최소 예시
```python
#!/usr/bin/env python3
import sys, subprocess, os

def main():
    if len(sys.argv) < 2:
        print("Usage: search.py <query>"); sys.exit(1)
    query = sys.argv[1]
    # 여기서 당신의 검색 엔진을 호출하고, 검색된 문서/스니펫을 stdout 으로 출력하세요.
    # 예) result = subprocess.run([...your engine CLI...], capture_output=True, text=True, check=True)
    #     print(result.stdout)
    ...

if __name__ == "__main__":
    main()
```

## 3. 실행
```bash
# 1) 평가할 엔진에 second_brain/ 를 색인한다 (엔진마다 방식이 다름)
# 2) 어댑터 작성: engines/<your_engine>/search.py
# 3) 평가 실행 — 단일 명령 (산출물은 engines/<your_engine>/ 아래로 모임)
python3 evaluator.py run --engine <your_engine>
#   → engines/<your_engine>/report.md + report.results.json 생성 (3지표)
```
보통은 에이전트에게 `/sbse-bench <your_engine>` 라고 요청하면 위 과정을 자동 수행합니다(SKILL.md).
별도 단계·작업 파일·반복 실행이 없으며, 검색이 결정론적이라 어떤 환경에서도 동일합니다.

## 4. no-engine — 데이터셋 자기검증 (Dataset Self-Test)
`engines/no-engine/` 는 쿼리를 무시하고 `second_brain/` 전체를 그대로 반환합니다.
전체 문서가 컨텍스트에 들어가므로 **핵심사실 커버리지가 100% 여야 정상**입니다.
이는 모델 베이스라인이 아니라, `questions.json` 의 `key_facts`/알리아스가 코퍼스 텍스트와
일치하는지 점검하는 **질문지 셀프테스트**입니다. 100% 미만이면 알리아스 정의나 정규화가
코퍼스와 어긋난 것이니 질문지를 점검하세요. 자세한 내용은 `engines/no-engine/README.md`.

## 5. 참고용 예제 (리포지토리 한정)
이 리포지토리에는 참고/리더보드 재현용으로 두 예제가 포함되어 있습니다.
**이들은 설치 스크립트로 배포되지 않으며**, 작성 예시로만 보세요.
* `engines/qmd/` — [QMD](https://github.com/tobi/qmd) 검색 엔진 어댑터(레퍼런스).
* `engines/no-engine/` — 전체 문서 반환 어댑터. 데이터셋 자기검증(커버리지 100% 기대)에
  사용합니다.
