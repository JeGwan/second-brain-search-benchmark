#!/usr/bin/env python3
"""
SBSE-Bench 스킬 및 벤치마크 파일 원격 설치기 (Remote Installer)
이 스크립트는 로컬 파일이 없는 경우 GitHub에서 최신 벤치마크 데이터를 직접 다운로드하여 설치합니다.
"""

import os
import sys
import shutil
import argparse
import urllib.request

GITHUB_RAW_URL = "https://raw.githubusercontent.com/JeGwan/second-brain-search-benchmark/main"

# 벤치마크에 필요한 코어 파일 목록
CORE_FILES = [
    "evaluator.py",
    "questions.json",
    "second_brain/01_횡령의혹_내부감사보고서.md",
    "second_brain/02_재무팀_비밀_장부.md",
    "second_brain/03_인사기록_및_조직도.md",
    "second_brain/04_사내_메신저_백업.md",
    "skills/sbse-bench/SKILL.md"
]

def download_file(url, dest_path):
    print(f"📥 다운로드 중: {url} -> {dest_path}")
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            with open(dest_path, "wb") as f:
                f.write(response.read())
    except Exception as e:
        print(f"❌ 다운로드 오류 발생: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="SBSE-Bench Skill & File Installer")
    parser.add_argument("--global-install", action="store_true", help="Install skill to global Gemini config (~/.gemini/config)")
    parser.add_argument("--workspace-install", action="store_true", help="Install skill to workspace (.agents)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. 벤치마크 구동용 파일들을 현재 실행 경로에 내려받기 (로컬 파일이 없을 때만 다운로드)
    for file_path in CORE_FILES:
        local_path = os.path.join(script_dir, file_path)
        if not os.path.exists(local_path):
            remote_url = f"{GITHUB_RAW_URL}/{file_path}"
            download_file(remote_url, local_path)
            if file_path.endswith(".py"):
                os.chmod(local_path, 0o755)

    # 2. 에이전트 커스터마이징 폴더에 스킬(SKILL.md) 등록
    # 볼트 루트 탐색 (상위 폴더에 .git이나 README가 있는지 기준으로 판단)
    vault_root = script_dir
    for _ in range(3):
        if os.path.exists(os.path.join(vault_root, ".git")) or os.path.exists(os.path.join(vault_root, "README.md")):
            break
        vault_root = os.path.dirname(vault_root)

    src_skill_path = os.path.join(script_dir, "skills", "sbse-bench", "SKILL.md")
    
    if args.global_install:
        target_dir = os.path.expanduser("~/.gemini/config/skills/sbse-bench")
    else:
        # 기본값: 워크스페이스 설치
        target_dir = os.path.join(vault_root, ".agents", "skills", "sbse-bench")

    target_skill_path = os.path.join(target_dir, "SKILL.md")
    print(f"📦 에이전트 스킬 복사 중:\n  - 원본: {src_skill_path}\n  - 대상: {target_skill_path}")
    
    try:
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(src_skill_path, target_skill_path)
        print("\n✅ SBSE-Bench 스킬 및 벤치마크 파일 설치 성공!")
        print("💡 에이전트 대화창에 '/sbse-bench qmd'를 입력하여 실행해 보세요.")
    except Exception as e:
        print(f"❌ 스킬 설치 실패: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
