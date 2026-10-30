"""Skriver den valda produkten till `products/<id>/` och utkastet till listningen på plattformen (Fas 7a).

- `product.md`: hela produkten. Produktagenten skriver den via LLMGateway; ett tomt eller för kort svar
  ersätts av en regelmall och det står i filen.
- `product.pdf`: samma text som PDF, skriven med standardbiblioteket (Helvetica, WinAnsi). Tecken som inte
  finns i WinAnsi byts mot `?`; därför finns Markdown-filen alltid som original.
- `listing.md`: titel, beskrivning, pris, taggar och upplysning om AI-användning. Inget publiceras; en
  grundare listar för hand.
- `idea.json`: förslaget med kodens beräkningar.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from ..llm import ChatRequest, DataClass, Message
from .product import AGENT, AgentStopped, Idea
from .settings import SETTINGS

AI_DISCLOSURE = ("Den här produkten är skriven med hjälp av AI (språkmodeller) och granskad av en människa "
                 "innan publicering. Den är ingen juridisk eller skattemässig rådgivning.")
MIN_CHARS = 1_500


def write_content(gateway, idea: Idea, data_class: DataClass = DataClass.PUBLIC) -> tuple[str, str]:
    """(markdown, källa). Källan är `model:<leverantör>` eller `rule`."""
    prompt = (f"Skriv hela produkten '{idea.title}' ({idea.format}) på svenska i Markdown för {idea.target_customer}. "
              f"Problemet: {idea.problem}. Minst 6 avsnitt med rubriker, konkreta steg och checklistor. "
              "Inga påhittade lagparagrafer, siffror eller källor; skriv 'kontrollera hos Skatteverket' där det behövs.")
    try:
        r = gateway.complete(AGENT, ChatRequest((Message("user", prompt),), data_class, 4_000))
        if len(r.text.strip()) >= MIN_CHARS:
            return r.text.strip() + "\n", f"model:{r.provider}/{r.model}"
    except Exception as exc:  # noqa: BLE001 — ingen reserv (Robin 2026-10-30)
        raise AgentStopped(f"produktagenten skrev ingen produkt: {type(exc).__name__}: {exc}") from exc
    raise AgentStopped("produktagenten skrev för lite text; ingen regelmall används")


def listing(idea: Idea) -> str:
    tags = ", ".join(sorted({idea.format, "svenska", "mall" if idea.format == "template" else "guide", "frilans"}))
    return textwrap.dedent(f"""\
        # Listning på {SETTINGS.platform} (UTKAST — publiceras för hand av en grundare)

        - **Titel:** {idea.title}
        - **Pris:** {idea.price_cents / 100:.2f} USD
        - **Plattformens avgift:** {idea.fee_cents / 100:.2f} USD per försäljning ({SETTINGS.fee_percent} % + {SETTINGS.fee_fixed_cents / 100:.2f} USD)
        - **Netto per försäljning:** {idea.net_per_sale_cents / 100:.2f} USD (före skatt)
        - **Taggar:** {tags}

        ## Beskrivning
        {idea.problem}. Den här {('mallen' if idea.format == 'template' else 'guiden')} är gjord för {idea.target_customer.lower()}.

        ## Upplysning om AI-användning (måste finnas i listningen)
        {AI_DISCLOSURE}

        ## Stoppkriterier
        - Stoppa och avpublicera: {idea.stop_criteria}
        - Fortsätt: {idea.continue_criteria}
        - Efterfrågan är OVERIFIERAD tills riktig försäljning finns (D-063).
        """)


def _pdf_text(s: str) -> str:
    s = s.encode("cp1252", "replace").decode("cp1252")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(markdown: str, path: Path) -> None:
    """En enkel textbaserad PDF (A4, Helvetica 10 pt), bara standardbiblioteket."""
    lines = []
    for raw in markdown.splitlines():
        lines += textwrap.wrap(raw.lstrip("#").strip() if raw.startswith("#") else raw, 95) or [""]
    pages = [lines[i:i + 60] for i in range(0, len(lines), 60)] or [[]]
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for page in pages:
        body = "BT /F1 10 Tf 13 TL 50 800 Td " + " ".join(f"({_pdf_text(t)}) '" for t in page) + " ET"
        stream = body.encode("cp1252", "replace")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, obj in enumerate(objs, 1):
        offsets.append(len(out))
        data = obj if isinstance(obj, bytes) else obj.encode("cp1252", "replace")
        out += f"{n} 0 obj\n".encode() + data + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def write_product(idea: Idea, content: str, source: str, out_root: Path) -> Path:
    folder = Path(out_root) / idea.id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "product.md").write_text(content, encoding="utf-8")
    write_pdf(content, folder / "product.pdf")
    (folder / "listing.md").write_text(listing(idea), encoding="utf-8")
    (folder / "idea.json").write_text(json.dumps({**idea.as_dict(), "content_source": source}, ensure_ascii=False,
                                                 indent=2) + "\n", encoding="utf-8")
    return folder
