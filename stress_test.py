#!/usr/bin/env python3
"""
DigitalHuman Stress Test - Browser-based WebSocket testing
Uses Playwright to simulate real user interactions via the web UI
"""

import asyncio
import json
import time
import random
from datetime import datetime, timedelta
from pathlib import Path

# Test questions (10-15 words each)
TEST_QUESTIONS = [
    # Qin Shi Huang questions
    ("qin-shihuang", "你好，你是谁？请介绍一下你自己"),
    ("qin-shihuang", "你统一了哪些国家？是怎么统一的？"),
    ("qin-shihuang", "长城是怎么修建的？花了多长时间？"),
    ("qin-shihuang", "你为什么要焚书坑儒？"),
    ("qin-shihuang", "兵马俑是怎么制作的？"),
    ("qin-shihuang", "你统一文字和货币有什么意义？"),
    ("qin-shihuang", "你觉得长生不老可能吗？"),
    ("qin-shihuang", "秦朝的法律是什么样的？"),
    ("qin-shihuang", "你和李斯的关系怎么样？"),
    ("qin-shihuang", "秦朝的军队有多强大？"),

    # Maryknoll Teacher questions
    ("maryknoll-teacher", "Hello, can you tell me about the school programs?"),
    ("maryknoll-teacher", "What is the admission process for new students?"),
    ("maryknoll-teacher", "瑪利諾中學有什麼課外活動？"),
    ("maryknoll-teacher", "學校的校訓是什麼？"),
    ("maryknoll-teacher", "What subjects do you teach at the school?"),
    ("maryknoll-teacher", "學校有什麼升學輔導服務？"),
    ("maryknoll-teacher", "How can I apply to the school?"),
    ("maryknoll-teacher", "學校的STEM教育怎麼樣？"),
    ("maryknoll-teacher", "有什麼獎學金可以申請？"),
    ("maryknoll-teacher", "學校的校園環境如何？"),

    # Elizabeth I questions
    ("elizabeth-i", "Your Majesty, tell me about your reign as Queen"),
    ("elizabeth-i", "What was life like during the Tudor period?"),
    ("elizabeth-i", "How did you deal with political challenges?"),
    ("elizabeth-i", "What is your relationship with Mary Queen of Scots?"),
    ("elizabeth-i", "Tell me about the Spanish Armada victory"),
    ("elizabeth-i", "How did you promote arts and culture?"),
    ("elizabeth-i", "What was your relationship with your father Henry VIII?"),
    ("elizabeth-i", "How did you handle religious conflicts?"),
    ("elizabeth-i", "What legacy did you leave for England?"),
    ("elizabeth-i", "How did you maintain power as a female ruler?"),

    # Li Bai questions
    ("character-49fd372d", "李白你好，你是唐代著名诗人"),
    ("character-49fd372d", "请背诵一首你的代表作品"),
    ("character-49fd372d", "你最喜欢喝什麼酒？"),
    ("character-49fd372d", "你是怎么成为詩人的？"),
    ("character-49fd372d", "你和杜甫的關係怎麼樣？"),
    ("character-49fd372d", "你遊歷過哪些名山大川？"),
    ("character-49fd372d", "你的詩歌有什麼特點？"),
    ("character-49fd372d", "為什麼你被稱為詩仙？"),
    ("character-49fd372d", "你對當時的政治有什麼看法？"),
    ("character-49fd372d", "你最喜歡的詩作是哪一首？"),
]


class StressTestResults:
    def __init__(self):
        self.total_requests = 0
        self.successful = 0
        self.failed = 0
        self.errors = []
        self.response_times = []
        self.start_time = time.time()

    def record_success(self, response_time_ms):
        self.total_requests += 1
        self.successful += 1
        self.response_times.append(response_time_ms)

    def record_failure(self, error_msg):
        self.total_requests += 1
        self.failed += 1
        self.errors.append({
            "time": datetime.now().isoformat(),
            "error": error_msg
        })

    def get_stats(self):
        elapsed = time.time() - self.start_time
        avg_response = sum(self.response_times) / len(self.response_times) if self.response_times else 0
        return {
            "elapsed_seconds": int(elapsed),
            "total_requests": self.total_requests,
            "successful": self.successful,
            "failed": self.failed,
            "success_rate": f"{(self.successful/self.total_requests*100):.1f}%" if self.total_requests > 0 else "0%",
            "avg_response_time_ms": int(avg_response),
            "requests_per_minute": int(self.total_requests / (elapsed / 60)) if elapsed > 0 else 0,
        }


