"""Background lease renewal for active processing jobs."""

import threading

from .jobs import get_job, renew_job_lease


class JobHeartbeat:
    def __init__(
        self,
        job_id,
        lease_token,
        interval_seconds=30,
        lease_seconds=120,
        user_id=1,
    ):
        if interval_seconds <= 0:
            raise ValueError("Interval must be positive")

        if lease_seconds <= interval_seconds:
            raise ValueError(
                "Lease must exceed heartbeat interval"
            )

        self.job_id = job_id
        self.lease_token = lease_token
        self.interval_seconds = interval_seconds
        self.lease_seconds = lease_seconds
        self.user_id = user_id

        self._stop_event = threading.Event()
        self._thread = None
        self.lost_lease = False
        self.renewal_error = None

    def _run(self):
        while not self._stop_event.wait(
            self.interval_seconds
        ):
            try:
                renewed = renew_job_lease(
                    self.job_id,
                    self.lease_token,
                    lease_seconds=self.lease_seconds,
                )

                if renewed:
                    continue

                # The extraction pipeline may have atomically
                # completed the job and cleared the lease.
                job = get_job(
                    self.job_id,
                    user_id=self.user_id,
                )

                if job is not None and job["status"] == "succeeded":
                    break

                self.lost_lease = True
                break

            except Exception as error:
                self.renewal_error = type(error).__name__
                self.lost_lease = True
                break

    def __enter__(self):
        self._thread = threading.Thread(
            target=self._run,
            name=f"job-heartbeat-{self.job_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join()

        return False
