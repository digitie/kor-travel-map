import importlib.util
import json
import logging
import os
import sys
import time
from pathlib import Path

from dagster import DagsterInstance, DagsterRunStatus
from dagster._core.workspace.context import WorkspaceProcessContext
from dagster._core.workspace.load_target import PythonFileTarget
from dagster._daemon.monitoring.run_monitoring import monitor_started_run
from kortravelcommon.dagster import has_active_run

root = Path("/home/digitie/.cache/map-native-recovery-20261005")
root.mkdir(exist_ok=False)
(root / "dagster.yaml").write_text("""telemetry:
  enabled: false
run_monitoring:
  enabled: true
  max_runtime_seconds: 20
  start_timeout_seconds: 30
  cancel_timeout_seconds: 5
  max_resume_run_attempts: 0
""")
jobfile = root / "jobs.py"
jobfile.write_text("""import os, time
from dagster import Definitions, job, op, multiprocess_executor
from kortravelcommon.dagster import RecoveryPolicy
@op(config_schema={"action": str})
def probe(context):
    action = context.op_config["action"]
    if action == "raise":
        raise RuntimeError("isolated fixture failure")
    if action == "crash":
        os._exit(9)
    if action == "stall":
        time.sleep(60)
    return 1
@job(executor_def=multiprocess_executor.configured({"max_concurrent": 1}),
     tags=RecoveryPolicy(max_runtime_seconds=10).tags(project="codex-native", job_name="probe_job"))
def probe_job():
    probe()
defs = Definitions(jobs=[probe_job])
""")
os.environ["DAGSTER_HOME"] = str(root)
spec = importlib.util.spec_from_file_location("isolated_recovery_jobs", jobfile)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
rows = []
logger = logging.getLogger("isolated-recovery")
with (  # noqa: SIM117 - 실행 원문의 context 경계를 보존한다.
    DagsterInstance.from_config(str(root)) as instance,
    WorkspaceProcessContext(
        instance, PythonFileTarget(str(jobfile), "defs", str(root), "codex-native-recovery")
    ) as process,
):
    with process.create_request_context() as workspace:
        location = workspace.get_code_location("codex-native-recovery")
        remote = location.get_repository("__repository__").get_full_job("probe_job")

        def launch(action):
            run = instance.create_run_for_job(
                module.probe_job,
                run_config={"ops": {"probe": {"config": {"action": action}}}},
                remote_job_origin=remote.get_remote_origin(),
                job_code_origin=remote.get_python_origin(),
            )
            instance.launch_run(run.run_id, workspace)
            return run.run_id

        def wait(run_id, monitor=True):
            started = time.monotonic()
            while time.monotonic() - started < 40:
                run = instance.get_run_by_id(run_id)
                if run.is_finished:
                    return run, time.monotonic() - started
                if monitor and run.status == DagsterRunStatus.STARTED:
                    record = instance.get_run_records(
                        filters=__import__("dagster").RunsFilter(run_ids=[run_id])
                    )[0]
                    monitor_started_run(instance, workspace, record, logger)
                time.sleep(0.15)
            raise AssertionError("isolated run did not reach terminal state")

        for action in ("raise", "crash"):
            failed_id = launch(action)
            failed, elapsed = wait(failed_id)
            assert failed.status == DagsterRunStatus.FAILURE
            recovered, retry_elapsed = wait(launch("ok"))
            assert recovered.status == DagsterRunStatus.SUCCESS
            rows.append(
                {
                    "fault": action,
                    "terminal": failed.status.value,
                    "elapsed_seconds": elapsed,
                    "same_job_manual_retry": recovered.status.value,
                    "retry_elapsed_seconds": retry_elapsed,
                }
            )
        stalled_id = launch("stall")
        assert has_active_run(
            instance,
            job_name="probe_job",
            project="codex-native",
            location_name="codex-native-recovery",
        )
        healthy_id = launch("ok")
        healthy, healthy_elapsed = wait(healthy_id)
        assert healthy.status == DagsterRunStatus.SUCCESS
        stalled, stall_elapsed = wait(stalled_id)
        assert stalled.status == DagsterRunStatus.FAILURE
        assert not has_active_run(
            instance,
            job_name="probe_job",
            project="codex-native",
            location_name="codex-native-recovery",
        )
        recovered, _ = wait(launch("ok"))
        assert recovered.status == DagsterRunStatus.SUCCESS
        rows.append(
            {
                "fault": "stall",
                "terminal": stalled.status.value,
                "healthy_concurrent_job": healthy.status.value,
                "healthy_elapsed_seconds": healthy_elapsed,
                "active_coalescing_released": True,
                "same_job_manual_retry": recovered.status.value,
                "monitor_wait_seconds_after_healthy": stall_elapsed,
            }
        )
payload = {
    "dagster_version": __import__("dagster").__version__,
    "common_product": "1f8e339c7c79f86f8952b0d4c326ab4dae56bee8",
    "scope": (
        "isolated local SQLite instance, real gRPC DefaultRunLauncher and "
        "multiprocess workers; native monitor function called by probe; not shared "
        "production daemon or domain SQL"
    ),
    "cases": rows,
}
out = Path("/mnt/f/dev/kor-travel-weather/.playwright-mcp/map-native-recovery-result.json")
out.write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps(payload))
