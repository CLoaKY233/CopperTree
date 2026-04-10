import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from src.config import settings
from src.workflows.activities import run_assessment, run_final_notice
from src.workflows.collections import CollectionsWorkflow

TASK_QUEUE = "collections-queue"


async def main() -> None:
    client = await Client.connect(settings.temporal_host)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CollectionsWorkflow],
        activities=[run_assessment, run_final_notice],
    )
    print(f"Worker started — listening on task queue: {TASK_QUEUE}")
    print(f"Temporal: {settings.temporal_host}")
    print("Press Ctrl+C to stop.\n")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