async def run_stress_test(duration_minutes=60):
    """Run stress test for specified duration using browser automation"""
    from playwright.async_api import async_playwright

    results = StressTestResults()
    end_time = time.time() + (duration_minutes * 60)

    print(f"\n{'='*70}")
    print(f"🚀 DigitalHuman Stress Test - Browser Automation")
    print(f"{'='*70}")
    print(f"Duration: {duration_minutes} minutes")
    print(f"Target: http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080")
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        # Track active sessions
        active_sessions = {}
        question_index = 0

        while time.time() < end_time:
            # Pick next question (cycle through all)
            char_id, question = TEST_QUESTIONS[question_index % len(TEST_QUESTIONS)]
            question_index += 1

            # Create a new browser page for this request
            page = await context.new_page()

            try:
                # Navigate to the character page
                url = f"http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/?char={char_id}"
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Wait for WebSocket to connect
                await page.wait_for_timeout(2000)

                # Use JavaScript to send message via WebSocket
                start_time = time.time()

                # Inject JavaScript to handle the conversation
                result = await page.evaluate(f"""
                    async () => {{
                        return new Promise((resolve, reject) => {{
                            const timeout = setTimeout(() => {{
                                reject(new Error('WebSocket timeout'));
                            }}}, 60000);

                            // Find existing WebSocket or create new one
                            let ws = null;
                            const wsUrl = 'ws://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/ws?char={char_id}';

                            try {{
                                ws = new WebSocket(wsUrl);

                                ws.onopen = () => {{
                                    // Send the question
                                    ws.send(JSON.stringify({{
                                        type: 'text',
                                        content: '{question}'
                                    }}));
                                }};

                                let response = '';
                                let audioChunks = 0;
                                let done = false;

                                ws.onmessage = (event) => {{
                                    if (typeof event.data === 'string') {{
                                        try {{
                                            const data = JSON.parse(event.data);
                                            if (data.type === 'llm') {{
                                                response += data.content;
                                            }} else if (data.type === 'status' && data.content === 'done') {{
                                                done = true;
                                                clearTimeout(timeout);
                                                ws.close();
                                                resolve({{
                                                    response: response,
                                                    audioChunks: audioChunks,
                                                    done: true
                                                }});
                                            }} else if (data.type === 'error') {{
                                                clearTimeout(timeout);
                                                ws.close();
                                                reject(new Error(data.content));
                                            }}
                                        }} catch (e) {{
                                            // Ignore parse errors
                                        }}
                                    }} else {{
                                        // Binary audio data
                                        audioChunks++;
                                    }}
                                }};

                                ws.onerror = (error) => {{
                                    clearTimeout(timeout);
                                    reject(new Error('WebSocket error: ' + error.message));
                                }};

                                ws.onclose = () => {{
                                    if (!done) {{
                                        clearTimeout(timeout);
                                        resolve({{
                                            response: response,
                                            audioChunks: audioChunks,
                                            done: false
                                        }});
                                    }}
                                }};
                            }} catch (e) {{
                                clearTimeout(timeout);
                                reject(e);
                            }}
                        }});
                    }}
                """)

                response_time = int((time.time() - start_time) * 1000)

                if result and result.get('done'):
                    results.record_success(response_time)
                    stats = results.get_stats()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ #{results.total_requests} | "
                          f"{char_id[:15]:15} | {response_time:6}ms | "
                          f"Audio: {result.get('audioChunks', 0):4} chunks | "
                          f"Rate: {stats['requests_per_minute']}/min")
                else:
                    results.record_failure("Incomplete response")

            except Exception as e:
                error_msg = str(e)[:100]
                results.record_failure(error_msg)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ #{results.total_requests} | "
                      f"{char_id[:15]:15} | Error: {error_msg}")

            finally:
                await page.close()

            # Brief pause between requests (1-3 seconds)
            await asyncio.sleep(random.uniform(1, 3))

            # Print periodic stats
            if results.total_requests % 10 == 0:
                stats = results.get_stats()
                print(f"\n--- Stats @ {datetime.now().strftime('%H:%M:%S')} ---")
                print(f"Total: {stats['total_requests']} | Success: {stats['successful']} | "
                      f"Failed: {stats['failed']} | Rate: {stats['success_rate']}")
                print(f"Avg Response: {stats['avg_response_time_ms']}ms | "
                      f"Throughput: {stats['requests_per_minute']} req/min")
                print(f"---\n")

        await browser.close()

    # Final report
    stats = results.get_stats()
    print(f"\n{'='*70}")
    print(f"📊 STRESS TEST COMPLETE")
    print(f"{'='*70}")
    print(f"Duration: {stats['elapsed_seconds']} seconds ({stats['elapsed_seconds']//60} minutes)")
    print(f"Total Requests: {stats['total_requests']}")
    print(f"Successful: {stats['successful']}")
    print(f"Failed: {stats['failed']}")
    print(f"Success Rate: {stats['success_rate']}")
    print(f"Average Response Time: {stats['avg_response_time_ms']}ms")
    print(f"Throughput: {stats['requests_per_minute']} requests/minute")
    print(f"{'='*70}")

    if results.errors:
        print(f"\n❌ Errors ({len(results.errors)}):")
        for err in results.errors[:10]:  # Show first 10 errors
            print(f"  - [{err['time']}] {err['error']}")

    # Save results to file
    report = {
        "test_time": datetime.now().isoformat(),
        "duration_minutes": duration_minutes,
        "stats": stats,
        "errors": results.errors
    }
    report_path = Path("stress_test_report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n📄 Report saved to: {report_path}")

    return stats


if __name__ == "__main__":
    import sys
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    asyncio.run(run_stress_test(duration))
