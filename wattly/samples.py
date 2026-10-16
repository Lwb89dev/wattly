"""Sample bill PDFs, generated with PyMuPDF.

Used by ``python -m wattly --make-samples`` and by the test suite.
Numbers are internally consistent (bands sum to total, readings delta
equals billed kWh, components sum to total) so parsers can be verified
against known ground truth. One PDF is rasterized to an image-only
document to exercise the OCR fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class SampleBill:
    provider: str
    period_start: date
    period_end: date
    issue_date: date
    account: str
    pod: str
    tariff: str
    prev_reading: float
    bands: list[tuple[str, float, float]] = field(default_factory=list)  # label, kWh, EUR/kWh
    fixed_eur: float = 11.84
    tax_rate_per_kwh: float = 0.0771
    tax_flat_eur: float = 3.12

    @property
    def kwh_total(self) -> float:
        return round(sum(b[1] for b in self.bands), 1)

    @property
    def curr_reading(self) -> float:
        return round(self.prev_reading + self.kwh_total, 1)

    @property
    def energy_eur(self) -> float:
        return round(sum(b[1] * b[2] for b in self.bands), 2)

    @property
    def taxes_eur(self) -> float:
        return round(self.kwh_total * self.tax_rate_per_kwh + self.tax_flat_eur, 2)

    @property
    def total_eur(self) -> float:
        return round(self.energy_eur + self.fixed_eur + self.taxes_eur, 2)


def _it_amount(eur: float) -> str:
    s = f"{eur:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _it_kwh(v: float) -> str:
    s = f"{v:,.1f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _it_reading(v: float) -> str:
    s = f"{v:,.1f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _luceverde_lines(b: SampleBill) -> list[tuple[str, int, bool]]:
    L: list[tuple[str, int, bool]] = [
        (b.provider, 13, True),
        ("Via delle Fonti 42 — 20100 Milano", 9, False),
        ("", 9, False),
        (f"Bolletta luce — Data emissione: {b.issue_date:%d/%m/%Y}", 10, False),
        ("Cliente: Mario Rossi            Numero cliente: " + b.account, 10, False),
        (f"Codice POD: {b.pod}      Contratto: {b.tariff}", 10, False),
        ("", 9, False),
        (f"Periodo di fatturazione: dal {b.period_start:%d/%m/%Y} al {b.period_end:%d/%m/%Y}", 11, True),
        ("", 9, False),
        ("DETTAGLIO CONSUMI", 10, True),
    ]
    for label, kwh, price in b.bands:
        L.append(
            (f"Fascia {label}   {_it_kwh(kwh)} kWh      EUR {_it_amount(kwh * price)}", 10, False)
        )
    L += [
        (f"Consumo totale fatturato: {_it_kwh(b.kwh_total)} kWh", 11, True),
        ("", 9, False),
        ("LETTURA CONTATORE", 10, True),
        (
            f"Lettura precedente: {_it_reading(b.prev_reading)} del {b.period_start:%d/%m/%Y}",
            10, False,
        ),
        (
            f"Lettura attuale:    {_it_reading(b.curr_reading)} del {b.period_end:%d/%m/%Y}",
            10, False,
        ),
        ("", 9, False),
        ("RIEPILOGO COSTI", 10, True),
        (f"Spesa per l'energia: EUR {_it_amount(b.energy_eur)}", 10, False),
        (f"Quota fissa (commercializzazione): EUR {_it_amount(b.fixed_eur)}", 10, False),
        (f"Imposte, oneri e accise: EUR {_it_amount(b.taxes_eur)}", 10, False),
        (f"TOTALE BOLLETTA: EUR {_it_amount(b.total_eur)}", 12, True),
    ]
    return L


def _elettra_lines(b: SampleBill) -> list[tuple[str, int, bool]]:
    L: list[tuple[str, int, bool]] = [
        (b.provider, 13, True),
        ("Corso Europa 7 — 20122 Milano", 9, False),
        ("", 9, False),
        (f"Documento emesso il {b.issue_date:%d/%m/%Y}", 10, False),
        (f"Cliente n. {b.account}", 10, False),
        (f"Punto di prelievo (POD): {b.pod}", 10, False),
        ("Offerta luce: Energia Mono", 10, False),
        ("", 9, False),
        (f"Periodo: {b.period_start:%d/%m/%Y} – {b.period_end:%d/%m/%Y}", 11, True),
        ("", 9, False),
        ("CONSUMI", 10, True),
        (f"Consumo: {_it_kwh(b.kwh_total)} kWh (monoraria)", 10, False),
        (
            f"Rilevazioni contatore: da {_it_reading(b.prev_reading)} a "
            f"{_it_reading(b.curr_reading)}",
            10, False,
        ),
        ("", 9, False),
        ("COSTI DELLA FORNITURA", 10, True),
        (f"Fornitura energia elettrica: EUR {_it_amount(b.energy_eur)}", 10, False),
        (f"Canone fisso mensile: EUR {_it_amount(b.fixed_eur)}", 10, False),
        (f"Imposte e oneri di rete: EUR {_it_amount(b.taxes_eur)}", 10, False),
        (f"Totale fattura: EUR {_it_amount(b.total_eur)}", 12, True),
    ]
    return L


def _render_pdf(path: Path, lines: list[tuple[str, int, bool]]) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 60.0
    for text, size, bold in lines:
        if y > 800:  # paginate: content past the page bottom is silently dropped
            page = doc.new_page(width=595, height=842)
            y = 60.0
        if text:
            page.insert_text((60, y), text, fontsize=size,
                             fontname="hebo" if bold else "helv")
        y += size * 1.55
    doc.save(str(path))
    doc.close()


def _rasterize(src: Path, dest: Path, dpi: int = 200) -> None:
    """Create an image-only copy of a PDF (exercises the OCR path)."""
    import fitz

    src_doc = fitz.open(str(src))
    out = fitz.open()
    for page in src_doc:
        pix = page.get_pixmap(dpi=dpi)
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, pixmap=pix)
    out.save(str(dest))
    out.close()
    src_doc.close()


def _enel_classic_lines() -> list[tuple[str, int, bool]]:
    """Enel "bolletta sintetica" 2024 layout: (A)/(B) summary rows."""
    rows: list[tuple[str, int, bool]] = [
        ("Enel Energia - Mercato libero dell'energia", 13, True),
        ("Codice Fiscale", 10, False),
        ("RSSMRA00A00A000A", 10, False),
        ("N° Cliente", 10, True),
        ("987654321", 10, False),
        ("Codice POD", 10, True),
        ("IT012E00009988", 10, False),
        ("Periodo MAG. 2026 - GIU. 2026 - spesa per l'ENERGIA ELETTRICA", 11, True),
        ("Bolletta sintetica riferita alla fattura elettronica n. 1234567890 del 10/07/2026 "
         "valida ai fini fiscali.", 9, False),
        ("", 9, False),
        ("Quanto pago per questa bolletta?", 11, True),
        ("141,05 EUR", 11, False),
        ("Quanto ho consumato?", 11, True),
        ("236 kWh ", 11, False),
        ("consumi rilevati", 9, False),
        ("", 9, False),
        ("Com'è composto l'importo da pagare?", 10, True),
        ("Spesa per l'energia (A)", 10, False),
        ("68,34 EUR", 10, False),
        ("Spesa per il trasporto dell'energia elettrica e la gestione ", 10, False),
        ("del contatore (A)", 10, False),
        ("30,90 EUR", 10, False),
        ("Spesa oneri di sistema (A)", 10, False),
        ("24,66 EUR", 10, False),
        ("Totale imposte e IVA (B)", 10, False),
        ("17,15 EUR", 10, False),
        ("Totale Bolletta", 11, True),
        ("141,05 EUR", 11, False),
        ("", 9, False),
        ("Consumo rilevato (dal 01.05.2026 al 30.06.2026)", 10, True),
        ("F1", 10, False), ("F2", 10, False), ("F3", 10, False), ("Totale energia", 10, True),
        ("54 kWh", 10, False), ("101 kWh", 10, False), ("81 kWh", 10, False), ("236 kWh", 10, False),
        ("Consumo fatturato (dal 01.05.2026 al 30.06.2026)", 10, True),
        ("Mono", 10, False), ("Totale energia", 10, True),
        ("236 kWh", 10, False), ("236 kWh", 10, False),
        ("", 9, False),
        ("Riepilogo delle letture", 10, True),
        ("Data al", 9, False), ("F1", 9, False), ("F2", 9, False), ("F3", 9, False),
        ("Tipologia", 9, False),
        ("30/04/2026", 9, False), ("2.450", 9, False), ("4.120", 9, False), ("3.280", 9, False),
        ("(stimata)", 9, False),
        ("31/05/2026", 9, False), ("2.480", 9, False), ("4.180", 9, False), ("3.330", 9, False),
        ("(rilevata)", 9, False),
        ("30/06/2026", 9, False), ("2.504", 9, False), ("4.221", 9, False), ("3.361", 9, False),
        ("(rilevata)", 9, False),
    ]
    return rows


def _enel_scontrino_lines() -> list[tuple[str, int, bool]]:
    """Enel 2025+ layout: itemised "Scontrino dell'energia", no (A)/(B) rows."""
    return [
        ("Enel Energia - Mercato libero dell'energia", 13, True),
        ("N° Cliente", 10, True),
        ("987654321", 10, False),
        ("Codice POD", 10, True),
        ("IT012E00009988", 10, False),
        ("Periodo MAR. 2026 - APR. 2026 - spesa per l'ENERGIA ELETTRICA", 11, True),
        ("Bolletta sintetica riferita alla fattura elettronica n. 1234567891 del 08/05/2026 "
         "valida ai fini fiscali.", 9, False),
        ("", 9, False),
        ("Quanto pago per questa bolletta?", 11, True),
        ("121,92 EUR", 11, False),
        ("Consumo del periodo", 10, True),
        ("187 kWh ", 11, False),
        ("Consumi Rilevati nel periodo oggetto di fatturazione", 9, False),
        ("", 9, False),
        ("Scontrino dell'energia", 11, True),
        ("QUANTITÀ", 9, True), ("PREZZO MEDIO", 9, True), ("IMPORTO", 9, True),
        ("QUOTA CONSUMI", 10, True),
        ("41,03 EUR", 10, False),
        ("Quota consumi", 10, False),
        ("187 kWh", 10, False),
        ("0,219412 EUR/kWh", 10, False),
        ("41,03 EUR", 10, False),
        ("di cui spesa per la vendita di energia elettrica", 9, False),
        ("0,164491 EUR/kWh", 9, False),
        ("30,76 EUR", 9, False),
        ("QUOTA FISSA E QUOTA POTENZA", 10, True),
        ("68,38 EUR", 10, False),
        ("Quota fissa", 10, False),
        ("2 mesi", 10, False),
        ("21,550000 EUR/mese", 10, False),
        ("43,10 EUR", 10, False),
        ("Quota potenza", 10, False),
        ("6,0 kW x 2 mesi", 10, False),
        ("2,106667 EUR/kW/mese", 10, False),
        ("25,28 EUR", 10, False),
        ("ACCISE E IVA", 10, True),
        ("12,51 EUR", 10, False),
        ("TOTALE BOLLETTA", 11, True),
        ("121,92 EUR", 11, False),
        ("TOTALE DA PAGARE", 11, True),
        ("121,92 EUR", 11, False),
        ("", 9, False),
        ("Consumo fatturato (dal 01.03.2026 al 30.04.2026)", 10, True),
        ("Mono", 10, False), ("Totale energia", 10, True),
        ("187 kWh", 10, False), ("187 kWh", 10, False),
        ("", 9, False),
        ("Riepilogo delle letture", 10, True),
        ("Data al", 9, False), ("Totale", 9, False), ("Tipologia", 9, False),
        ("28/02/2026", 9, False), ("9.912", 9, False), ("(stimata)", 9, False),
        ("31/03/2026", 9, False), ("9.955", 9, False), ("(rilevata)", 9, False),
        ("30/04/2026", 9, False), ("10.099", 9, False), ("(rilevata)", 9, False),
    ]


def _octopus_lines() -> list[tuple[str, int, bool]]:
    return [
        ("BOLLETTA LUCE | Codice Fornitura: A-TEST1234", 13, True),
        ("Octopus Energy Italia Srl, società a socio unico", 9, False),
        ("", 9, False),
        ("La tua bolletta di Aprile 2026", 13, True),
        ("Questo mese dovrai pagare", 11, True),
        ("89,42EUR", 11, False),
        ("", 9, False),
        ("Dati di fatturazione e pagamento", 10, True),
        ("DATA FATTURA: 06/05/2026", 10, False),
        ("PERIODO DI RIFERIMENTO: dal 01/04/2026 al 30/04/2026", 10, False),
        ("CONSUMO FATTURATO: 322 kWh", 11, True),
        ("", 9, False),
        ("Scontrino dell’energia", 11, True),
        ("Quantità", 9, True), ("Prezzo medio", 9, True), ("Importo", 9, True),
        ("Quota per consumi", 10, False),
        ("322 kWh x", 10, False),
        ("0,19 EUR/kWh", 10, False),
        ("61,18 EUR", 10, False),
        ("di cui spesa per vendita energia elettrica", 9, False),
        ("0,15 EUR/kWh", 9, False),
        ("48,30 EUR", 9, False),
        ("Quota fissa", 10, False),
        ("1 mese x", 10, False),
        ("7,92 EUR/mese", 10, False),
        ("7,92 EUR", 10, False),
        ("Quota potenza", 10, False),
        ("6 kW x", 10, False),
        ("1,98 EUR/kW", 10, False),
        ("11,86 EUR", 10, False),
        ("Accise e IVA", 10, True),
        ("8,46 EUR", 10, False),
        ("TOTALE BOLLETTA", 11, True),
        ("89,42 EUR", 11, False),
        ("TOTALE DA PAGARE", 11, True),
        ("89,42 EUR", 11, False),
        ("", 9, False),
        ("CODICE POD:", 10, True),
        ("IT012E00009988", 10, False),
        ("NOME OFFERTA: Octopus Fissa 12M v200", 10, False),
    ]


def sample_bill_specs() -> list[SampleBill]:
    return [
        SampleBill(
            provider="LUCEVERDE ENERGIA S.P.A.",
            period_start=date(2026, 8, 1), period_end=date(2026, 8, 31),
            issue_date=date(2026, 9, 5),
            account="40219376", pod="IT001E12345678",
            tariff="TRIFARIA F1/F2/F3",
            prev_reading=12450.0,
            bands=[("F1", 132.0, 0.151), ("F2", 114.0, 0.143), ("F3", 101.0, 0.138)],
            fixed_eur=11.84,
        ),
        SampleBill(
            provider="ELETTRA S.R.L.",
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
            issue_date=date(2026, 10, 4),
            account="88-451290", pod="IT003E99887766",
            tariff="Monoraria",
            prev_reading=12797.0,
            bands=[("Mono", 312.0, 0.149)],
            fixed_eur=10.90,
        ),
    ]


def build_sample_pdfs(target_dir: str | Path) -> list[Path]:
    """Generate the sample PDF set; returns created paths.

    Includes layout-faithful synthetic bills for every supported provider
    parser (Enel classic, Enel scontrino, Octopus) so the test suite can
    regression-test them without real personal documents.
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    specs = sample_bill_specs()
    paths: list[Path] = []
    for spec in specs:
        lines = _luceverde_lines(spec) if "luceverde" in spec.provider.lower() else _elettra_lines(spec)
        slug = spec.provider.split()[0].lower().replace(".", "")
        path = target / f"wattly_bill_{slug}_{spec.period_start:%Y-%m}.pdf"
        _render_pdf(path, lines)
        paths.append(path)
    scanned = target / f"wattly_bill_luceverde_{specs[0].period_start:%Y-%m}_scanned.pdf"
    _rasterize(paths[0], scanned)
    paths.append(scanned)

    provider_samples = [
        ("enel", _enel_classic_lines()),
        ("enel_scontrino", _enel_scontrino_lines()),
        ("octopus", _octopus_lines()),
    ]
    for slug, lines in provider_samples:
        path = target / f"wattly_bill_{slug}.pdf"
        _render_pdf(path, lines)
        paths.append(path)
    return paths
