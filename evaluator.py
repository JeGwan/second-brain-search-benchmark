#!/usr/bin/env python3
"""
세컨드 브레인 검색 엔진 벤치마크 평가기 (Second Brain Search Engine Benchmark Evaluator)

설계 원칙 (v4 — 대화형 프로토콜 폐기):
  역할을 명확히 나눈다.
   * 결정론적인 작업은 이 파이썬 평가기가 수행한다: 검색 어댑터 실행, 프롬프트 생성,
     검색 재현율 계산, 점수 집계, 보고서 렌더링.
   * '에이전트가 필요한' 작업(격리 서브에이전트로 답변/채점)은 평가기가 직접 하지 않고,
     SKILL.md 가이드에 따라 오케스트레이터 에이전트가 수행한다.
   * 둘은 단일 작업 파일(engines/<engine>/run.json)을 통해 주고받는다. (stdin 중계 없음)

파이프라인:
  1) prepare        : 검색 실행 → run.json 에 컨텍스트/재현율/답변프롬프트 기록
  2) (에이전트)      : 격리 서브에이전트로 답변 생성 → run.json 의 answer 채움
  3) grade-prompts  : 답변을 받아 컨텍스트 포함 채점 프롬프트 생성 → run.json 기록
  4) (에이전트)      : 격리 서브에이전트로 채점 → run.json 의 score/reason 채움
  5) assemble       : run.json 집계 → report.md + report.results.json
  (render)          : 채점 결과 캐시(report.results.json)로부터 보고서만 재생성

핵심 채점 원칙:
  - 채점 프롬프트는 '검색된 컨텍스트'를 포함한다. 환각 판정은 정답이 아니라 컨텍스트 기준.
  - reference_notes 대비 검색 재현율을 별도 계산해 검색 실패와 생성 실패를 분리한다.
  - 헤드라인 점수는 stability-runs '평균'.
  - API 키를 사용하지 않는다.
"""

import os
import re
import sys
import json
import math
import argparse
import subprocess
import unicodedata
from datetime import datetime

DEFAULT_QUESTIONS_PATH = "questions.json"


def normalize(text):
    """매칭용 정규화: NFKC → 소문자 → 천단위 콤마 제거 → 공백 정리."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.lower()
    t = re.sub(r"(?<=\d),(?=\d)", "", t)      # 1,000 → 1000
    t = re.sub(r"\s+", " ", t).strip()
    return t

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
        print(f"❌ 에러: 질문지 파일을 찾을 수 없습니다. 경로: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"❌ 에러: 질문지 파일이 올바른 JSON 형식이 아닙니다. 경로: {path}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# 프롬프트 단일 소스 (Single source of truth)
# ---------------------------------------------------------------------------

def build_answer_prompt(question_text, context):
    """답변 생성 프롬프트. 격리 답변 서브에이전트에 그대로 전달한다."""
    return f"""[답변 지시사항]
제시된 컨텍스트(Retrieved Context)만을 바탕으로 질문에 한국어로 정확하게 답변하세요.
절대로 외부 지식이나 상상력을 이용해 지어내거나(환각), 무리하게 추론하지 마세요.
제시된 컨텍스트에 정보가 부족하다면, 어떤 정보가 누락되어 답변할 수 없는지 구체적으로 기술하세요.
파일 경로나 시스템 위치를 추측해서 적지 마세요. 어떤 도구도 사용하지 말고 오직 답변 텍스트만 출력하세요.

[질문]
{question_text}

