from unittest import IsolatedAsyncioTestCase

from httpx import ASGITransport, AsyncClient

from backend.main import app


class SetupTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = await self.enterAsyncContext(
            AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        )

    async def test_api_health(self) -> None:
        response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    async def test_example_case_is_available(self) -> None:
        response = await self.client.get("/api/cases/example")
        self.assertEqual(response.status_code, 200)
        case = response.json()
        self.assertEqual(len(case["exams"]), 3)
        self.assertEqual(len(case["rooms"]), 2)
        self.assertEqual(len(case["slots"]), 2)
