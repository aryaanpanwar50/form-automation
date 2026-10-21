import logging
from datetime import date, datetime, time

from apscheduler.schedulers.background import BackgroundScheduler

from .local_auth_state import has_local_auth_profile
from .local_paths import LOCAL_PROFILE_ID
from .local_settings import get_settings_store, parse_schedule_time
from .local_task_queue import LocalTaskQueue

logger = logging.getLogger("form_automation.scheduler")
JOB_ID = "daily_form_submission"
CATCH_UP_JOB_ID = "missed_form_submission"

scheduler = BackgroundScheduler()


def pending_task_is_due_today(
    pending_task: dict | None,
    schedule_time: str,
    now: datetime | None = None,
) -> bool:
    """Return whether a retained task should run as soon as the app is available."""
    if not pending_task:
        return False
    now = now or datetime.now()
    if pending_task.get("scheduled_date") != now.date().isoformat():
        return False
    hour, minute = parse_schedule_time(schedule_time)
    return now.time() >= time(hour, minute)


def work_day_for_date(settings: dict, selected_date: date) -> int | None:
    """Use a calendar override when one exists, otherwise the app default."""
    return settings["calendar_work_days"].get(
        selected_date.isoformat(), settings["work_day"]
    )


def refresh_pending_task_work_day(settings_store, settings: dict) -> dict:
    """Keep the one queued task aligned with the selected date's override."""
    pending_task = settings["pending_task"]
    if pending_task is None:
        return settings
    scheduled_date = date.fromisoformat(pending_task["scheduled_date"])
    work_day = work_day_for_date(settings, scheduled_date)
    if work_day in (1, 2, 3) and pending_task["work_day"] != work_day:
        settings_store.set_pending_task(scheduled_date, work_day)
        return settings_store.get_settings()
    return settings


def run_automation(*, retry: bool = False) -> None:
    settings_store = get_settings_store()
    settings = settings_store.get_settings()
    if not settings["automation_active"]:
        logger.info("Skipping submission because automation is disabled")
        return

    work_day = settings["work_day"]
    if work_day not in (1, 2, 3):
        logger.warning("Skipping submission because no work-day choice is saved")
        return

    schedule_time = settings["schedule_time"]
    if not schedule_time:
        logger.warning("Skipping submission because no schedule time is saved")
        return

    queue = LocalTaskQueue(settings_store)
    settings = refresh_pending_task_work_day(settings_store, settings)
    task = queue.get_due_task(schedule_time, work_day)
    if task is None:
        # A newly saved time is itself a request to run at that time.  Once a
        # prior run has queued tomorrow's task, do not let that bookkeeping
        # prevent a later time change from running again today.
        task = {
            "scheduled_date": date.today().isoformat(),
            "work_day": work_day_for_date(settings, date.today()),
        }
        logger.info("Running the current scheduled time despite a future queued task")

    existing_status = settings["automation_status"]
    if (
        existing_status
        and existing_status["code"] == "session_expired"
        and not retry
    ):
        logger.warning("Skipping submission until the Google account is reconnected")
        return

    if not has_local_auth_profile(LOCAL_PROFILE_ID):
        message = "Connect a Google account before submitting the pending form."
        settings_store.set_automation_status("error", "session_required", message)
        logger.warning(message)
        return

    from .scripts.automation import AutomationError, SessionExpiredError, submit_form

    logger.info("Starting queued Google Form task for %s", task["scheduled_date"])
    def report_progress(message: str) -> None:
        settings_store.set_automation_status("submitting", "submitting", message)

    report_progress("Opening Google Form.")
    try:
        submit_form(
            task["work_day"],
            settings["form_responses"],
            account_email=settings["google_account_email"],
            progress_reporter=report_progress,
        )
    except SessionExpiredError as error:
        settings_store.set_automation_status("error", "session_expired", str(error))
        logger.warning("Google session expired while submitting: %s", error)
    except AutomationError as error:
        settings_store.set_automation_status("error", "form_error", str(error))
        logger.exception("Google Form submission failed")
    except Exception:
        message = "The Google Form could not be submitted because of a browser or network error."
        settings_store.set_automation_status("error", "submission_error", message)
        logger.exception("Google Form submission failed unexpectedly")
    else:
        queue.complete_task(schedule_time, work_day)
        refresh_pending_task_work_day(settings_store, settings_store.get_settings())
        settings_store.set_automation_status(
            "succeeded", "submitted", "Google Form submitted successfully."
        )
        logger.info("Google Form task completed")


def add_user_job(schedule_time: str) -> None:
    hour, minute = parse_schedule_time(schedule_time)
    scheduler.add_job(
        run_automation,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id=JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=None,
    )
    logger.info("Local form job scheduled for %s", schedule_time)


def remove_user_job() -> None:
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)


def remove_catch_up_job() -> None:
    if scheduler.get_job(CATCH_UP_JOB_ID):
        scheduler.remove_job(CATCH_UP_JOB_ID)


def sync_schedule() -> None:
    settings_store = get_settings_store()
    settings = settings_store.get_settings()
    queue = LocalTaskQueue(settings_store)
    if settings["automation_active"] and settings["schedule_time"]:
        if settings["work_day"] in (1, 2, 3):
            if settings["pending_task"] is None:
                queue.schedule_next(settings["schedule_time"], settings["work_day"])
            settings = refresh_pending_task_work_day(
                settings_store, settings_store.get_settings()
            )
        add_user_job(settings["schedule_time"])
        current_settings = settings_store.get_settings()
        if pending_task_is_due_today(
            current_settings["pending_task"], current_settings["schedule_time"]
        ):
            scheduler.add_job(
                run_automation,
                trigger="date",
                run_date=datetime.now(),
                id=CATCH_UP_JOB_ID,
                replace_existing=True,
                max_instances=1,
            )
            logger.info("Queued catch-up submission for today's pending task")
        else:
            remove_catch_up_job()
    else:
        remove_user_job()
        remove_catch_up_job()
        settings_store.clear_pending_task()


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
    sync_schedule()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def wakeup_scheduler() -> None:
    if scheduler.running:
        scheduler.wakeup()