[검색된 컨텍스트]
{context}
"""


def build_grade_prompt(question_text, ground_truth, rubric_str, answer, context):
    """채점 프롬프트. 환각 판정은 '제시된 컨텍스트' 기준으로만 이루어진다."""
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
어떤 도구도 사용하지 말고, 아래 JSON 형식만 출력하세요.

{precision_rule}
질문: {question_text}
정답: {ground_truth}

루브릭:
{rubric_str}

후보 답변:
{answer}

출력 형식 (다른 서두나 백틱 없이 이 JSON 만):
{{"score": <1|2|3>, "reason": "<한글 채점 사유, 감점 여부 포함>"}}
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
    포함되었는지 비율(0.0~1.0)과 누락 문서 목록을 반환한다."""
    if context is None or not reference_notes:
        return None, None
    present, missing = [], []
    for note in reference_notes:
        stem = note[:-3] if note.endswith(".md") else note
        core = re.sub(r"^\d+[_-]", "", stem)
        if stem in context or (core and core in context):
            present.append(note)
        else:
            missing.append(note)
    return len(present) / len(reference_notes), missing


def compute_keyfact_coverage(context, key_facts):
    """문항의 key_facts 각각이 검색 컨텍스트에 (정규화 후) 등장하는지 매칭.
    반환: (coverage 0.0~1.0 | None, facts 상세 목록)."""
    if not key_facts:
        return None, []
    norm_ctx = normalize(context or "")
    facts = []
    found_count = 0
    for kf in key_facts:
        matched = None
        for alias in kf.get("aliases", []):
            na = normalize(alias)
            if na and na in norm_ctx:
                matched = alias
                break
        if matched is not None:
            found_count += 1
        facts.append({"label": kf["label"], "found": matched is not None,
                      "matched_alias": matched})
    return found_count / len(key_facts), facts


def run_engine_search(engine, query):
    search_script = f"engines/{engine}/search.py"
    if not os.path.exists(search_script):
        print(f"❌ 에러: 엔진 검색 스크립트를 찾을 수 없습니다. 경로: {search_script}", file=sys.stderr)
        sys.exit(1)
    try:
        result = subprocess.run(["python3", search_script, query], capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ 엔진 검색 실행 오류: {e.stderr}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# 통계 / 집계
# ---------------------------------------------------------------------------

def calc_stats(scores):
    n = len(scores)
    if n == 0:
        return 0.0, 0.0
    mean = sum(scores) / n
    return mean, math.sqrt(sum((x - mean) ** 2 for x in scores) / n)


def summarize(results, stability_runs, eval_method, answer_source):
    axis_scores = {}
    total_score = 0.0
    stds, recalls = [], []
    for r in results:
        a = axis_scores.setdefault(r["axis"], {"score": 0.0, "max": 0, "count": 0})
        a["score"] += r["score"]
        a["max"] += 3
        a["count"] += 1
        total_score += r["score"]
        stds.append(r["stability_std"])
        if r.get("retrieval_recall") is not None:
            recalls.append(r["retrieval_recall"])
    max_score = len(results) * 3
    return {
        "total_score": total_score,
        "max_score": max_score,
        "percentage": (total_score / max_score) * 100 if max_score else 0.0,
        "eval_method": eval_method,
        "answer_source": answer_source,
        "axis_scores": axis_scores,
        "stability_runs": stability_runs,
        "avg_stability_std": sum(stds) / len(stds) if stds else 0.0,
        "avg_retrieval_recall": sum(recalls) / len(recalls) if recalls else None,
    }


# ---------------------------------------------------------------------------
# 보고서 렌더링
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

    has_recall = any(r.get("retrieval_recall") is not None for r in results)
    report_md += """
## 3. 검색 재현율 분석 (Retrieval Recall — 검색 실패 vs 생성 실패 분리)
정답 도출에 필요한 원본 문서(reference_notes)가 검색 단계에서 실제로 회수되었는지 측정합니다.
재현율이 낮으면 점수 하락의 책임은 '생성/추론'이 아니라 '검색'에 있습니다.
"""
    if not has_recall:
        report_md += "\n> 이 보고서에는 검색 컨텍스트가 보존되지 않아 검색 재현율을 계산할 수 없습니다.\n"
    else:
        report_md += "| 문항 ID | 필요한 문서 수 | 검색 재현율 | 누락된 문서 |\n| :---: | :---: | :---: | :--- |\n"
        for r in results:
            if r.get("retrieval_recall") is None:
                report_md += f"| {r['id']} | - | N/A | - |\n"
            else:
                missing = ", ".join(r.get("retrieval_missing") or []) or "없음"
                report_md += f"| {r['id']} | {len(r.get('reference_notes') or [])} | {r['retrieval_recall'] * 100:.0f}% | {missing} |\n"

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

    report_md += "\n## 5. 문항별 세부 결과 (Detailed Results)\n"
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

    parent = os.path.dirname(output_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"🎉 벤치마크 보고서가 생성되었습니다: {output_path}", file=sys.stderr)


def dump_results_cache(results, summary, path, generated_at=None):
    payload = {
        "meta": {
            "generated_at": generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stability_runs": summary["stability_runs"],
            "eval_method": summary["eval_method"],
            "answer_source": summary["answer_source"],
        },
        "results": results,
    }
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"💾 채점 결과 캐시를 저장했습니다 (재현용): {path}", file=sys.stderr)


