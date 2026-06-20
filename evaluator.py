#!/usr/bin/env python3
"""
세컨드 브레인 검색 엔진 벤치마크 평가기 (Second Brain Search Engine Benchmark Evaluator)
이 스크립트는 검색 엔진의 답변을 받아 평가 기준(루브릭)에 따라 채점하고 보고서를 생성합니다.
에이전트와의 인터랙티브 격리 모드(--interactive-agent)를 지원합니다.
"""

import os
import sys
import json
import argparse
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

# 평가 질문 파일 경로 (기본값)
DEFAULT_QUESTIONS_PATH = "questions.json"
DEFAULT_REPORT_PATH = "benchmark_report.md"

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

def call_gemini_api(api_key, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text.strip())
    except urllib.error.HTTPError as e:
        print(f"⚠️ Gemini API 호출 오류 (HTTP {e.code}): {e.read().decode('utf-8')}")
        return None
    except Exception as e:
        print(f"⚠️ API 호출 중 오류 발생: {e}")
        return None

def call_openai_api(api_key, prompt):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a precise evaluator that outputs JSON only."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"}
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["choices"][0]["message"]["content"]
            return json.loads(text.strip())
    except urllib.error.HTTPError as e:
        print(f"⚠️ OpenAI API 호출 오류 (HTTP {e.code}): {e.read().decode('utf-8')}")
        return None
    except Exception as e:
        print(f"⚠️ API 호출 중 오류 발생: {e}")
        return None

def llm_grade(question_data, answer, api_key, provider):
    rubric_str = "\n".join([f"- {score}점: {desc}" for score, desc in question_data["evaluation_rubric"].items()])
    prompt = f"""
You are an expert AI evaluator assessing the quality of a Second Brain Search Engine's answer.
Analyze the candidate answer based on the Question, Ground Truth, and Rubric.

[Question]
{question_data['question']}

[Ground Truth]
{question_data['ground_truth']}

[Rubric]
{rubric_str}

[Candidate Answer to evaluate]
{answer}

Evaluate the candidate answer and provide your judgment strictly in the following JSON format:
{{
  "score": <int: 1, 2, or 3>,
  "reason": "<string: concise explanation in Korean why this score was given based on the rubric>"
}}
Response must be valid JSON only. Do not wrap in markdown or backticks.
"""
    if provider == "gemini":
        return call_gemini_api(api_key, prompt)
    else:
        return call_openai_api(api_key, prompt)

def get_agent_graded(q, answer):
    rubric_str = "\n".join([f"- {score}점: {desc}" for score, desc in q["evaluation_rubric"].items()])
    prompt = f"""[채점 지시사항]
제시된 질문, 정답(Ground Truth), 채점 루브릭을 보고 후보 답변(Candidate Answer)을 평가하세요.
반드시 루브릭 기준만을 준수하여 1점, 2점, 혹은 3점으로 채점하고 그 이유를 작성해 주세요.

질문: {q['question']}
정답: {q['ground_truth']}

루브릭:
{rubric_str}

후보 답변:
{answer}

출력 형식:
반드시 아래 JSON 형식만 정확히 반환하세요. 다른 서두나 백틱(```json) 마크다운은 포함하지 마세요.
{{
  "score": <점수: 1, 2, 또는 3>,
  "reason": "<한글 채점 사유>"
}}
"""
    print("=== SUBAGENT_PROMPT_START ===")
    print(prompt.strip())
    print("=== SUBAGENT_PROMPT_END ===")
    sys.stdout.flush()
    
    # 에이전트로부터 채점 결과(JSON)를 stdin으로 읽음
    lines = []
    for line in sys.stdin:
        # 종료 감지 (빈 라인이거나 단일 JSON 완성 시 종료)
        lines.append(line)
        try:
            # 매 줄 누적하여 유효한 JSON인지 체크
            data = json.loads("".join(lines).strip())
            if "score" in data:
                return data
        except json.JSONDecodeError:
            pass
            
    # 파싱 실패 시 기본값 처리
    try:
        raw_text = "".join(lines).strip()
        # 혹시 모를 마크다운 블록 제거
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        return json.loads(raw_text.strip())
    except Exception:
        return {"score": 1, "reason": "에이전트 채점 결과 파싱 실패."}

def manual_grade(q, answer):
    print("\n" + "="*60)
    print(f"❓ 질문 ({q['id']}): {q['question']}")
    print(f"💡 정답 (Ground Truth): {q['ground_truth']}")
    print("-"*60)
    print(f"📥 엔진 답변:\n{answer}")
    print("-"*60)
    print("📋 채점 루브릭:")
    for score in sorted(q["evaluation_rubric"].keys(), reverse=True):
        print(f"  [{score}점] {q['evaluation_rubric'][score]}")
    print("="*60)
    
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

