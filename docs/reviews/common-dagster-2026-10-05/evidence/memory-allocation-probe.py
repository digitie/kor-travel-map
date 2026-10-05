import asyncio
import gc
import json
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

from kortravelmap.dagster.assets import _record_batches, _record_list


def source():
    for n in range(5000):
        yield {"identity": n, "raw": (str(n) + ":" + "x" * 8192)}


async def measure(whole):
    gc.collect()
    tracemalloc.start()
    context = SimpleNamespace(resources=SimpleNamespace(records=source()))
    seen = 0
    largest = 0
    if whole:
        records = await _record_list(context, "records")
        seen = len(records)
        largest = len(records)
    else:
        async for records in _record_batches(context, "records", batch_size=100):
            seen += len(records)
            largest = max(largest, len(records))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert seen == 5000
    return {"records": seen, "largest_batch": largest, "python_peak_bytes": peak}


async def main():
    result = {
        "map_product": "72242b1a0c964893778ee7e0ef25e698097e1dfa",
        "scope": (
            "synthetic lazy provider 5000 records, 8KiB raw each; Python allocation only,"
            " not operating RSS or PG SQL"
        ),
        "whole_list": await measure(True),
        "bounded_batches": await measure(False),
    }
    Path("/mnt/f/dev/kor-travel-weather/.playwright-mcp/map-batch-allocation.json").write_text(  # noqa: ASYNC240 - 측정 종료 후 증거 파일을 기록하는 probe다.
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result))


asyncio.run(main())
