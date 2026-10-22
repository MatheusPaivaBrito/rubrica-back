from prometheus_client import multiprocess


def child_exit(_server, worker) -> None:
    multiprocess.mark_process_dead(worker.pid)
