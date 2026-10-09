import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .local_auth_state import get_local_auth_state
from .local_paths import LOCAL_PROFILE_ID
from .local_settings import get_settings_store, parse_schedule_time
from .local_task_queue import LocalTaskQueue

logger = logging.getLogger("form_automation.scheduler")
JOB_ID = "daily_form_submission"

scheduler = BackgroundScheduler()


def run_automation() -> None:
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
    task = queue.get_due_task(schedule_time, work_day)
    if task is None:
        logger.info("No queued form task is due yet")
        return

    storage_state = get_local_auth_state(LOCAL_PROFILE_ID)
    if storage_state is None:
        logger.warning("Skipping submission because no Google session is saved")
        return

    from .scripts.automation import submit_form

    logger.info("Starting queued Google Form task for %s", task["scheduled_date"])
    submit_form(task["work_day"], storage_state, settings["form_responses"])
    queue.complete_task(schedule_time, work_day)
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


def sync_schedule() -> None:
    settings_store = get_settings_store()
    settings = settings_store.get_settings()
    queue = LocalTaskQueue(settings_store)
    if settings["automation_active"] and settings["schedule_time"]:
        if settings["work_day"] in (1, 2, 3):
            queue.schedule_next(settings["schedule_time"], settings["work_day"])
        add_user_job(settings["schedule_time"])
    else:
        remove_user_job()
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