def print_cli_summary(summary):
    print("\n" + "=" * 40, file=sys.stderr)
    print("📊 벤치마크 평가 결과 요약", file=sys.stderr)
    print(f"- 총점(평균): {summary['total_score']:.1f} / {summary['max_score']} ({summary['percentage']:.1f}%)", file=sys.stderr)
    if summary.get("avg_retrieval_recall") is not None:
        print(f"- 평균 검색 재현율: {summary['avg_retrieval_recall'] * 100:.1f}%", file=sys.stderr)
    for axis, data in summary["axis_scores"].items():
        pct = (data["score"] / data["max"]) * 100 if data["max"] else 0
        print(f"  * {axis}: {data['score']:.1f} / {data['max']} ({pct:.1f}%)", file=sys.stderr)
    print("=" * 40, file=sys.stderr)


# ---------------------------------------------------------------------------
# run.json 입출력
# ---------------------------------------------------------------------------

def run_file_path(args):
    if args.run_file:
        return args.run_file
    if args.engine:
        return f"engines/{args.engine}/run.json"
    print("❌ 에러: --engine 또는 --run-file 이 필요합니다.", file=sys.stderr)
    sys.exit(1)


def load_run(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ 에러: 작업 파일을 찾을 수 없습니다: {path} (먼저 prepare 를 실행하세요)", file=sys.stderr)
        sys.exit(1)


def save_run(run, path):
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 1) prepare
# ---------------------------------------------------------------------------

def cmd_prepare(args):
    questions = load_questions(args.questions)
    path = run_file_path(args)
    items = []
    for q in questions:
        qid = q["id"]
        sub_tests = [{"key": qid, "type": "original", "text": q["question"]}]
        for idx, pq in enumerate(q.get("paraphrased_questions", [])):
            sub_tests.append({"key": f"{qid}_para{idx + 1}", "type": "paraphrased", "text": pq})
        for st in sub_tests:
            print(f"🔍 [{qid}] ({st['type']}) {args.engine} 검색...", file=sys.stderr)
            context = sanitize_context(run_engine_search(args.engine, st["text"]))
            recall, missing = compute_retrieval_recall(context, q.get("reference_notes", []))
            for run_idx in range(1, args.stability_runs + 1):
                items.append({
                    "key": f"{st['key']}_run{run_idx}" if args.stability_runs > 1 else st["key"],
                    "qid": qid,
                    "type": st["type"],
                    "run_idx": run_idx,
                    "question": st["text"],
                    "original_question": q["question"],
                    "axis": q["axis"],
                    "ground_truth": q["ground_truth"],
                    "reference_notes": q.get("reference_notes", []),
                    "rubric": q["evaluation_rubric"],
                    "context": context,
                    "retrieval_recall": recall,
                    "retrieval_missing": missing,
                    "answer_prompt": build_answer_prompt(st["text"], context),
                    "answer": None,
                    "grade_prompt": None,
                    "score": None,
                    "reason": None,
                })
    run = {
        "meta": {
            "engine": args.engine,
            "stability_runs": args.stability_runs,
            "questions_path": args.questions,
            "answer_source": args.answer_source or f"{args.engine} 검색 + 격리 답변 생성",
        },
        "items": items,
    }
    save_run(run, path)
    n_ans = len(items)
    print(f"\n✅ prepare 완료: {path} ({n_ans}개 항목)", file=sys.stderr)
    print("다음 단계: 각 항목의 'answer_prompt' 로 격리 답변 서브에이전트를 띄워 'answer' 를 채운 뒤,", file=sys.stderr)
    print("           grade-prompts 를 실행하세요. (SKILL.md 참고)", file=sys.stderr)


