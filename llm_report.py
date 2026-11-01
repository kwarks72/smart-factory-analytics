"""
5단계: 생성형 AI(LLM)로 일일 보고 요약 만들기

output/report.md(분석 결과)를 AI에게 읽혀서 공장장에게 보고하는 3문장 요약을 만듭니다.

  - ANTHROPIC_API_KEY(AI 사용 열쇠)가 있으면 -> Claude가 요약
  - 없으면 -> 미리 정해 둔 문장 틀로 요약 (AI 없이도 프로그램이 멈추지 않게)

Windows 명령 프롬프트에서 열쇠 넣는 법:  set ANTHROPIC_API_KEY=여기에_열쇠
"""

import os
from pathlib import Path

report = Path("output/report.md").read_text(encoding="utf-8")

PROMPT = f"""당신은 공장 생산관리 보조입니다.
아래 분석 리포트를 읽고, 공장장에게 보고하듯 한국어 3문장으로 요약하세요.
리포트에 없는 숫자나 사실은 절대 만들지 마세요.

{report}"""


def fallback_summary(text):
    """AI 없이, 리포트의 줄을 뽑아 문장 틀에 끼워 넣습니다."""
    pick = lambda key: next((l.lstrip("- ").strip() for l in text.splitlines() if key in l), "")
    return f"{pick('총 생산')}. {pick('이상으로 표시된 설비')}. {pick('이상 탐지가 불량 급증보다')}."


api_key = os.getenv("ANTHROPIC_API_KEY")
if api_key:
    import anthropic  # pip install anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=500,
        messages=[{"role": "user", "content": PROMPT}],
    )
    summary = message.content[0].text
    source = "Claude API로 생성"
else:
    summary = fallback_summary(report)
    source = "AI 미사용 (ANTHROPIC_API_KEY 없음) - 문장 틀로 생성"

Path("output/daily_summary.md").write_text(f"# 일일 보고 요약\n\n_{source}_\n\n{summary}\n", encoding="utf-8")
print(f"[{source}]\n{summary}")
