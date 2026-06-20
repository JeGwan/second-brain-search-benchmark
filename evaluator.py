#!/usr/bin/env python3
"""
세컨드 브레인 검색 엔진 벤치마크 평가기 (Second Brain Search Engine Benchmark Evaluator)

목적:
  비정형 지식 뭉치(세컨드 브레인)에 대한 검색 레이어 성능을 결정론적으로 측정한다.

설계 원칙:
  평가기는 LLM/에이전트 없이 결정론적인 일만 한다.
   * 검색 어댑터(engines/<engine>/search.py)를 실행한다.
   * 핵심사실 커버리지·문서 재현율·의미론적 일관성을 계산한다.
   * 보고서(report.md)와 결과 캐시(report.results.json)를 생성한다.

명령:
  run    : 검색 → 3지표 계산 → report.md + report.results.json 생성
  render : 결과 캐시(report.results.json)로부터 report.md 만 재생성

지표:
  - 핵심사실 커버리지: 문항별 key_facts(알리아스 목록)를 정규화 부분문자열로
    검색 컨텍스트에 매칭한다. 헤드라인은 마이크로 평균.
  - 문서 재현율: reference_notes 대비 회수된 문서 비율.
  - 의미론적 일관성: 변형 질의로 검색했을 때 원 질의에서 회수된 사실의 보존율.

  API 키/LLM/네트워크(검색 어댑터 제외)/무작위 요소가 없으므로,
  어떤 에이전트 환경에서 돌려도 동일한 숫자가 나온다.
"""

import os
import re
import sys
import json
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

def generate_report(results, summary, output_path, engine, generated_at=None):
    ts = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = f"""# 📊 세컨드 브레인 검색 엔진 벤치마크 결과 보고서

## 1. 종합 요약 (Summary)
*   **평가 대상 엔진**: {engine}
*   **평가 일시**: {ts}
*   **핵심사실 커버리지 (헤드라인, 마이크로 평균)**: **{summary['micro_coverage'] * 100:.1f}%** ({summary['total_found']}/{summary['total_facts']} 사실 회수)
"""
    if summary.get("avg_retrieval_recall") is not None:
        md += f"*   **평균 문서 재현율 (Avg Retrieval Recall)**: {summary['avg_retrieval_recall'] * 100:.1f}%\n"
    if summary.get("avg_semantic_consistency") is not None:
        md += f"*   **평균 의미론적 일관성 (Avg Semantic Consistency)**: {summary['avg_semantic_consistency'] * 100:.1f}%\n"
    md += """
> **측정 모델**: 검색 레이어만 결정론적으로 측정합니다. 핵심사실 커버리지는 문항별
> 핵심 사실(key_facts)이 검색 컨텍스트에 등장했는지를 직접 매칭한 값으로, LLM 답변/채점이
> 개입하지 않아 어떤 에이전트 환경에서 돌려도 동일한 숫자가 나옵니다.

## 2. 핵심사실 커버리지 (문항별)
| 문항 ID | 평가 영역 | 회수 사실 | 전체 사실 | 커버리지 |
| :---: | :--- | :---: | :---: | :---: |
"""
    for r in results:
        md += f"| {r['id']} | {r['axis']} | {r['n_found']} | {r['n_facts']} | {r['key_fact_coverage'] * 100:.0f}% |\n"

    md += """
## 3. 검색 재현율 분석 (문서 단위 vs 사실 단위)
문서 재현율은 정답 근거 문서(reference_notes)가 회수됐는지, 핵심사실 커버리지는 그 문서의
정답 줄(청크)까지 회수됐는지를 봅니다. 재현율 100%인데 커버리지가 낮으면 '문서는 찾았으나
청크 경계가 정답을 놓친' 경우입니다.
| 문항 ID | 필요 문서 수 | 문서 재현율 | 핵심사실 커버리지 | 누락 문서 |
| :---: | :---: | :---: | :---: | :--- |
"""
    for r in results:
        if r.get("retrieval_recall") is None:
            md += f"| {r['id']} | - | N/A | {r['key_fact_coverage'] * 100:.0f}% | - |\n"
        else:
            missing = ", ".join(r.get("retrieval_missing") or []) or "없음"
            md += f"| {r['id']} | {len(r.get('reference_notes') or [])} | {r['retrieval_recall'] * 100:.0f}% | {r['key_fact_coverage'] * 100:.0f}% | {missing} |\n"

    md += """
## 4. 의미론적 일관성 (변형 질의 강건성)
질문 표현이 달라져도 원 질의에서 회수한 핵심 사실을 변형 질의에서도 회수하는지 측정합니다.
| 문항 ID | 원 질의 커버리지 | 변형 질의 평균 커버리지 | 일관성 |
| :---: | :---: | :---: | :---: |
"""
    for r in results:
        if not r.get("paraphrased"):
            md += f"| {r['id']} | {r['key_fact_coverage'] * 100:.0f}% | - | N/A |\n"
            continue
        pcovs = [p["coverage"] for p in r["paraphrased"] if p["coverage"] is not None]
        pavg = (sum(pcovs) / len(pcovs) * 100) if pcovs else 0.0
        cons = r["semantic_consistency"]
        cons_s = f"{cons * 100:.0f}%" if cons is not None else "N/A"
        md += f"| {r['id']} | {r['key_fact_coverage'] * 100:.0f}% | {pavg:.0f}% | {cons_s} |\n"

    md += "\n## 5. 문항별 세부 결과 (Detailed Results)\n"
    for r in results:
        md += f"\n### 📝 {r['id']} ({r['axis']})\n"
        md += f"*   **질문**: {r['question']}\n"
        md += f"*   **정답 (참고용)**: {r['ground_truth']}\n"
        md += f"*   **핵심사실 커버리지**: {r['n_found']}/{r['n_facts']} ({r['key_fact_coverage'] * 100:.0f}%)\n"
        for f in r["key_facts"]:
            mark = "✅" if f["found"] else "❌"
            via = f" (매칭: `{f['matched_alias']}`)" if f["found"] else ""
            md += f"    *   {mark} {f['label']}{via}\n"
        if r.get("retrieval_recall") is not None:
            missing = ", ".join(r.get("retrieval_missing") or []) or "없음"
            md += f"*   **문서 재현율**: {r['retrieval_recall'] * 100:.0f}% (누락: {missing})\n"
        if r.get("paraphrased"):
            md += "*   **변형 질의 결과**:\n"
            for p in r["paraphrased"]:
                pc = f"{p['coverage'] * 100:.0f}%" if p["coverage"] is not None else "N/A"
                md += f"    *   \"{p['q_text']}\" → 커버리지 {pc}\n"
        md += "\n---\n"

    parent = os.path.dirname(output_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"🎉 벤치마크 보고서가 생성되었습니다: {output_path}", file=sys.stderr)