# ---------------------------------------------------------------------------
# 3) grade-prompts
# ---------------------------------------------------------------------------

def cmd_grade_prompts(args):
    path = run_file_path(args)
    run = load_run(path)
    missing_ans = [it["key"] for it in run["items"] if not it.get("answer")]
    if missing_ans:
        print(f"❌ 에러: 아직 답변(answer)이 없는 항목이 있습니다: {missing_ans}", file=sys.stderr)
        print("   모든 항목에 격리 답변 서브에이전트 결과를 채운 뒤 다시 실행하세요.", file=sys.stderr)
        sys.exit(1)
    for it in run["items"]:
        it["grade_prompt"] = build_grade_prompt(
            it["question"], it["ground_truth"], rubric_to_str(it["rubric"]), it["answer"], it.get("context") or "")
    save_run(run, path)
    print(f"✅ grade-prompts 완료: {path} ({len(run['items'])}개 채점 프롬프트 생성)", file=sys.stderr)
    print("다음 단계: 각 항목의 'grade_prompt' 로 격리 채점 서브에이전트를 띄워 'score'/'reason' 을 채운 뒤,", file=sys.stderr)
    print("           assemble 을 실행하세요.", file=sys.stderr)


# ---------------------------------------------------------------------------
# 5) assemble
# ---------------------------------------------------------------------------

def cmd_assemble(args):
    path = run_file_path(args)
    run = load_run(path)
    items = run["items"]
    ungraded = [it["key"] for it in items if it.get("score") is None]
    if ungraded:
        print(f"❌ 에러: 아직 채점(score)이 없는 항목이 있습니다: {ungraded}", file=sys.stderr)
        sys.exit(1)

    meta = run.get("meta", {})
    stability_runs = meta.get("stability_runs", 1)

    # qid 순서 보존
    order = []
    by_qid = {}
    for it in items:
        if it["qid"] not in by_qid:
            by_qid[it["qid"]] = []
            order.append(it["qid"])
        by_qid[it["qid"]].append(it)

    results = []
    for qid in order:
        group = by_qid[qid]
        originals = sorted([it for it in group if it["type"] == "original"], key=lambda x: x["run_idx"])
        orig_scores = [it["score"] for it in originals]
        omean, ostd = calc_stats(orig_scores)
        base = originals[0]

        recall_vals = [it["retrieval_recall"] for it in originals if it["retrieval_recall"] is not None]
        q_recall = sum(recall_vals) / len(recall_vals) if recall_vals else None

        # 변형 질문: 각 변형의 run1 점수
        paras = {}
        for it in group:
            if it["type"] == "paraphrased":
                paras.setdefault(it["qid"] + "|" + it["question"], []).append(it)
        para_formatted, para_run1_scores = [], []
        for key in sorted(paras.keys()):
            runs = sorted(paras[key], key=lambda x: x["run_idx"])
            r1 = runs[0]
            para_run1_scores.append(r1["score"])
            para_formatted.append({"q_text": r1["question"], "score": r1["score"],
                                   "reason": r1["reason"], "answer": r1["answer"]})

        base_round = round(omean)
        pool = [base_round] + para_run1_scores
        sem_pct = (sum(1 for s in pool if s == base_round) / len(pool)) * 100 if pool else 100.0
        para_mean, _ = calc_stats([omean] + para_run1_scores)

        results.append({
            "id": qid,
            "axis": base["axis"],
            "question": base.get("original_question", base["question"]),
            "ground_truth": base["ground_truth"],
            "reference_notes": base.get("reference_notes", []),
            "answer": base["answer"],
            "score": omean,
            "reason": base["reason"],
            "all_runs": [{"run_idx": it["run_idx"], "answer": it["answer"],
                          "score": it["score"], "reason": it["reason"]} for it in originals],
            "stability_mean": omean,
            "stability_std": ostd,
            "retrieval_recall": q_recall,
            "retrieval_missing": base.get("retrieval_missing"),
            "paraphrased_results": para_formatted if para_formatted else None,
            "semantic_avg": para_mean,
            "semantic_robustness_pct": sem_pct,
        })

    eval_method = meta.get("eval_method", "에이전트 격리 채점 (서브에이전트 오케스트레이션)")
    answer_source = meta.get("answer_source", "엔진 검색 + 격리 답변 생성")
    summary = summarize(results, stability_runs, eval_method, answer_source)

    output = args.output or (f"engines/{meta.get('engine')}/report.md" if meta.get("engine") else "benchmark_report.md")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generate_report(results, summary, output, generated_at=generated_at)
    cache_path = f"{os.path.splitext(output)[0]}.results.json"
    dump_results_cache(results, summary, cache_path, generated_at=generated_at)
    print_cli_summary(summary)


