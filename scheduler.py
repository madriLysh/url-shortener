from apscheduler.schedulers.background import BackgroundScheduler

from config import Config
from services import URLService

scheduler = BackgroundScheduler()


def start_scheduler(service: URLService) -> None:
    scheduler.add_job(
        service.sync_clicks_to_db,
        trigger= "interval",
        seconds= Config.SYNC_INTERVAL
    )
    scheduler.add_job(
        service.deactivate_expired_urls,
        trigger="interval",
        seconds=Config.EXPIRY_CLEANUP_INTERVAL
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown()
