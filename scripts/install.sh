#!/usr/bin/env bash
# SBSE-Bench installer — auto-detects agent runtime and installs benchmark files & skills.
# Usage: curl -fsSL https://raw.githubusercontent.com/JeGwan/second-brain-search-benchmark/main/scripts/install.sh | bash

set -euo pipefail

GITHUB_RAW_URL="https://raw.githubusercontent.com/JeGwan/second-brain-search-benchmark/main"

CORE_FILES=(
  "evaluator.py"
  "questions.json"
  "second_brain/01_횡령의혹_내부감사보고서.md"
  "second_brain/02_재무팀_비밀_장부.md"
  "second_brain/03_인사기록_및_조직도.md"
  "second_brain/04_사내_메신저_백업.md"
  "skills/sbse-bench/SKILL.md"
)

# Color configurations
if [ -z "${NO_COLOR:-}" ] && { [ -t 1 ] || [ -n "${FORCE_COLOR:-}" ]; } && { [ "${TERM:-}" != "dumb" ] || [ -n "${FORCE_COLOR:-}" ]; }; then
  BOLD="$(printf '\033[1m')"
  DIM="$(printf '\033[2m')"
  GREEN="$(printf '\033[1;32m')"
  YELLOW="$(printf '\033[1;33m')"
  BLUE="$(printf '\033[1;34m')"
  CYAN="$(printf '\033[1;36m')"
  MAGENTA="$(printf '\033[1;35m')"
  RED="$(printf '\033[1;31m')"
  RESET="$(printf '\033[0m')"
else
  BOLD=""
  DIM=""
  GREEN=""
  YELLOW=""
  BLUE=""
  CYAN=""
  MAGENTA=""
  RED=""
  RESET=""
fi

_say() { printf '%s\n' "$*"; }
_blank() { printf '\n'; }
_step() { _blank; _say "${BLUE}◆${RESET} ${BOLD}$1${RESET}"; if [ "${2:-}" != "" ]; then _say "  ${DIM}$2${RESET}"; fi; }
_ok() { _say "  ${GREEN}✓${RESET} $1"; }
_warn() { _say "  ${YELLOW}!${RESET} $1"; }
_err() { _say "  ${RED}✗${RESET} $1"; }
_info() { _say "  ${DIM}•${RESET} $1"; }

_banner() {
  _say "${MAGENTA}╭────────────────────────────────────────────╮${RESET}"
  _say "${MAGENTA}│${RESET} ${BOLD}${CYAN}SBSE-Bench Installer${RESET}                       ${MAGENTA}│${RESET}"
  _say "${MAGENTA}│${RESET} ${DIM}Second Brain Search Engine Benchmark${RESET}       ${MAGENTA}│${RESET}"
  _say "${MAGENTA}╰────────────────────────────────────────────╯${RESET}"
  _say "${DIM}Installs the benchmark files and registers skills for local agents.${RESET}"
}

# 0. Show Banner
_banner

# 1. Check Python
_step "1/3 Checking System Environment"
if command -v python3 &>/dev/null; then
  _ok "Python 3 found: $(python3 --version)"
else
  _err "Python 3 is required to run the evaluator. Please install Python 3."
  exit 1
fi

# 2. Detect Runtimes
_info "Detecting active AI Agent environments..."
HAS_GEMINI=false
HAS_CLAUDE=false
HAS_CODEX=false

if command -v gemini &>/dev/null || [ -d "$HOME/.gemini" ]; then
  _ok "Gemini / Antigravity environment detected."
  HAS_GEMINI=true
fi
if command -v claude &>/dev/null || [ -d "$HOME/.claude" ]; then
  _ok "Claude Code environment detected."
  HAS_CLAUDE=true
fi
if command -v codex &>/dev/null || [ -d "$HOME/.codex" ]; then
  _ok "Codex environment detected."
  HAS_CODEX=true
fi

# 3. Download Files
_step "2/3 Downloading Benchmark Core Files" "Downloading latest files from GitHub..."
for file in "${CORE_FILES[@]}"; do
  # 로컬 디렉토리 생성
  mkdir -p "$(dirname "$file")"
  
  # 다운로드 (curl)
  if curl -fsSL "${GITHUB_RAW_URL}/${file}" -o "${file}"; then
    _ok "Downloaded: ${file}"
    if [[ "$file" == *.py ]]; then
      chmod +x "$file"
    fi
  else
    _err "Failed to download: ${file}"
    exit 1
  fi
done

# 4. Wire skills for runtimes
_step "3/3 Wiring Agent Customization Skills"

# Determine workspace root (looking for .git or README)
VROOT="."
for i in {1..3}; do
  if [ -d "$VROOT/.git" ] || [ -f "$VROOT/README.md" ]; then
    break
  fi
  VROOT=".."
done
VROOT=$(abspath "$VROOT" 2>/dev/null || cd "$VROOT" && pwd)

# 4a. Install to workspace .agents/ (Standard for Gemini/Claude/Codex workspace config)
WORKSPACE_SKILL_DIR="${VROOT}/.agents/skills/sbse-bench"
_info "Wiring workspace skill path: ${WORKSPACE_SKILL_DIR}"
mkdir -p "${WORKSPACE_SKILL_DIR}"
cp "skills/sbse-bench/SKILL.md" "${WORKSPACE_SKILL_DIR}/SKILL.md"
_ok "Workspace skill wired."

# 4b. Install to global config folders if detected
if [ "$HAS_GEMINI" = true ]; then
  GEMINI_GLOBAL_DIR="$HOME/.gemini/config/skills/sbse-bench"
  _info "Wiring Gemini global skill path: ${GEMINI_GLOBAL_DIR}"
  mkdir -p "${GEMINI_GLOBAL_DIR}"
  cp "skills/sbse-bench/SKILL.md" "${GEMINI_GLOBAL_DIR}/SKILL.md"
  _ok "Gemini global skill wired."
fi

if [ "$HAS_CLAUDE" = true ]; then
  CLAUDE_GLOBAL_DIR="$HOME/.claude/skills/sbse-bench"
  _info "Wiring Claude global skill path (if supported): ${CLAUDE_GLOBAL_DIR}"
  mkdir -p "${CLAUDE_GLOBAL_DIR}"
  cp "skills/sbse-bench/SKILL.md" "${CLAUDE_GLOBAL_DIR}/SKILL.md"
  _ok "Claude global skill path created."
fi

_blank
_say "${GREEN}${BOLD}Done! SBSE-Bench installation completed successfully.${RESET}"
_blank
_say "${BOLD}How to run:${RESET}"
_info "1. Index the 'second_brain/' directory in your search engine."
_info "2. Call your agent with: /sbse-bench <engine_name>"
_info "   Example: /sbse-bench qmd"
_blank
_info "Enjoy benchmarking your Second Brain!"
