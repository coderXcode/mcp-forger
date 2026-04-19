import asyncio
import httpx
import json

async def go():
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(
            "http://localhost:8000/api/projects/1/tests/run",
            headers={"Content-Type": "application/json"},
            content=json.dumps({"regenerate_tests": True}),
        )
        print("started:", r.status_code, r.text)

        for i in range(60):
            await asyncio.sleep(5)
            r2 = await c.get("http://localhost:8000/api/projects/1/tests/runs")
            runs = r2.json()
            if runs:
                latest = runs[0]
                status = latest["status"]
                passed = latest["passed"]
                total = latest["total"]
                rid = latest["id"]
                print(f"[{(i+1)*5}s] run#{rid} status={status} {passed}/{total}")
                if status not in ("running", "pending"):
                    # Fetch full details
                    r3 = await c.get(f"http://localhost:8000/api/projects/1/tests/runs/{rid}")
                    detail = r3.json()
                    print("output tail:")
                    print((detail.get("output") or "")[-1000:])
                    print("test_code written:", bool(detail.get("test_code")))
                    break

asyncio.run(go())