def get_agent_answer(q, context):
    prompt = f"""[답변 지시사항]
제시된 컨텍스트(Retrieved Context)만을 바탕으로 질문에 한국어로 정확하게 답변하세요.
절대로 외부 지식이나 상상력을 이용해 지어내거나(환각), 무리하게 추론하지 마세요.
제시된 컨텍스트에 정보가 부족하다면, 어떤 정보가 누락되어 답변할 수 없는지 구체적으로 기술하세요.

[질문]
{q['question']}

[검색된 컨텍스트]
{context}
"""
    print("=== SUBAGENT_PROMPT_START ===")
    print(prompt.strip())
    print("=== SUBAGENT_PROMPT_END ===")
    sys.stdout.flush()
    
    # 에이전트로부터 답변을 stdin으로 읽음
    lines = []
    for line in sys.stdin:
        # 특정 종료 시그널 대신 EOF나 파이프가 끊길 때까지 읽음
        lines.append(line)
        
    return "".join(lines).strip()

def generate_report(results, summary, output_path):
    report_md = f"""# 📊 세컨드 브레인 검색 엔진 벤치마크 결과 보고서

## 1. 종합 요약 (Summary)
*   **평가 일시**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
*   **전체 점수**: **{summary['total_score']}** / {summary['max_score']} (달성도: **{summary['percentage']:.1f}%**)
*   **평가 방식**: {summary['eval_method']}

## 2. 평가 영역별 요약 (Scores by Axis)
| 평가 영역 | 질문 수 | 획득 점수 | 만점 | 백분율 |
| :--- | :---: | :---: | :---: | :---: |
"""
    for axis, data in summary["axis_scores"].items():
        pct = (data["score"] / data["max"]) * 100 if data["max"] > 0 else 0
        report_md += f"| {axis} | {data['count']} | {data['score']} | {data['max']} | {pct:.1f}% |\n"
        
    report_md += """
## 3. 문항별 세부 결과 (Detailed Results)
"""
    for r in results:
        report_md += f"""
### 📝 {r['id']} ({r['axis']})
*   **질문**: {r['question']}
*   **정답 (Ground Truth)**: {r['ground_truth']}
*   **엔진 답변**: 
    > {r['answer'].replace(chr(10), chr(10) + '> ')}
*   **채점 결과**: **{r['score']}점** / 3점
*   **평가 의견**: {r['reason']}

---
"""
    try:
        # 상위 폴더가 존재하지 않으면 생성
        parent_dir = os.path.dirname(output_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
            
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"\n🎉 벤치마크 보고서가 생성되었습니다: {output_path}", file=sys.stderr)
    except Exception as e:
        print(f"❌ 에러: 보고서 파일 작성 중 오류 발생: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="세컨드 브레인 검색 엔진 벤치마크 채점기")
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS_PATH, help="질문지 JSON 파일 경로")
    parser.add_argument("--answers", help="검색 엔진의 답변이 저장된 JSON 파일 경로 (제공 시 검색 단계를 건너뜀)")
    parser.add_argument("--engine", help="대상 검색 엔진 이름 (예: qmd) - --answers 미지정 시 필수")
    parser.add_argument("--output", default=DEFAULT_REPORT_PATH, help="출력 보고서 마크다운 파일 경로")
    parser.add_argument("--provider", default="gemini", choices=["gemini", "openai"], help="자동 채점에 사용할 LLM 제공자 (기본값: gemini)")
    parser.add_argument("--api-key", help="LLM API 키 (환경 변수 GEMINI_API_KEY 또는 OPENAI_API_KEY도 가능)")
    parser.add_argument("--interactive-agent", action="store_true", help="API 키 없이 에이전트와 대화식 격리 환경(Subagent)으로 답변 및 채점 수행")
    
    args = parser.parse_args()
    
    # 1. 질문지 로드
    questions = load_questions(args.questions)
    
    # 2. API 키 설정 및 평가 방식 결정
    api_key = args.api_key
    if not api_key:
        if args.provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY")
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            
    eval_method = "수동 채점 (Interactive CLI)"
    if args.interactive_agent:
        eval_method = "에이전트 격리 채점 (Interactive Subagent)"
    elif api_key:
        eval_method = f"자동 채점 (LLM-as-a-Judge, Provider: {args.provider})"
        
    answers_dict = {}
    if args.answers:
        try:
            with open(args.answers, "r", encoding="utf-8") as f:
                answers_dict = json.load(f)
            print(f"📂 답변 파일을 로드했습니다: {args.answers}", file=sys.stderr)
        except Exception as e:
            print(f"❌ 에러: 답변 파일을 읽는 중 오류 발생: {e}", file=sys.stderr)
            sys.exit(1)
    elif not args.engine:
        print("❌ 에러: --answers 파일을 주지 않을 경우, --engine 파라미터가 필수적입니다.", file=sys.stderr)
        sys.exit(1)
        
    # 4. 채점 및 답변 생성 진행
    results = []
    total_score = 0
    max_score = len(questions) * 3
    axis_scores = {}
    
    for q in questions:
        q_id = q["id"]
        axis = q["axis"]
        
        # 각 축별 점수 통계 초기화
        if axis not in axis_scores:
            axis_scores[axis] = {"score": 0, "max": 0, "count": 0}
        axis_scores[axis]["max"] += 3
        axis_scores[axis]["count"] += 1
        
        # 답변 획득
        answer = ""
        if q_id in answers_dict:
            answer = answers_dict[q_id]
        else:
            # 1단계: 엔진 검색 수행
            print(f"🔍 [{q_id}] {args.engine} 검색 엔진으로 컨텍스트 조회 중...", file=sys.stderr)
            context = run_engine_search(args.engine, q["question"])
            
            # 2단계: 답변 생성
            if args.interactive_agent:
                # 에이전트 서브토픽 격리 방식으로 답변 수집
                answer = get_agent_answer(q, context)
            else:
                # 일반 유저 터미널 직접 입력
                print("\n" + "="*50, file=sys.stderr)
                print(f"❓ [{q_id}] {q['question']}", file=sys.stderr)
                print("="*50, file=sys.stderr)
                print("엔진의 답변을 입력하세요. 입력이 끝나면 빈 줄에서 Ctrl+D를 누르세요:", file=sys.stderr)
                lines = []
                try:
                    for line in sys.stdin:
                        lines.append(line)
                    answer = "".join(lines).strip()
                except KeyboardInterrupt:
                    print("\n👋 평가가 중단되었습니다.", file=sys.stderr)
                    sys.exit(0)
                    
        if not answer:
            print(f"⚠️ 경고: {q_id}번에 대한 답변이 비어있어 1점 처리됩니다.", file=sys.stderr)
            score_data = {"score": 1, "reason": "답변이 제출되지 않았습니다."}
        else:
            # 3단계: 채점 진행
            if args.interactive_agent:
                # 에이전트 격리 채점 모드
                score_data = get_agent_graded(q, answer)
            elif api_key:
                score_data = llm_grade(q, answer, api_key, args.provider)
                if score_data is None:
                    score_data = manual_grade(q, answer)
            else:
                score_data = manual_grade(q, answer)
                
        score = score_data["score"]
        reason = score_data["reason"]
        
        results.append({
            "id": q_id,
            "axis": axis,
            "question": q["question"],
            "ground_truth": q["ground_truth"],
            "answer": answer,
            "score": score,
            "reason": reason
        })
        
        total_score += score
        axis_scores[axis]["score"] += score
        
        # 중간 저장 (중간 중단 대비)
        if not args.answers:
            answers_dict[q_id] = answer
            
    # 생성된 답변 캐싱 저장 (새로운 벤치마크 수행 시)
    if not args.answers and args.engine:
        answers_save_path = f"engines/{args.engine}/answers.json"
        try:
            with open(answers_save_path, "w", encoding="utf-8") as f:
                json.dump(answers_dict, f, ensure_ascii=False, indent=2)
            print(f"💾 생성된 엔진 답변이 기록되었습니다: {answers_save_path}", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ 답변 캐시 저장 실패: {e}", file=sys.stderr)
            
    # 5. 요약 통계 작성
    percentage = (total_score / max_score) * 100 if max_score > 0 else 0
    summary = {
        "total_score": total_score,
        "max_score": max_score,
        "percentage": percentage,
        "eval_method": eval_method,
        "axis_scores": axis_scores
    }
    
    # 6. 보고서 생성
    generate_report(results, summary, args.output)
    
    # 7. CLI 결과 요약 출력
    print("\n" + "="*40, file=sys.stderr)
    print("📊 벤치마크 평가 결과 요약", file=sys.stderr)
    print(f"- 총점: {total_score} / {max_score} ({percentage:.1f}%)", file=sys.stderr)
    print("- 영역별 달성도:", file=sys.stderr)
    for axis, data in axis_scores.items():
        pct = (data["score"] / data["max"]) * 100
        print(f"  * {axis}: {data['score']} / {data['max']} ({pct:.1f}%)", file=sys.stderr)
    print("="*40, file=sys.stderr)

if __name__ == "__main__":
    main()
