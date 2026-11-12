"""Notiser till grundarna (Command Center Del 5, D-091, FR-33): ntfy och Gmail SMTP. Gratis, inget SMS.

- `py -m aie notify run`    larm ur revisionsloggen sedan förra gången (körs av control-ingest och company-daily)
- `py -m aie notify daily`  den dagliga sammanfattningen med e-post (körs 21:00 svensk vintertid av notify-daily)

Hemligheter läses bara ur miljön och skrivs aldrig ut: `NTFY_TOPIC`, `GMAIL_USER`, `GMAIL_APP_PASSWORD` och
`NOTIFY_TO` (mottagarna, valfri; annars går e-posten till `GMAIL_USER`). Saknas en hemlighet hoppas kanalen över utan fel.
"""
from .channels import Channels, send_email, send_ntfy
from .triggers import GENERIC, Alert, collect

__all__ = ["Alert", "Channels", "GENERIC", "collect", "send_email", "send_ntfy"]
