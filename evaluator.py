#!/usr/bin/env python3
"""
세컨드 브레인 검색 엔진 벤치마크 평가기 (Second Brain Search Engine Benchmark Evaluator)

이 스크립트는 검색 엔진의 답변을 받아 평가 기준(루브릭)에 따라 채점하고 보고서를 생성합니다.

설계 원칙 (v3 — 타당성/재현성 개선):
  1. 채점기는 '검색된 컨텍스트'를 함께 받는다. 환각(hallucination) 판정은
     정답(ground truth)이 아니라 '제시된 컨텍스트' 기준으로만 이루어진다.
  2. 검색 실패와 생성 실패를 분리한다. reference_notes 대비 검색 재현율
     (Retrieval Recall)을 별도 지표로 계산해, 점수가 낮은 원인이 검색(retrieval)인지
     생성(generation)인지 구분할 수 있게 한다.
  3. 헤드라인 점수는 stability-runs '평균'으로 계산한다 (run1 단독 사용 금지).
  4. 답변/채점 프롬프트는 단일 소스(build_* 함수)에서 생성한다. API/대화형/수동
     모드가 동일한 프롬프트 텍스트를 사용하므로 결과가 모드 간 비교 가능하다.
  5. 채점 결과(results)를 캐시로 덤프하고 --from-results 로 LLM 없이 보고서를
     재현 생성할 수 있다.
"""

import os
import re
import sys
import json
import math
import argparse
import subprocess
from datetime import datetime

# 평가 질문 파일 경로 (기본값)
DEFAULT_QUESTIONS_PATH = "questions.json"
DEFAULT_REPORT_PATH = "benchmark_report.md"

# 격리 컨텍스트에서 제거할 로컬 절대경로/파일 URI 패턴 (정보 누수 차단)
_PATH_LEAK_PATTERNS = [
    re.compile(r"file://[^\s)\]]+"),
    re.compile(r"/Users/[^\s)\]]+"),
    re.compile(r"/home/[^\s)\]]+"),
    re.compile(r"[A-Za-z]:\\\\[^\s)\]]+"),
    re.compile(r"\.agents/[^\s)\]]+"),
    re.compile(r"\.claude/[^\s)\]]+"),
    re.compile(r"\.gemini/[^\s)\]]+"),
]


