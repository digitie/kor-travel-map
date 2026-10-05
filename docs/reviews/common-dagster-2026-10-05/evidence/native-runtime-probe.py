import hashlib
import importlib.metadata
import importlib.util
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from dagster import DagsterInstance, DagsterRunStatus, RunsFilter
from dagster._core.workspace.context import WorkspaceProcessContext
from dagster._core.workspace.load_target import PythonFileTarget
from kortravelcommon.dagster import has_active_run

root = Path("/work/native-runtime-instance")
root.mkdir(exist_ok=False)
(root / "dagster.yaml").write_text("""telemetry:
  enabled: false
run_monitoring:
  enabled: true
  max_runtime_seconds: 30
  poll_interval_seconds: 1
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
        time.sleep(90)
    return 1
@job(executor_def=multiprocess_executor.configured({"max_concurrent": 1}),
     tags=RecoveryPolicy(max_runtime_seconds=20).tags(project="codex-native", job_name="probe_job"))
def probe_job():
    probe()
defs = Definitions(jobs=[probe_job])
""")
os.environ["DAGSTER_HOME"] = str(root)
spec = importlib.util.spec_from_file_location("isolated_recovery_jobs", jobfile)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
workspace_file = root / "workspace.yaml"
workspace_file.write_text(
    "load_from:\n  - python_file:\n      relative_path: "
    + str(jobfile)
    + "\n      attribute: defs\n      working_directory: "
    + str(root)
    + "\n      location_name: codex-native-recovery\n"
)
daemon_log = open("/evidence/native-daemon-private.log", "w")  # noqa: SIM115 - daemon 종료 뒤 finally에서 닫는 실행 원문이다.
daemon = subprocess.Popen(
    ["dagster-daemon", "run", "-w", str(workspace_file)],
    stdout=daemon_log,
    stderr=subprocess.STDOUT,
    cwd=root,
)
probe_failure = None
try:
    time.sleep(3)
    assert daemon.poll() is None, "isolated native daemon exited at startup"
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

            def wait(run_id):
                started = time.monotonic()
                while time.monotonic() - started < 80:
                    run = instance.get_run_by_id(run_id)
                    if run.is_finished:
                        return run, time.monotonic() - started
                    time.sleep(0.15)
                raise AssertionError("isolated run did not reach terminal state")

            for action in ("raise", "crash"):
                failed_id = launch(action)
                failed, elapsed = wait(failed_id)
                assert failed.status == DagsterRunStatus.FAILURE
                fault_logs = instance.all_logs(failed_id)
                assert any(
                    entry.dagster_event and entry.dagster_event.event_type_value == "STEP_START"
                    for entry in fault_logs
                )
                failure_errors = "\n".join(
                    entry.dagster_event.step_failure_data.error.to_string()
                    for entry in fault_logs
                    if entry.dagster_event
                    and entry.dagster_event.event_type_value == "STEP_FAILURE"
                    and entry.dagster_event.step_failure_data.error
                )
                if action == "raise":
                    assert "RuntimeError: isolated fixture failure" in failure_errors
                else:
                    assert "ChildProcessCrashException" in failure_errors
                    assert any(
                        entry.dagster_event
                        and entry.dagster_event.event_type_value == "ENGINE_EVENT"
                        and "child process for step probe unexpectedly exited with code 9."
                        in entry.message
                        for entry in fault_logs
                    )
                recovered, retry_elapsed = wait(launch("ok"))
                assert recovered.status == DagsterRunStatus.SUCCESS
                rows.append(
                    {
                        "fault": action,
                        "terminal": failed.status.value,
                        "elapsed_seconds": elapsed,
                        "step_started": True,
                        "fault_cause_verified": True,
                        "same_job_manual_retry": recovered.status.value,
                        "retry_elapsed_seconds": retry_elapsed,
                    }
                )
            stalled_id = launch("stall")
            step_deadline = time.monotonic() + 25
            while time.monotonic() < step_deadline:
                stalled = instance.get_run_by_id(stalled_id)
                logs = instance.all_logs(stalled_id)
                if any(
                    entry.dagster_event and entry.dagster_event.event_type_value == "STEP_START"
                    for entry in logs
                ):
                    break
                assert not stalled.is_finished, "stall ended before step started"
                time.sleep(0.15)
            else:
                raise AssertionError("stall STEP_START missing")
            assert stalled.status == DagsterRunStatus.STARTED
            assert stalled.tags["dagster/max_runtime"] == "20"
            assert has_active_run(
                instance,
                job_name="probe_job",
                project="codex-native",
                location_name="codex-native-recovery",
            )
            healthy_id = launch("ok")
            assert instance.get_run_by_id(stalled_id).status == DagsterRunStatus.STARTED
            healthy, healthy_elapsed = wait(healthy_id)
            assert healthy.status == DagsterRunStatus.SUCCESS
            stalled, stall_elapsed = wait(stalled_id)
            assert stalled.status == DagsterRunStatus.FAILURE
            timeout_events = [
                entry
                for entry in instance.all_logs(stalled_id)
                if entry.dagster_event
                and entry.dagster_event.event_type_value == "RUN_FAILURE"
                and "Exceeded maximum runtime of 20 seconds" in entry.message
            ]
            assert timeout_events, "stall FAILURE was not native max-runtime timeout"
            stall_record = instance.get_run_records(filters=RunsFilter(run_ids=[stalled_id]))[0]
            healthy_record = instance.get_run_records(filters=RunsFilter(run_ids=[healthy_id]))[0]
            assert stall_record.start_time < healthy_record.start_time < stall_record.end_time
            assert healthy_record.end_time > stall_record.start_time
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
                    "stall_step_started": True,
                    "native_timeout_event_verified": True,
                    "run_intervals_overlap": True,
                    "max_runtime_tag": stalled.tags["dagster/max_runtime"],
                    "monitor_wait_seconds_after_healthy": stall_elapsed,
                }
            )
except BaseException as error:
    probe_failure = error
    Path("/evidence/native-runtime-recovery-failure.json").write_text(
        json.dumps(
            {
                "status": "FAIL",
                "error_type": type(error).__name__,
                "completed_cases": rows if "rows" in globals() else [],
            },
            indent=2,
        )
        + "\n"
    )
    raise
finally:
    daemon.terminate()
    try:
        daemon.wait(timeout=20)
    except subprocess.TimeoutExpired:
        daemon.kill()
        daemon.wait()
    daemon_log.close()
common_url = json.loads(
    importlib.metadata.distribution("kor-travel-common").read_text("direct_url.json") or "{}"
)
common_file = Path(importlib.util.find_spec("kortravelcommon.dagster").origin)
payload = {
    "dagster_version": __import__("dagster").__version__,
    "common_reference_contract": "1f8e339c7c79f86f8952b0d4c326ab4dae56bee8",
    "actual_common_package_commit": common_url.get("vcs_info", {}).get("commit_id"),
    "actual_common_dagster_sha256": hashlib.sha256(common_file.read_bytes()).hexdigest(),
    "scope": (
        "isolated SQLite instance inside exact rebuilt operating Map Dagster image; "
        "real gRPC launcher/multiprocess workers and autonomous dagster-daemon "
        "monitoring; shared plane and domain SQL untouched"
    ),
    "autonomous_daemon_monitoring": True,
    "max_runtime_seconds": 20,
    "cases": rows,
}
out = Path("/evidence/native-runtime-recovery-result.json")
out.write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps(payload))