def dump_results_cache(results, summary, engine, path, generated_at=None):
    payload = {
        "meta": {
            "engine": engine,
            "generated_at": generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "eval_method": "결정론적 검색 측정 (핵심사실 커버리지)",
        },
        "summary": summary,
        "results": results,
    }
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"💾 결과 캐시를 저장했습니다 (render 재현용): {path}", file=sys.stderr)


def print_cli_summary(summary):
    print("\n" + "=" * 40, file=sys.stderr)
    print("📊 벤치마크 평가 결과 요약 (결정론적 검색 측정)", file=sys.stderr)
    print(f"- 핵심사실 커버리지(헤드라인): {summary['micro_coverage'] * 100:.1f}% "
          f"({summary['total_found']}/{summary['total_facts']})", file=sys.stderr)
    if summary.get("avg_retrieval_recall") is not None:
        print(f"- 평균 문서 재현율: {summary['avg_retrieval_recall'] * 100:.1f}%", file=sys.stderr)
    if summary.get("avg_semantic_consistency") is not None:
        print(f"- 평균 의미론적 일관성: {summary['avg_semantic_consistency'] * 100:.1f}%", file=sys.stderr)
    for axis, d in summary["axis_scores"].items():
        pct = (d["found"] / d["facts"] * 100) if d["facts"] else 0.0
        print(f"  * {axis}: {d['found']}/{d['facts']} ({pct:.1f}%)", file=sys.stderr)
    print("=" * 40, file=sys.stderr)


def cmd_render(args):
    with open(args.source, "r", encoding="utf-8") as f:
        payload = json.load(f)
    results = payload["results"]
    meta = payload.get("meta", {})
    summary = payload.get("summary") or summarize(results)
    engine = meta.get("engine", "?")
    output = args.output or os.path.join(os.path.dirname(args.source) or ".", "report.md")
    generate_report(results, summary, output, engine, generated_at=meta.get("generated_at"))
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

    r = sub.add_parser("render", help="측정 결과 캐시(report.results.json)로부터 보고서만 재생성")
    r.add_argument("source", help="report.results.json 경로")
    r.add_argument("--output", help="보고서 경로 (기본 캐시와 같은 폴더의 report.md)")
    r.set_defaults(func=cmd_render)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