def load_questions(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ 에러: 질문지 파일을 찾을 수 없습니다. 경로: {path}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"❌ 에러: 질문지 파일이 올바른 JSON 형식이 아닙니다. 경로: {path}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 프롬프트 단일 소스 (Single source of truth)
# ---------------------------------------------------------------------------

def build_answer_prompt(question_text, context):
    """답변 생성 프롬프트. API/대화형/수동 모든 모드가 이 함수를 사용한다."""
    return f"""[답변 지시사항]
제시된 컨텍스트(Retrieved Context)만을 바탕으로 질문에 한국어로 정확하게 답변하세요.
절대로 외부 지식이나 상상력을 이용해 지어내거나(환각), 무리하게 추론하지 마세요.
제시된 컨텍스트에 정보가 부족하다면, 어떤 정보가 누락되어 답변할 수 없는지 구체적으로 기술하세요.
파일 경로나 시스템 위치를 추측해서 적지 마세요.

[질문]
{question_text}

[검색된 컨텍스트]
{context}
"""


def build_grade_prompt(question_text, ground_truth, rubric_str, answer, context):
    """채점 프롬프트. 환각 판정은 '제시된 컨텍스트' 기준으로만 이루어진다.

    context 가 빈 문자열이면(예: 사전 생성 답변 --answers 모드라 컨텍스트가 없음),
    환각 판정 기준을 정답(ground truth)으로 완화한다는 점을 명시한다.
    """
    if context and context.strip():
        precision_rule = (
            "[중요 채점 규정 - 정밀도(Precision) 감점제]\n"
            "환각 판정은 반드시 아래 '검색된 컨텍스트'를 기준으로 합니다. "
            "후보 답변이 '검색된 컨텍스트'에 근거가 있는 내용을 기술했다면, 그것이 "
            "정답(Ground Truth)과 다소 다르더라도 환각으로 보지 않습니다. 반대로 "
            "후보 답변이 '검색된 컨텍스트'에 전혀 근거가 없는 내용을 사실처럼 지어냈다면 "
            "(컨텍스트에 없는 수치/이름/관계 등) 최종 점수에서 1점을 감점합니다. "
            "(단, 최저 점수는 1점입니다.)\n"
            "주의: 컨텍스트에 정보가 없어서 '답변할 수 없다/누락되었다'고 정직하게 "
            "기술한 것은 환각이 아니며 감점하지 않습니다.\n\n"
            f"[검색된 컨텍스트 — 환각 판정의 유일한 근거]\n{context}\n"
        )
    else:
        precision_rule = (
            "[중요 채점 규정 - 정밀도(Precision) 감점제]\n"
            "(이 채점에는 검색 컨텍스트가 제공되지 않았습니다. 따라서 환각 판정은 "
            "정답(Ground Truth) 및 일반 상식 기준으로만 보수적으로 적용합니다.)\n"
            "후보 답변이 정답과 명백히 상반되는 거짓 사실을 단정적으로 지어낸 경우에만 "
            "1점을 감점합니다. (단, 최저 점수는 1점입니다.)\n"
        )

    return f"""[채점 지시사항]
제시된 질문, 정답(Ground Truth), 채점 루브릭을 보고 후보 답변(Candidate Answer)을 평가하세요.
반드시 루브릭 기준만을 준수하여 1점, 2점, 혹은 3점으로 채점하고 그 이유를 작성해 주세요.

{precision_rule}
질문: {question_text}
정답: {ground_truth}

루브릭:
{rubric_str}

후보 답변:
{answer}

출력 형식:
반드시 아래 JSON 형식만 정확히 반환하세요. 다른 서두나 백틱(```json) 마크다운은 포함하지 마세요.
{{
  "score": <점수: 1, 2, 또는 3>,
  "reason": "<한글 채점 사유, 감점 여부 포함>"
}}
"""


def rubric_to_str(rubric):
    return "\n".join([f"- {score}점: {desc}" for score, desc in rubric.items()])


def sanitize_context(context):
    """검색 컨텍스트에서 로컬 경로/파일 URI 등 누수 가능 정보를 마스킹한다."""
    if not context:
        return context
    cleaned = context
    for pat in _PATH_LEAK_PATTERNS:
        cleaned = pat.sub("[경로 제거됨]", cleaned)
    return cleaned


def compute_retrieval_recall(context, reference_notes):
    """reference_notes(정답 도출에 필요한 원본 문서들)가 검색 컨텍스트에 얼마나
    포함되었는지 비율(0.0~1.0)과 누락 문서 목록을 반환한다.

    context 가 None 이면 (사전 생성 답변 모드 등) (None, None) 을 반환한다.
    """
    if context is None:
        return None, None
    if not reference_notes:
        return None, None

    haystack = context
    present, missing = [], []
    for note in reference_notes:
        stem = note[:-3] if note.endswith(".md") else note  # 확장자 제거
        # 파일명 전체 또는 숫자 프리픽스 제거한 핵심 토큰으로 매칭
        core = re.sub(r"^\d+[_-]", "", stem)
        if stem in haystack or (core and core in haystack):
            present.append(note)
        else:
            missing.append(note)

    recall = len(present) / len(reference_notes)
    return recall, missing


# ---------------------------------------------------------------------------
# 대화형(에이전트 서브에이전트) 채점/답변
#
# 본 벤치마크는 'API 키 무사용'을 원칙으로 한다. 채점/답변은 에이전트의 월구독
# 크레딧으로 도는 격리 서브에이전트(--interactive-agent) 또는 수동 채점으로만
# 수행한다. (외부 LLM API 호출 경로는 의도적으로 제거됨)
# ---------------------------------------------------------------------------

def _read_json_from_stdin(label):
    lines = []
    while True:
        line = sys.stdin.readline()
        if not line:
            print(f"DEBUG {label}: EOF reached", file=sys.stderr)
            break
        print(f"DEBUG {label}: read line: {line.strip()}", file=sys.stderr)
        lines.append(line)
        try:
            data = json.loads("".join(lines).strip())
            if "score" in data:
                return data
        except json.JSONDecodeError:
            pass
    try:
        raw_text = "".join(lines).strip()
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        return json.loads(raw_text.strip())
    except Exception:
        return {"score": 1, "reason": "에이전트 채점 결과 파싱 실패."}


def get_agent_graded(question_text, question_data, answer, context):
    rubric_str = rubric_to_str(question_data["evaluation_rubric"])
    prompt = build_grade_prompt(question_text, question_data["ground_truth"], rubric_str, answer, context)
    print("=== SUBAGENT_PROMPT_START ===")
    print(prompt.strip())
    print("=== SUBAGENT_PROMPT_END ===")
    sys.stdout.flush()
    return _read_json_from_stdin("Grader")


def get_agent_answer(question_text, context):
    prompt = build_answer_prompt(question_text, context)
    print("=== SUBAGENT_PROMPT_START ===")
    print(prompt.strip())
    print("=== SUBAGENT_PROMPT_END ===")
    sys.stdout.flush()

    lines = []
    while True:
        line = sys.stdin.readline()
        if not line:
            print("DEBUG Answer: EOF reached", file=sys.stderr)
            break
        print(f"DEBUG Answer: read line: {line.strip()}", file=sys.stderr)
        if line.strip() == "=== SUBAGENT_ANSWER_END ===":
            break
        lines.append(line)
    return "".join(lines).strip()


def manual_grade(question_text, q, answer, context):
    print("\n" + "=" * 60)
    print(f"❓ 질문 ({q['id']}): {question_text}")
    print(f"💡 정답 (Ground Truth): {q['ground_truth']}")
    if context:
        print("-" * 60)
        print(f"🔎 검색된 컨텍스트(환각 판정 근거):\n{context[:2000]}")
    print("-" * 60)
    print(f"📥 엔진 답변:\n{answer}")
    print("-" * 60)
    print("📋 채점 루브릭:")
    for score in sorted(q["evaluation_rubric"].keys(), reverse=True):
        print(f"  [{score}점] {q['evaluation_rubric'][score]}")
    print("=" * 60)

    while True:
        try:
            score_input = input("👉 이 답변에 매길 점수를 입력하세요 (1, 2, 3): ").strip()
            if score_input in ["1", "2", "3"]:
                score = int(score_input)
                break
            print("⚠️ 올바른 점수(1, 2, 3)를 입력해 주세요.")
        except KeyboardInterrupt:
            print("\n👋 평가가 중단되었습니다.")
            sys.exit(0)

    reason = input("💬 평가 코멘트 (생략 가능, Enter): ").strip()
    if not reason:
        reason = "수동 채점 완료."
    return {"score": score, "reason": reason}


def run_engine_search(engine, query):
    search_script = f"engines/{engine}/search.py"
    if not os.path.exists(search_script):
        print(f"❌ 에러: 엔진 검색 스크립트를 찾을 수 없습니다. 경로: {search_script}")
        sys.exit(1)
    cmd = ["python3", search_script, query]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ 엔진 검색 실행 오류: {e.stderr}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# 통계/요약
# ---------------------------------------------------------------------------

def calc_stats(scores):
    n = len(scores)
    if n == 0:
        return 0.0, 0.0
    mean = sum(scores) / n
    var = sum((x - mean) ** 2 for x in scores) / n
    return mean, math.sqrt(var)


def summarize(results, stability_runs, eval_method, answer_source):
    axis_scores = {}
    total_score = 0.0
    stds = []
    recalls = []
    for r in results:
        axis = r["axis"]
        a = axis_scores.setdefault(axis, {"score": 0.0, "max": 0, "count": 0})
        a["score"] += r["score"]
        a["max"] += 3
        a["count"] += 1
        total_score += r["score"]
        stds.append(r["stability_std"])
        if r.get("retrieval_recall") is not None:
            recalls.append(r["retrieval_recall"])

    max_score = len(results) * 3
    percentage = (total_score / max_score) * 100 if max_score > 0 else 0.0
    avg_std = sum(stds) / len(stds) if stds else 0.0
    avg_recall = sum(recalls) / len(recalls) if recalls else None
    return {
        "total_score": total_score,
        "max_score": max_score,
        "percentage": percentage,
        "eval_method": eval_method,
        "answer_source": answer_source,
        "axis_scores": axis_scores,
        "stability_runs": stability_runs,
        "avg_stability_std": avg_std,
        "avg_retrieval_recall": avg_recall,
    }


# ---------------------------------------------------------------------------
# 보고서 생성
# ---------------------------------------------------------------------------

def generate_report(results, summary, output_path, generated_at=None):
    ts = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_md = f"""# 📊 세컨드 브레인 검색 엔진 벤치마크 결과 보고서

## 1. 종합 요약 (Summary)
*   **평가 일시**: {ts}
*   **헤드라인 점수 (stability-runs 평균)**: **{summary['total_score']:.1f}** / {summary['max_score']} (달성도: **{summary['percentage']:.1f}%**)
*   **평가 방식**: {summary['eval_method']}
*   **답변 출처 (Answer Source)**: {summary['answer_source']}
*   **결정론적 일관성 (Stability Runs)**: {summary['stability_runs']}회 실행
"""
    if summary["stability_runs"] > 1:
        report_md += f"*   **평균 안정성 (Average Stability StdDev)**: {summary['avg_stability_std']:.3f} (낮을수록 우수)\n"
    if summary.get("avg_retrieval_recall") is not None:
        report_md += f"*   **평균 검색 재현율 (Avg Retrieval Recall)**: {summary['avg_retrieval_recall'] * 100:.1f}% (검색 단계가 정답 근거 문서를 얼마나 가져왔는지)\n"

    report_md += """
> **점수 해석 주의**: 헤드라인 점수는 반복 실행의 *평균*입니다. 표본이 작고(문항 5개)
> 비결정성이 있으므로 소수점 차이는 노이즈로 보아야 하며, 단일 순위 비교보다는
> 영역별 강약점과 검색 재현율을 함께 보는 것이 타당합니다.

## 2. 평가 영역별 요약 (Scores by Axis)
| 평가 영역 | 질문 수 | 획득 점수(평균) | 만점 | 백분율 |
| :--- | :---: | :---: | :---: | :---: |
"""
    for axis, data in summary["axis_scores"].items():
        pct = (data["score"] / data["max"]) * 100 if data["max"] > 0 else 0
        report_md += f"| {axis} | {data['count']} | {data['score']:.1f} | {data['max']} | {pct:.1f}% |\n"

    # 검색 재현율 (Retrieval vs Generation 분리)
    has_recall = any(r.get("retrieval_recall") is not None for r in results)
    report_md += """
## 3. 검색 재현율 분석 (Retrieval Recall — 검색 실패 vs 생성 실패 분리)
정답 도출에 필요한 원본 문서(reference_notes)가 검색 단계에서 실제로 회수되었는지 측정합니다.
재현율이 낮으면 점수 하락의 책임은 '생성/추론'이 아니라 '검색'에 있습니다.
"""
    if not has_recall:
        report_md += "\n> 이 보고서에는 검색 컨텍스트가 보존되지 않아(사전 생성 답변/캐시 재현) 검색 재현율을 계산할 수 없습니다. 엔진을 직접 실행(`--engine`)하면 문항별 재현율이 기록됩니다.\n"
    else:
        report_md += """| 문항 ID | 필요한 문서 수 | 검색 재현율 | 누락된 문서 |
| :---: | :---: | :---: | :--- |
"""
        for r in results:
            if r.get("retrieval_recall") is None:
                report_md += f"| {r['id']} | - | N/A (사전 생성 답변) | - |\n"
            else:
                missing = ", ".join(r.get("retrieval_missing") or []) or "없음"
                need = len(r.get("reference_notes") or [])
                report_md += f"| {r['id']} | {need} | {r['retrieval_recall'] * 100:.0f}% | {missing} |\n"

    report_md += """
## 4. 일관성 및 신뢰성 상세 분석 (Consistency & Reliability Analysis)

### 🔹 의미론적 일관성 (Semantic Robustness)
질문 표현 변화(Paraphrasing)에 대해 RAG 시스템이 얼마나 일관된 답변을 제공하는지 평가합니다.
**주의**: Robustness %는 '본 질문 점수와 변형 질문 점수의 일치율'(=일관성)일 뿐,
정확성을 보장하지 않습니다. 따라서 변형 질문 '평균 점수'(정확성 대리값)를 함께 봅니다.
| 문항 ID | 본 질문 점수 | 변형 질문 평균 점수 | 점수 일치도 (Consistency %) |
| :---: | :---: | :---: | :---: |
"""
    has_semantic = False
    for r in results:
        if r.get("paraphrased_results") is not None:
            has_semantic = True
            report_md += f"| {r['id']} | {r['score']:.1f}점 | {r['semantic_avg']:.1f}점 | {r['semantic_robustness_pct']:.1f}% |\n"
    if not has_semantic:
        report_md += "| - | - | - | 변형 질문이 포함된 문항이 없습니다. |\n"

    if summary["stability_runs"] > 1:
        report_md += """
### 🔹 결정론적 일관성 (Deterministic Stability)
동일 질문을 반복 실행했을 때 점수의 변동성(표준편차)을 통해 검색 및 생성 안정성을 평가합니다.
| 문항 ID | 평균 점수 | 표준편차 (StdDev) | 안정성 평가 |
| :---: | :---: | :---: | :---: |
"""
        for r in results:
            std = r["stability_std"]
            status = "🟢 안정" if std < 0.3 else ("🟡 보통" if std < 0.7 else "🔴 불안정")
            report_md += f"| {r['id']} | {r['stability_mean']:.2f}점 | {std:.3f} | {status} |\n"

    report_md += """
## 5. 문항별 세부 결과 (Detailed Results)
"""
    for r in results:
        recall_line = ""
        if r.get("retrieval_recall") is not None:
            missing = ", ".join(r.get("retrieval_missing") or []) or "없음"
            recall_line = f"*   **검색 재현율**: {r['retrieval_recall'] * 100:.0f}% (누락: {missing})\n"
        report_md += f"""
### 📝 {r['id']} ({r['axis']})
*   **질문**: {r['question']}
*   **정답 (Ground Truth)**: {r['ground_truth']}
{recall_line}*   **대표 답변 (run 1)**:
    > {r['answer'].replace(chr(10), chr(10) + '> ')}
*   **점수 (평균)**: **{r['score']:.1f}점** / 3점
*   **대표 평가 의견**: {r['reason']}
"""
        if r.get("paraphrased_results"):
            report_md += "\n*   **의미론적 일관성 변형 질문 테스트**:\n"
            for p_idx, pr in enumerate(r["paraphrased_results"]):
                report_md += f"    *   *변형 {p_idx + 1}*: \"{pr['q_text']}\"\n"
                report_md += f"        *   **점수**: {pr['score']}점 / **평가의견**: {pr['reason']}\n"
                report_md += f"        *   **답변**: {pr['answer']}\n"

        if len(r.get("all_runs", [])) > 1:
            report_md += "\n*   **결정론적 일관성 반복 런 테스트**:\n"
            for run in r["all_runs"]:
                report_md += f"    *   *런 {run['run_idx']}*: 점수 {run['score']}점 | 의견: {run['reason']}\n"

        report_md += "\n---\n"

    try:
        parent_dir = os.path.dirname(output_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"\n🎉 벤치마크 보고서가 생성되었습니다: {output_path}", file=sys.stderr)
    except Exception as e:
        print(f"❌ 에러: 보고서 파일 작성 중 오류 발생: {e}", file=sys.stderr)


def dump_results_cache(results, summary, path, generated_at=None):
    """LLM 없이 보고서를 재현 생성할 수 있도록 채점 결과를 직렬화한다."""
    payload = {
        "meta": {
            "generated_at": generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stability_runs": summary["stability_runs"],
            "eval_method": summary["eval_method"],
            "answer_source": summary["answer_source"],
        },
        "results": results,
    }
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"💾 채점 결과 캐시를 저장했습니다 (재현용): {path}", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ 결과 캐시 저장 실패: {e}", file=sys.stderr)


def report_from_results_cache(cache_path, output_path):
    with open(cache_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    results = payload["results"]
    meta = payload.get("meta", {})
    summary = summarize(
        results,
        meta.get("stability_runs", 1),
        meta.get("eval_method", "캐시 재현"),
        meta.get("answer_source", "캐시 재현"),
    )
    generate_report(results, summary, output_path, generated_at=meta.get("generated_at"))
    print_cli_summary(summary)
    return summary


def print_cli_summary(summary):
    print("\n" + "=" * 40, file=sys.stderr)
    print("📊 벤치마크 평가 결과 요약", file=sys.stderr)
    print(f"- 총점(평균): {summary['total_score']:.1f} / {summary['max_score']} ({summary['percentage']:.1f}%)", file=sys.stderr)
    if summary.get("avg_retrieval_recall") is not None:
        print(f"- 평균 검색 재현율: {summary['avg_retrieval_recall'] * 100:.1f}%", file=sys.stderr)
    print("- 영역별 달성도:", file=sys.stderr)
    for axis, data in summary["axis_scores"].items():
        pct = (data["score"] / data["max"]) * 100 if data["max"] else 0
        print(f"  * {axis}: {data['score']:.1f} / {data['max']} ({pct:.1f}%)", file=sys.stderr)
    print("=" * 40, file=sys.stderr)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="세컨드 브레인 검색 엔진 벤치마크 채점기")
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS_PATH, help="질문지 JSON 파일 경로")
    parser.add_argument("--answers", help="검색 엔진의 답변이 저장된 JSON 파일 경로 (제공 시 검색 단계를 건너뜀)")
    parser.add_argument("--engine", help="대상 검색 엔진 이름 (예: qmd) - --answers 미지정 시 필수")
    parser.add_argument("--output", default=None, help="출력 보고서 경로 (미지정 시 --engine 이면 engines/<engine>/report.md)")
    parser.add_argument("--interactive-agent", action="store_true", help="API 키 없이 에이전트와 대화식 격리 환경(Subagent)으로 답변 및 채점 수행")
    parser.add_argument("--stability-runs", type=int, default=1, help="결정론적 일관성 측정을 위해 각 질문을 반복 실행할 횟수")
    parser.add_argument("--from-results", help="채점 결과 캐시(JSON)로부터 LLM 없이 보고서를 재현 생성합니다.")

    args = parser.parse_args()

    # 출력 경로 기본값 결정: 엔진별 산출물은 engines/<engine>/ 아래로 모은다.
    if not args.output:
        if args.engine:
            args.output = f"engines/{args.engine}/report.md"
        elif args.from_results:
            # 캐시와 같은 위치에 report.md 생성
            args.output = os.path.join(os.path.dirname(args.from_results) or ".", "report.md")
        else:
            args.output = DEFAULT_REPORT_PATH

    # 0. 캐시 재현 모드: LLM/엔진 없이 보고서만 다시 생성
    if args.from_results:
        report_from_results_cache(args.from_results, args.output)
        return

    # 1. 질문지 로드
    questions = load_questions(args.questions)

    # 2. 평가 방식 결정 (API 키 무사용 — 격리 에이전트 또는 수동 채점)
    eval_method = "수동 채점 (Interactive CLI)"
    if args.interactive_agent:
        eval_method = "에이전트 격리 채점 (Interactive Subagent)"

    answers_dict = {}
    if args.answers:
        try:
            with open(args.answers, "r", encoding="utf-8") as f:
                answers_dict = json.load(f)
            answer_source = f"사전 생성 답변 파일 ({args.answers}) — 검색 컨텍스트 없음"
            print(f"📂 답변 파일을 로드했습니다: {args.answers}", file=sys.stderr)
        except Exception as e:
            print(f"❌ 에러: 답변 파일을 읽는 중 오류 발생: {e}", file=sys.stderr)
            sys.exit(1)
    elif not args.engine:
        print("❌ 에러: --answers 파일을 주지 않을 경우, --engine 파라미터가 필수적입니다.", file=sys.stderr)
        sys.exit(1)
    else:
        answer_source = f"실시간 엔진 검색 ({args.engine}) + 격리 답변 생성"

    # 3. 채점 및 답변 생성 진행
    results = []
    contexts_cache = {}

    for q in questions:
        q_id = q["id"]
        axis = q["axis"]
        reference_notes = q.get("reference_notes", [])

        # 서브 테스트 생성 (원본 + 변형 질문)
        sub_tests = [{"q_text": q["question"], "type": "original", "key": q_id}]
        for idx, pq in enumerate(q.get("paraphrased_questions", [])):
            sub_tests.append({"q_text": pq, "type": "paraphrased", "key": f"{q_id}_para{idx + 1}"})

        sub_test_results = []
        for st in sub_tests:
            st_key = st["key"]
            st_runs = []
            for run_idx in range(args.stability_runs):
                run_key = f"{st_key}_run{run_idx + 1}" if args.stability_runs > 1 else st_key

                # 답변 + 컨텍스트 획득
                context = None
                if run_key in answers_dict:
                    answer = answers_dict[run_key]
                else:
                    print(f"🔍 [{q_id}] ({st['type']}) Run {run_idx + 1}/{args.stability_runs} - {args.engine} 검색 엔진으로 컨텍스트 조회...", file=sys.stderr)
                    context = sanitize_context(run_engine_search(args.engine, st["q_text"]))
                    contexts_cache[run_key] = context
                    if args.interactive_agent:
                        answer = get_agent_answer(st["q_text"], context)
                    else:
                        print("\n" + "=" * 50, file=sys.stderr)
                        print(f"❓ [{q_id}] ({st['type']} - Run {run_idx + 1}) {st['q_text']}", file=sys.stderr)
                        print("=" * 50, file=sys.stderr)
                        print("엔진의 답변을 입력하세요. 입력이 끝나면 빈 줄에서 Ctrl+D를 누르세요:", file=sys.stderr)
                        lines = []
                        try:
                            for line in sys.stdin:
                                lines.append(line)
                            answer = "".join(lines).strip()
                        except KeyboardInterrupt:
                            print("\n👋 평가가 중단되었습니다.", file=sys.stderr)
                            sys.exit(0)

                # 채점 (검색 컨텍스트를 함께 전달 → 환각 판정 근거)
                if not answer:
                    score_data = {"score": 1, "reason": "답변이 제출되지 않았습니다."}
                else:
                    grade_context = context if context is not None else ""
                    if args.interactive_agent:
                        score_data = get_agent_graded(st["q_text"], q, answer, grade_context)
                    else:
                        score_data = manual_grade(st["q_text"], q, answer, grade_context)

                recall, missing = compute_retrieval_recall(context, reference_notes)
                st_runs.append({
                    "run_idx": run_idx + 1,
                    "answer": answer,
                    "score": score_data["score"],
                    "reason": score_data["reason"],
                    "retrieval_recall": recall,
                    "retrieval_missing": missing,
                })

                if not args.answers:
                    answers_dict[run_key] = answer

            sub_test_results.append({"q_text": st["q_text"], "type": st["type"], "runs": st_runs})

        # 원본 질문 런 → 헤드라인은 평균 사용
        orig_runs = [r for r in sub_test_results if r["type"] == "original"][0]["runs"]
        orig_scores = [r["score"] for r in orig_runs]
        orig_mean, orig_std = calc_stats(orig_scores)

        # 검색 재현율: 원본 런들 중 컨텍스트가 있는 것들의 평균
        recall_vals = [r["retrieval_recall"] for r in orig_runs if r["retrieval_recall"] is not None]
        q_recall = sum(recall_vals) / len(recall_vals) if recall_vals else None
        # 누락 문서는 run1 기준(있으면)
        q_missing = next((r["retrieval_missing"] for r in orig_runs if r["retrieval_missing"] is not None), None)

        base_answer = orig_runs[0]["answer"]
        base_reason = orig_runs[0]["reason"]

        # 의미론적 일관성 (변형 질문 run1 vs 원본 평균)
        para_results = [r for r in sub_test_results if r["type"] == "paraphrased"]
        para_run1_scores = [r["runs"][0]["score"] for r in para_results]
        para_scores = [orig_mean] + para_run1_scores
        para_mean, _ = calc_stats(para_scores) if para_scores else (orig_mean, 0.0)
        # 일치도: 변형 질문 점수가 원본 '반올림 평균'과 같은 비율
        base_round = round(orig_mean)
        match_pool = [round(orig_mean)] + para_run1_scores
        matches = sum(1 for s in match_pool if s == base_round)
        semantic_robustness_pct = (matches / len(match_pool)) * 100 if match_pool else 100.0

        para_formatted = [{
            "q_text": pr["q_text"],
            "score": pr["runs"][0]["score"],
            "reason": pr["runs"][0]["reason"],
            "answer": pr["runs"][0]["answer"],
        } for pr in para_results]

        results.append({
            "id": q_id,
            "axis": axis,
            "question": q["question"],
            "ground_truth": q["ground_truth"],
            "reference_notes": reference_notes,
            "answer": base_answer,
            "score": orig_mean,
            "reason": base_reason,
            "all_runs": orig_runs if len(orig_runs) > 1 else [],
            "stability_mean": orig_mean,
            "stability_std": orig_std,
            "retrieval_recall": q_recall,
            "retrieval_missing": q_missing,
            "paraphrased_results": para_formatted if para_formatted else None,
            "semantic_avg": para_mean,
            "semantic_robustness_pct": semantic_robustness_pct,
        })

    # 4. 답변/컨텍스트 캐시 저장
    if not args.answers and args.engine:
        try:
            with open(f"engines/{args.engine}/answers.json", "w", encoding="utf-8") as f:
                json.dump(answers_dict, f, ensure_ascii=False, indent=2)
            print(f"💾 생성된 엔진 답변이 기록되었습니다: engines/{args.engine}/answers.json", file=sys.stderr)
            with open(f"engines/{args.engine}/contexts.json", "w", encoding="utf-8") as f:
                json.dump(contexts_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 답변/컨텍스트 캐시 저장 실패: {e}", file=sys.stderr)

    # 5. 요약 + 보고서 + 결과 캐시
    summary = summarize(results, args.stability_runs, eval_method, answer_source)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generate_report(results, summary, args.output, generated_at=generated_at)
    cache_path = f"{os.path.splitext(args.output)[0]}.results.json"
    dump_results_cache(results, summary, cache_path, generated_at=generated_at)
    print_cli_summary(summary)


if __name__ == "__main__":
    main()
