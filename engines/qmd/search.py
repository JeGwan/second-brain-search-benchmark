#!/usr/bin/env python3
"""QMD 검색 엔진 어댑터.

벤치마크 평가기가 쿼리를 인자로 넘기면, QMD로 관련 문서를 검색해 마크다운
컨텍스트를 stdout 으로 출력한다.

검색 상위 N개(top-N)는 환경변수 QMD_TOP_N 으로 조정한다. 기본값은 5다.
  - 주의: 세컨드 브레인 코퍼스가 작을 때(예: 문서 4개) top-N 을 코퍼스 크기보다
    작게 두면, 멀티홉 질문에 필요한 문서가 검색 단계에서 강제 탈락해 점수가
    '검색 실패'로 깎인다. 이는 생성/추론 성능과 무관하다.
  - 평가기는 reference_notes 대비 '검색 재현율(Retrieval Recall)'을 계산하므로,
    N 값을 바꿔가며 랭킹 품질을 스트레스 테스트할 수 있다. 큰 코퍼스에서
    랭킹을 평가하려면 N 을 작게, 회수 누락을 배제하려면 N 을 크게 둔다.
"""
import sys
import subprocess
import os


def main():
    if len(sys.argv) < 2:
        print("Usage: search.py <query>")
        sys.exit(1)

    query = sys.argv[1]
    top_n = os.environ.get("QMD_TOP_N", "5")

    cmd = ["npx", "@tobilu/qmd", "query", query, "-n", str(top_n), "--format", "md"]
    try:
        # 벤치마크 루트 폴더(두 단계 위)에서 실행
        cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=True)
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error querying QMD: {e.stderr}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