# ---------------------------------------------------------------------------
# render (채점 결과 캐시 → 보고서)
# ---------------------------------------------------------------------------

def cmd_render(args):
    with open(args.source, "r", encoding="utf-8") as f:
        payload = json.load(f)
    results = payload["results"]
    meta = payload.get("meta", {})
    summary = summarize(results, meta.get("stability_runs", 1),
                        meta.get("eval_method", "캐시 재현"), meta.get("answer_source", "캐시 재현"))
    output = args.output or os.path.join(os.path.dirname(args.source) or ".", "report.md")
    generate_report(results, summary, output, generated_at=meta.get("generated_at"))
    print_cli_summary(summary)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="세컨드 브레인 검색 엔진 벤치마크 평가기 (대화형 프로토콜 없음)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare", help="검색 실행 → run.json 에 컨텍스트/재현율/답변프롬프트 기록")
    p.add_argument("--engine", required=True, help="대상 검색 엔진(어댑터 폴더) 이름")
    p.add_argument("--questions", default=DEFAULT_QUESTIONS_PATH)
    p.add_argument("--stability-runs", type=int, default=1, help="각 질문 반복 실행 횟수(결정론적 일관성)")
    p.add_argument("--run-file", help="작업 파일 경로 (기본 engines/<engine>/run.json)")
    p.add_argument("--answer-source", help="보고서에 기록할 답변 출처 설명(예: 답변 모델명)")
    p.set_defaults(func=cmd_prepare)

    g = sub.add_parser("grade-prompts", help="답변을 받아 컨텍스트 포함 채점 프롬프트 생성")
    g.add_argument("--engine")
    g.add_argument("--run-file")
    g.set_defaults(func=cmd_grade_prompts)

    a = sub.add_parser("assemble", help="run.json 집계 → report.md + report.results.json")
    a.add_argument("--engine")
    a.add_argument("--run-file")
    a.add_argument("--output", help="보고서 경로 (기본 engines/<engine>/report.md)")
    a.set_defaults(func=cmd_assemble)

    r = sub.add_parser("render", help="채점 결과 캐시(report.results.json)로부터 보고서만 재생성")
    r.add_argument("source", help="report.results.json 경로")
    r.add_argument("--output", help="보고서 경로 (기본 캐시와 같은 폴더의 report.md)")
    r.set_defaults(func=cmd_render)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
