"""冒烟脚本：登录 → 创建文档 → 发布/审核 → 检索 → 对话。

用法：
    python scripts/smoke.py
环境变量：
    SMOKE_BASE_URL   后端地址，默认 http://127.0.0.1:3000
    SMOKE_USERNAME   默认 admin
    SMOKE_PASSWORD   默认 123456
"""

import os
import sys
import time

import httpx

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:3000")
USERNAME = os.getenv("SMOKE_USERNAME", "admin")
PASSWORD = os.getenv("SMOKE_PASSWORD", "123456")
PENDING_REVIEW = 3
TIMEOUT = httpx.Timeout(120.0)


def fail(step: str, response: httpx.Response) -> int:
    print(f"[FAIL] {step}: HTTP {response.status_code} {response.text[:300]}")
    return 1


def main() -> int:
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as client:
        print(f"[1/5] 登录 {BASE_URL} 用户 {USERNAME}")
        response = client.post(
            "/auth/login", json={"username": USERNAME, "password": PASSWORD}
        )
        if response.status_code != 200:
            return fail("登录", response)
        token = response.json().get("accessToken")
        if not token:
            print("[FAIL] 登录响应缺少 accessToken")
            return 1
        headers = {"Authorization": f"Bearer {token}"}

        title = f"冒烟测试文档 {int(time.time())}"
        print(f"[2/5] 创建文档：{title}")
        response = client.post(
            "/documents",
            headers=headers,
            json={
                "title": title,
                "content": "这是冒烟脚本创建的测试正文，用于验证发布、检索与问答链路。",
                "isPublic": True,
            },
        )
        if response.status_code != 200:
            return fail("创建文档", response)
        document = response.json()
        document_id = document.get("id")
        if not document_id:
            print("[FAIL] 创建文档响应缺少 id")
            return 1
        print(f"       documentId={document_id}")

        print("[3/5] 发布文档")
        response = client.put(f"/documents/{document_id}/publish", headers=headers)
        if response.status_code != 200:
            return fail("发布文档", response)
        status = response.json().get("status")
        if status == PENDING_REVIEW:
            print("       进入审核流，查询待审任务")
            tasks = client.get(
                "/documents/reviews/tasks",
                headers=headers,
                params={"status": "pending", "pageSize": 50},
            )
            if tasks.status_code != 200:
                return fail("查询审核任务", tasks)
            task = next(
                (
                    item
                    for item in tasks.json().get("items", [])
                    if item.get("documentId") == document_id
                ),
                None,
            )
            if task is None:
                print("[FAIL] 未找到该文档的待审核任务")
                return 1
            approved = client.post(
                f"/documents/reviews/tasks/{task['id']}/approve",
                headers=headers,
                json={"reviewComment": "冒烟通过"},
            )
            if approved.status_code != 200:
                return fail("审核通过", approved)
            status = approved.json().get("status")
        if status != 1:
            print(f"[FAIL] 文档未进入已发布状态，当前 status={status}")
            return 1
        print("       已发布")

        print("[4/5] 检索文档")
        response = client.post(
            "/search",
            headers=headers,
            json={"keyword": title[:8], "page": 1, "pageSize": 10},
        )
        if response.status_code != 200:
            return fail("检索", response)
        total = response.json().get("total", 0)
        print(f"       命中 {total} 条（依赖 Elasticsearch，索引未就绪时允许为 0）")

        print("[5/5] 发起对话")
        response = client.post(
            "/ai/chat",
            headers=headers,
            json={"content": "知识库怎么用？", "topK": 5},
        )
        if response.status_code == 503:
            print("       未配置 LLM Key，对话接口按预期返回 503")
        elif response.status_code != 200:
            return fail("对话", response)
        else:
            answer = response.json().get("answer") or ""
            print(f"       回答长度 {len(answer)}，sessionId={response.json().get('sessionId')}")

        print("清理测试文档")
        client.delete(f"/documents/{document_id}", headers=headers)

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
