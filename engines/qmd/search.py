#!/usr/bin/env python3
import sys
import subprocess
import os

def main():
    if len(sys.argv) < 2:
        print("Usage: search.py <query>")
        sys.exit(1)
        
    query = sys.argv[1]
    # QMD 쿼리 명령어 실행
    cmd = ["npx", "@tobilu/qmd", "query", query, "-n", "3", "--format", "md"]
    try:
        # 이 파일의 상위 부모 폴더(Second Brain 벤치마크/)에서 실행하도록 CWD 설정
        cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=True)
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error querying QMD: {e.stderr}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
