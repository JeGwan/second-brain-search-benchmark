#!/usr/bin/env python3
import os
import sys
import shutil
import argparse

def main():
    parser = argparse.ArgumentParser(description="SBSE-Bench Skill Installer")
    parser.add_argument("--global-install", action="store_true", help="Install skill to global Gemini config (~/.gemini/config)")
    parser.add_argument("--workspace-install", action="store_true", help="Install skill to workspace (.agents)")
    args = parser.parse_args()

    # 원본 스킬 폴더 위치
    # 이 스크립트 위치 기준으로 볼트 루트의 .agents/skills/sbse-bench를 이용
    script_dir = os.path.dirname(os.path.abspath(__file__))
    vault_root = os.path.abspath(os.path.join(script_dir, "../.."))
    src_skill_dir = os.path.join(vault_root, ".agents", "skills", "sbse-bench")

    if not os.path.exists(src_skill_dir):
        # 만약 볼트에 .agents가 없으면 로컬 스크립트 내부의 폴더를 생성
        src_skill_dir = os.path.join(script_dir, "skills", "sbse-bench")
        # 임시로 스킬 파일 생성 (백업용)
        os.makedirs(src_skill_dir, exist_ok=True)
        shutil.copy2(os.path.join(vault_root, ".agents", "skills", "sbse-bench", "SKILL.md"), os.path.join(src_skill_dir, "SKILL.md"))

    target_dir = None
    if args.global_install:
        target_dir = os.path.expanduser("~/.gemini/config/skills/sbse-bench")
    elif args.workspace_install or not args.global_install:
        target_dir = os.path.join(vault_root, ".agents", "skills", "sbse-bench")

    print(f"📦 스킬 복사 중:\n  - 원본: {src_skill_dir}\n  - 대상: {target_dir}")
    
    try:
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        shutil.copytree(src_skill_dir, target_dir)
        print("✅ 스킬 설치 성공!")
    except Exception as e:
        print(f"❌ 스킬 설치 실패: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
