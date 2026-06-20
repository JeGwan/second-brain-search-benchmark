#!/usr/bin/env python3
"""
QMD 검색 엔진 전용 RAG 러너 (QMD Search Engine RAG Runner)
QMD에서 컨텍스트를 검색한 뒤, LLM을 사용해 최종 답변을 생성하여 answers.json을 구축합니다.
"""

import os
import sys
import json
import subprocess
import urllib.request
import urllib.error

# 파일 경로 정의
QUESTIONS_PATH = "../../questions.json"
OUTPUT_ANSWERS_PATH = "answers.json"

def call_gemini_api(api_key, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
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
            {"role": "user", "content": prompt}
        ]
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        print(f"⚠️ OpenAI API 호출 오류 (HTTP {e.code}): {e.read().decode('utf-8')}")
        return None
    except Exception as e:
        print(f"⚠️ API 호출 중 오류 발생: {e}")
        return None

def search_qmd(query):
    # QMD 쿼리 명령어 실행 (상위 3개 문서 검색, 마크다운 형식으로 컨텍스트 추출)
    cmd = ["npx", "@tobilu/qmd", "query", query, "-n", "3", "--format", "md"]
    try:
        # 벤치마크 루트 폴더(두 단계 위)에서 실행하도록 설정
        cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ QMD 실행 오류: {e.stderr}")
        return ""

def main():
    # 1. API 키 확인
    api_key = os.environ.get("GEMINI_API_KEY")
    provider = "gemini"
    
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
        provider = "openai"
        
    if not api_key:
        print("❌ 에러: GEMINI_API_KEY 또는 OPENAI_API_KEY 환경 변수를 설정해야 합니다.")
        sys.exit(1)
        
    print(f"🤖 LLM 제공자: {provider}")

    # 2. 질문지 로드
    abs_questions_path = os.path.abspath(os.path.join(os.path.dirname(__file__), QUESTIONS_PATH))
    if not os.path.exists(abs_questions_path):
        print(f"❌ 에러: 질문지 파일을 찾을 수 없습니다. 경로: {abs_questions_path}")
        sys.exit(1)
        
    with open(abs_questions_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    answers = {}

    # 3. 질문별 검색 및 답변 생성
    for q in questions:
        q_id = q["id"]
        question_text = q["question"]
        
        print(f"🔍 [{q_id}] QMD 검색 중: {question_text}")
        context = search_qmd(question_text)
        
        if not context.strip():
            print(f"⚠️ [{q_id}] QMD에서 검색된 문서가 없습니다.")
            answers[q_id] = "QMD 검색 결과가 비어 있어 질문에 답변할 수 없습니다."
            continue
            
        print(f"✏️ [{q_id}] LLM 답변 생성 중...")
        prompt = f"""
You are a helpful assistant answering questions based on the retrieved context from a user's Second Brain.
Answer the question accurately based ONLY on the retrieved context. Do not make up facts.

[Retrieved Context from Second Brain]
{context}

[Question]
{question_text}

[Instruction]
Write your answer in Korean. Be clear, objective, and reference facts from the context.
"""
        if provider == "gemini":
            ans_text = call_gemini_api(api_key, prompt)
        else:
            ans_text = call_openai_api(api_key, prompt)
            
        if ans_text:
            answers[q_id] = ans_text
            print(f"✅ [{q_id}] 답변 완료")
        else:
            answers[q_id] = "답변 생성 실패 (API 오류)"
            print(f"❌ [{q_id}] 답변 생성 실패")

    # 4. 결과 저장
    output_path = os.path.abspath(os.path.join(os.path.dirname(__file__), OUTPUT_ANSWERS_PATH))
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=2)
        
    print(f"\n🎉 모든 답변이 저장되었습니다: {output_path}")

if __name__ == "__main__":
    main()
