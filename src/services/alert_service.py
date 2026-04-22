"""
SPMS Alert Service
──────────────────
Sends email and SMS notifications when occupancy thresholds are crossed,
the lot fills up, or a daily summary report is due.

Configuration is read from alerts.cfg in the project root.
"""

import configparser
import logging
import os
import smtplib
import threading
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Config path ───────────────────────────────────────────────────────────────

_CFG_PATH = Path(__file__).resolve().parent.parent.parent / 'alerts.cfg'


# ── Alert types ───────────────────────────────────────────────────────────────

class AlertType:
    HIGH_OCCUPANCY     = 'high_occupancy'
    CRITICAL_OCCUPANCY = 'critical_occupancy'
    LOT_FULL           = 'lot_full'
    LOT_RECOVERED      = 'lot_recovered'
    DAILY_REPORT       = 'daily_report'


# ── Main service ──────────────────────────────────────────────────────────────

class AlertService:
    """
    Monitors occupancy and fires email / SMS alerts.

    Usage:
        service = AlertService()
        service.start()
        ...
        service.check_occupancy(total=30, available=3)  # call on every bay update
        service.stop()
    """

    def __init__(self):
        self._cfg = configparser.ConfigParser()
        self._cfg.read(_CFG_PATH, encoding='utf-8')

        # Cooldown tracking: alert_type → datetime of last send
        self._last_sent: dict[str, datetime] = {}
        self._lock = threading.Lock()

        # State tracking
        self._was_full = False
        self._daily_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        logger.info(f"AlertService loaded config from {_CFG_PATH}")

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        """Start the daily report scheduler thread."""
        if self._get_bool('daily_report', 'enabled', False):
            self._daily_thread = threading.Thread(
                target=self._daily_report_loop,
                daemon=True,
                name='spms-daily-report'
            )
            self._daily_thread.start()
            logger.info("Daily report scheduler started")

    def stop(self):
        self._stop_event.set()

    def check_occupancy(self, total: int, available: int):
        """
        Call this whenever bay states change.
        Fires alerts if occupancy crosses configured thresholds.
        """
        if total == 0:
            return

        occupied = total - available
        pct = round((occupied / total) * 100, 1)

        # ── Lot full ──────────────────────────────────────────────────────────
        if available == 0:
            if not self._was_full:
                self._was_full = True
                self._fire(
                    AlertType.LOT_FULL,
                    subject='🚨 Parking Lot Full',
                    body=self._render_email(
                        title='Parking Lot is Full',
                        colour='#f43f5e',
                        icon='🚨',
                        lines=[
                            f'All <strong>{total}</strong> spaces are currently occupied.',
                            'Drivers are being turned away at the entrance.',
                        ],
                        stats={'Total': total, 'Available': 0, 'Occupied': occupied, 'Occupancy': f'{pct}%'}
                    ),
                    sms=f'[SPMS] Parking lot is FULL ({total}/{total} occupied). All bays taken.'
                )
        else:
            # Lot recovered from full
            if self._was_full:
                self._was_full = False
                self._fire(
                    AlertType.LOT_RECOVERED,
                    subject='✅ Parking Spaces Now Available',
                    body=self._render_email(
                        title='Spaces Now Available',
                        colour='#10b981',
                        icon='✅',
                        lines=[
                            f'<strong>{available}</strong> space(s) are now free.',
                            'The lot is accepting vehicles again.',
                        ],
                        stats={'Total': total, 'Available': available, 'Occupied': occupied, 'Occupancy': f'{pct}%'}
                    ),
                    sms=f'[SPMS] Parking space available! {available}/{total} bays now free.'
                )

        # ── Critical threshold ────────────────────────────────────────────────
        critical = self._get_int('thresholds', 'critical_occupancy', 90)
        if pct >= critical and available > 0:
            self._fire(
                AlertType.CRITICAL_OCCUPANCY,
                subject=f'⚠️ Parking Critical — {pct}% Full',
                body=self._render_email(
                    title=f'Critical Occupancy: {pct}%',
                    colour='#f59e0b',
                    icon='⚠️',
                    lines=[
                        f'Occupancy has reached <strong>{pct}%</strong>.',
                        f'Only <strong>{available}</strong> space(s) remaining out of {total}.',
                    ],
                    stats={'Total': total, 'Available': available, 'Occupied': occupied, 'Occupancy': f'{pct}%'}
                ),
                sms=f'[SPMS] CRITICAL: Parking {pct}% full. Only {available} bays left.'
            )
            return  # Don't also fire high if critical already triggered

        # ── High threshold ────────────────────────────────────────────────────
        high = self._get_int('thresholds', 'high_occupancy', 80)
        if pct >= high:
            self._fire(
                AlertType.HIGH_OCCUPANCY,
                subject=f'📊 Parking High Occupancy — {pct}% Full',
                body=self._render_email(
                    title=f'High Occupancy: {pct}%',
                    colour='#3b82f6',
                    icon='📊',
                    lines=[
                        f'Occupancy has reached <strong>{pct}%</strong>.',
                        f'<strong>{available}</strong> space(s) still available out of {total}.',
                    ],
                    stats={'Total': total, 'Available': available, 'Occupied': occupied, 'Occupancy': f'{pct}%'}
                ),
                sms=f'[SPMS] High occupancy: parking {pct}% full. {available} bays left.'
            )

    def send_daily_report(self, total: int, available: int, peak_pct: float = None):
        """Manually trigger a daily summary report."""
        occupied = total - available
        pct = round((occupied / total) * 100, 1) if total > 0 else 0
        now = datetime.now().strftime('%A, %d %B %Y')

        lines = [
            f'Here is your daily parking summary for <strong>{now}</strong>.',
        ]
        if peak_pct is not None:
            lines.append(f'Peak occupancy today: <strong>{peak_pct}%</strong>.')

        self._fire(
            AlertType.DAILY_REPORT,
            subject=f'📋 SPMS Daily Report — {now}',
            body=self._render_email(
                title='Daily Parking Report',
                colour='#8b5cf6',
                icon='📋',
                lines=lines,
                stats={
                    'Total Bays':  total,
                    'Available':   available,
                    'Occupied':    occupied,
                    'Current Occupancy': f'{pct}%',
                    **(({'Peak Occupancy': f'{peak_pct}%'}) if peak_pct else {})
                }
            ),
            sms=f'[SPMS] Daily report: {occupied}/{total} bays occupied ({pct}%).',
            force=True  # Always send daily reports, ignore cooldown
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _fire(self, alert_type: str, subject: str, body: str, sms: str, force=False):
        """Send email + SMS if cooldown has passed."""
        if not force:
            cooldown = self._get_int('thresholds', 'cooldown_minutes', 30)
            with self._lock:
                last = self._last_sent.get(alert_type)
                if last and datetime.now() - last < timedelta(minutes=cooldown):
                    logger.debug(f"Alert '{alert_type}' suppressed — cooldown active")
                    return
                self._last_sent[alert_type] = datetime.now()

        # Fire in background thread so we never block the main event loop
        threading.Thread(
            target=self._send_all,
            args=(subject, body, sms),
            daemon=True
        ).start()

    def _send_all(self, subject: str, body: str, sms: str):
        self._send_email(subject, body)
        self._send_sms(sms)

    # ── Email ──────────────────────────────────────────────────────────────────

    def _send_email(self, subject: str, body: str):
        if not self._get_bool('email', 'enabled', False):
            return

        try:
            host       = self._cfg.get('email', 'smtp_host', fallback='smtp.gmail.com')
            port       = self._get_int('email', 'smtp_port', 587)
            username   = self._cfg.get('email', 'username', fallback='')
            password   = self._cfg.get('email', 'password', fallback='')
            from_name  = self._cfg.get('email', 'from_name', fallback='SPMS Alerts')
            recipients = [r.strip() for r in self._cfg.get('email', 'recipients', fallback='').split(',') if r.strip()]

            if not username or not recipients:
                logger.warning("Email: username or recipients not configured")
                return

            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From']    = f'{from_name} <{username}>'
            msg['To']      = ', '.join(recipients)
            msg.attach(MIMEText(body, 'html'))

            with smtplib.SMTP(host, port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(username, password)
                smtp.sendmail(username, recipients, msg.as_string())

            logger.info(f"Email sent: '{subject}' → {recipients}")

        except Exception as e:
            logger.error(f"Email send failed: {e}")

    # ── SMS ────────────────────────────────────────────────────────────────────

    def _send_sms(self, message: str):
        if not self._get_bool('sms', 'enabled', False):
            return

        try:
            from twilio.rest import Client  # optional dependency

            sid        = self._cfg.get('sms', 'twilio_sid', fallback='')
            token      = self._cfg.get('sms', 'twilio_token', fallback='')
            from_num   = self._cfg.get('sms', 'from_number', fallback='')
            recipients = [r.strip() for r in self._cfg.get('sms', 'recipients', fallback='').split(',') if r.strip()]

            if not sid or not token or not recipients:
                logger.warning("SMS: Twilio credentials or recipients not configured")
                return

            client = Client(sid, token)
            for number in recipients:
                client.messages.create(body=message, from_=from_num, to=number)
                logger.info(f"SMS sent to {number}")

        except ImportError:
            logger.warning("SMS disabled — install twilio: pip install twilio")
        except Exception as e:
            logger.error(f"SMS send failed: {e}")

    # ── Daily report loop ──────────────────────────────────────────────────────

    def _daily_report_loop(self):
        """Background thread — fires the daily report at the configured time."""
        send_time_str = self._cfg.get('daily_report', 'send_time', fallback='08:00')
        try:
            h, m = map(int, send_time_str.split(':'))
        except ValueError:
            h, m = 8, 0

        logger.info(f"Daily report scheduled at {h:02d}:{m:02d}")
        last_sent_date = None

        while not self._stop_event.is_set():
            now = datetime.now()
            if now.hour == h and now.minute == m and now.date() != last_sent_date:
                last_sent_date = now.date()
                logger.info("Firing scheduled daily report")
                # Stats will be None unless injected — send what we can
                self.send_daily_report(total=0, available=0)
            self._stop_event.wait(30)  # Check every 30 seconds

    # ── Config helpers ─────────────────────────────────────────────────────────

    def _get_bool(self, section: str, key: str, default: bool) -> bool:
        try:
            return self._cfg.getboolean(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return default

    def _get_int(self, section: str, key: str, default: int) -> int:
        try:
            return self._cfg.getint(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return default

    # ── Email HTML template ────────────────────────────────────────────────────

    @staticmethod
    def _render_email(title: str, colour: str, icon: str, lines: list[str], stats: dict) -> str:
        stats_rows = ''.join(
            f'<tr><td style="padding:6px 12px;color:#94a3b8;font-size:13px;">{k}</td>'
            f'<td style="padding:6px 12px;color:#f1f5f9;font-size:13px;font-weight:600;">{v}</td></tr>'
            for k, v in stats.items()
        )
        body_lines = ''.join(f'<p style="margin:0 0 8px;color:#cbd5e1;font-size:14px;line-height:1.6;">{l}</p>' for l in lines)

        return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#060a13;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#060a13;padding:32px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#0c1221;border-radius:16px;border:1px solid rgba(255,255,255,0.06);overflow:hidden;">

        <!-- Header bar -->
        <tr><td style="background:linear-gradient(135deg,{colour}22,{colour}11);border-bottom:2px solid {colour};padding:24px 32px;">
          <table cellpadding="0" cellspacing="0"><tr>
            <td style="font-size:32px;padding-right:12px;">{icon}</td>
            <td>
              <div style="font-size:10px;font-weight:700;letter-spacing:2px;color:{colour};text-transform:uppercase;margin-bottom:4px;">Smart Parking Management System</div>
              <div style="font-size:20px;font-weight:700;color:#f1f5f9;">{title}</div>
            </td>
          </tr></table>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:24px 32px;">
          {body_lines}
        </td></tr>

        <!-- Stats table -->
        <tr><td style="padding:0 32px 24px;">
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="background:#111827;border-radius:10px;border:1px solid rgba(255,255,255,0.06);border-collapse:collapse;">
            {stats_rows}
          </table>
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:16px 32px;border-top:1px solid rgba(255,255,255,0.06);">
          <p style="margin:0;color:#475569;font-size:11px;">
            Sent by SPMS Alert Service &bull; {datetime.now().strftime('%d %b %Y, %H:%M')}
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
