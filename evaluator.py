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


def compute_semantic_consistency(orig_found_labels, para_found_labels_list):
    """변형 질의가 원 질의에서 회수된 사실을 얼마나 보존하는지(0.0~1.0).
    변형이 없으면 None."""
    if not para_found_labels_list:
        return None
    orig = set(orig_found_labels)
    scores = []
    for para in para_found_labels_list:
        if not orig:
            scores.append(1.0)
        else:
            scores.append(len(orig & set(para)) / len(orig))
    return sum(scores) / len(scores)


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
# 집계 / 실행
# ---------------------------------------------------------------------------

def summarize(results):
    total_facts = sum(r["n_facts"] for r in results)
    total_found = sum(r["n_found"] for r in results)
    recalls = [r["retrieval_recall"] for r in results if r.get("retrieval_recall") is not None]
    consis = [r["semantic_consistency"] for r in results if r.get("semantic_consistency") is not None]
    axis_scores = {}
    for r in results:
        a = axis_scores.setdefault(r["axis"], {"found": 0, "facts": 0})
        a["found"] += r["n_found"]
        a["facts"] += r["n_facts"]
    return {
        "total_facts": total_facts,
        "total_found": total_found,
        "micro_coverage": (total_found / total_facts) if total_facts else 0.0,
        "avg_retrieval_recall": (sum(recalls) / len(recalls)) if recalls else None,
        "avg_semantic_consistency": (sum(consis) / len(consis)) if consis else None,
        "axis_scores": axis_scores,
    }


def build_results(questions, engine):
    results = []
    for q in questions:
        qid = q["id"]
        key_facts = q.get("key_facts", [])
        print(f"🔍 [{qid}] {engine} 검색 (원 질의)...", file=sys.stderr)
        ctx = run_engine_search(engine, q["question"])
        coverage, facts = compute_keyfact_coverage(ctx, key_facts)
        recall, missing = compute_retrieval_recall(ctx, q.get("reference_notes", []))
        orig_found = {f["label"] for f in facts if f["found"]}

        paraphrased = []
        para_found_sets = []
        for pq in q.get("paraphrased_questions", []):
            print(f"🔍 [{qid}] {engine} 검색 (변형)...", file=sys.stderr)
            pctx = run_engine_search(engine, pq)
            pcov, pfacts = compute_keyfact_coverage(pctx, key_facts)
            pset = {f["label"] for f in pfacts if f["found"]}
            para_found_sets.append(pset)
            paraphrased.append({"q_text": pq, "coverage": pcov, "n_found": len(pset)})

        consistency = compute_semantic_consistency(orig_found, para_found_sets)
        n_found = sum(1 for f in facts if f["found"])
        results.append({
            "id": qid,
            "axis": q["axis"],
            "question": q["question"],
            "ground_truth": q.get("ground_truth", ""),
            "reference_notes": q.get("reference_notes", []),
            "key_facts": facts,
            "n_facts": len(key_facts),
            "n_found": n_found,
            "key_fact_coverage": coverage if coverage is not None else 0.0,
            "retrieval_recall": recall,
            "retrieval_missing": missing,
            "semantic_consistency": consistency,
            "paraphrased": paraphrased,
        })
    return results


def cmd_run(args):
    questions = load_questions(args.questions)
    results = build_results(questions, args.engine)
    summary = summarize(results)
    output = args.output or f"engines/{args.engine}/report.md"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generate_report(results, summary, output, args.engine, generated_at=generated_at)
    cache_path = f"{os.path.splitext(output)[0]}.results.json"
    dump_results_cache(results, summary, args.engine, cache_path, generated_at=generated_at)
    print_cli_summary(summary)


# ---------------------------------------------------------------------------
# 보고서 렌더링 (Task 6 에서 재작성 예정)
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
    parser = argparse.ArgumentParser(description="세컨드 브레인 검색 엔진 벤치마크 평가기 (결정론적 검색 측정)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="검색 실행 → 3지표 계산 → report.md + report.results.json")
    p.add_argument("--engine", required=True, help="대상 검색 엔진(어댑터 폴더) 이름")
    p.add_argument("--questions", default=DEFAULT_QUESTIONS_PATH)
    p.add_argument("--output", help="보고서 경로 (기본 engines/<engine>/report.md)")
    p.set_defaults(func=cmd_run)

    r = sub.add_parser("render", help="채점 결과 캐시(report.results.json)로부터 보고서만 재생성")
    r.add_argument("source", help="report.results.json 경로")
    r.add_argument("--output", help="보고서 경로 (기본 캐시와 같은 폴더의 report.md)")
    r.set_defaults(func=cmd_render)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
