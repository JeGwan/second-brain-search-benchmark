#!/usr/bin/env python3
import os
import sys

def main():
    # 쿼리 인자는 무시하고 second_brain 폴더 내의 모든 파일을 출력하여 완벽한 컨텍스트 제공
    second_brain_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../second_brain"))
    if not os.path.exists(second_brain_dir):
        print(f"Error: second_brain directory not found at {second_brain_dir}", file=sys.stderr)
        sys.exit(1)
        
    for filename in sorted(os.listdir(second_brain_dir)):
        if filename.endswith(".md"):
            filepath = os.path.join(second_brain_dir, filename)
            print(f"---\n# {filename}\n")
            with open(filepath, "r", encoding="utf-8") as f:
                print(f.read())
            print("\n")

if __name__ == "__main__":
    main()
