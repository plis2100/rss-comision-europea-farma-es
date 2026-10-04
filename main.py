import re
import html
import hashlib
import datetime as dt
import xml.etree.ElementTree as ET

from email.utils import parsedate_to_datetime, format_datetime

import requests
import feedparser
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURACIÓN
# ============================================================

OUTPUT_FILE = "feed.xml"

RSS_SOURCES = [
    "https://ec.europa.eu/health/documents/community-register/html/rss/rss_last.rss",
    "https://ec.europa.eu/health/documents/community-register/html/rss/rss_status_h.rss",
    "https://ec.europa.eu/health/documents/community-register/html/rss/rss_orph.rss",
    "https://ec.europa.eu/health/documents/community-register/html/rss/rss_referrals.rss",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140 Safari/537.36"
    )
}


# ============================================================
# EMPRESAS Y PRODUCTOS A VIGILAR
# ============================================================
#
# Se busca tanto el nombre de la empresa como medicamentos,
# principios activos y términos relacionados.
#
# Puedes añadir más palabras cuando quieras.
# ============================================================

COMPANIES = {

    "ALMIRALL": [
        "almirall",
        "ilumetri",
        "tildrakizumab",
        "ebglyss",
        "lebrikizumab",
        "klisyri",
        "tirbanibulin",
        "tirbanibulina",
        "seysera",
        "sarecycline",
        "sareciclina",
        "wynzora",
        "calcipotriol",
        "betamethasone",
        "betametasona",
    ],

    "PHARMA MAR": [
        "pharma mar",
        "pharmamar",
        "yondelis",
        "trabectedin",
        "trabectedina",
        "zepzelca",
        "lurbinectedin",
        "lurbinectedina",
        "aplidin",
        "plitidepsin",
        "plitidepsina",
    ],

    "ROVI": [
        "laboratorios farmaceuticos rovi",
        "laboratorios farmacéuticos rovi",
        "laboratorios rovi",
        "rovi",
        "okedi",
        "risperidone",
        "risperidona",
        "risperdal",
        "bemiparin",
        "bemiparina",
        "hibor",
        "becat",
        "enoxaparin",
        "enoxaparina",
    ],

    "FAES FARMA": [
        "faes farma",
        "faes pharma",
        "faes",
        "bilastine",
        "bilastina",
        "ilaxten",
        "bilaxiten",
        "bilaxten",
        "hidroferol",
        "calcifediol",
        "venosmil",
        "hidrosmina",
    ],

    "REIG JOFRE": [
        "reig jofre",
        "laboratorio reig jofre",
        "laboratorios reig jofre",
        "reig-jofre",
        "fortecortin",
        "dexamethasone",
        "dexametasona",
        "remifentanil",
        "vancomycin",
        "vancomicina",
    ],

    # ========================================================
    # BME GROWTH
    # ========================================================

    "LABIANA HEALTH": [
        "labiana",
        "labiana health",
        "labiana pharmaceuticals",
    ],

    "NATAC": [
        "natac",
        "natac natural ingredients",
        "natac biotech",
    ],

    "VYTRUS BIOTECH": [
        "vytrus",
        "vytrus biotech",
        "vytrus biotechnologies",
    ],

    "BIOTECHNOLOGY ASSETS": [
        "biotechnology assets",
        "biat",
        "biotechnology assets s.a.",
        "biotechnology assets sa",
    ],

    "1NKEMIA": [
        "1nkemia",
        "1nkemia iuct group",
        "iuct",
    ],
}


# ============================================================
# UTILIDADES
# ============================================================

def clean_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))
    soup = BeautifulSoup(value, "html.parser")
    value = soup.get_text(" ", strip=True)

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize(value):
    value = clean_text(value).lower()

    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
        "ñ": "n",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    return value


def parse_date(entry):
    """
    Obtiene la fecha real de la entrada.
    """

    candidates = [
        entry.get("published"),
        entry.get("updated"),
        entry.get("created"),
    ]

    for value in candidates:

        if not value:
            continue

        try:
            parsed = parsedate_to_datetime(value)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)

            return parsed

        except Exception:
            pass

        # Fechas tipo 04/10/2026
        for fmt in [
            "%d/%m/%Y",
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d.%m.%Y",
        ]:

            try:
                parsed = dt.datetime.strptime(
                    value.strip(),
                    fmt
                )

                return parsed.replace(
                    tzinfo=dt.timezone.utc
                )

            except Exception:
                pass

    # feedparser puede dar estructura de fecha
    for field in [
        "published_parsed",
        "updated_parsed",
        "created_parsed",
    ]:

        value = entry.get(field)

        if value:

            try:
                return dt.datetime(
                    value.tm_year,
                    value.tm_mon,
                    value.tm_mday,
                    value.tm_hour,
                    value.tm_min,
                    value.tm_sec,
                    tzinfo=dt.timezone.utc,
                )

            except Exception:
                pass

    return None


def format_spanish_date(date_value):

    if not date_value:
        return "SIN FECHA"

    return date_value.strftime("%d/%m/%Y")


# ============================================================
# IDENTIFICAR EMPRESA
# ============================================================

def find_company(text):

    normalized = normalize(text)

    matches = []

    for company, keywords in COMPANIES.items():

        for keyword in keywords:

            if normalize(keyword) in normalized:

                matches.append(
                    (
                        company,
                        keyword,
                        len(keyword)
                    )
                )

    if not matches:
        return None, None

    # Prioriza coincidencia más específica
    matches.sort(
        key=lambda x: x[2],
        reverse=True
    )

    return matches[0][0], matches[0][1]


# ============================================================
# IDENTIFICAR MEDICAMENTO / PRINCIPIO ACTIVO
# ============================================================

def find_product(company, text):

    normalized = normalize(text)

    if company not in COMPANIES:
        return None

    matches = []

    for keyword in COMPANIES[company]:

        normalized_keyword = normalize(keyword)

        if normalized_keyword in normalized:

            # Evitamos usar simplemente el nombre de empresa
            company_normalized = normalize(company)

            if normalized_keyword == company_normalized:
                continue

            matches.append(
                (
                    keyword,
                    len(keyword)
                )
            )

    if not matches:
        return None

    matches.sort(
        key=lambda x: x[1],
        reverse=True
    )

    return matches[0][0]


# ============================================================
# DETERMINAR TIPO DE NOVEDAD
# ============================================================

def detect_event(text):

    t = normalize(text)

    rules = [

        (
            [
                "withdrawal",
                "withdrawn",
                "retirada",
            ],
            "Retirada"
        ),

        (
            [
                "suspension",
                "suspended",
                "suspendido",
            ],
            "Suspensión"
        ),

        (
            [
                "refusal",
                "refused",
                "denegacion",
                "denegación",
            ],
            "Denegación"
        ),

        (
            [
                "transfer",
                "transferred",
                "transferencia",
            ],
            "Transferencia"
        ),

        (
            [
                "orphan designation",
                "designation",
                "designacion",
                "designación",
            ],
            "Designación huérfana"
        ),

        (
            [
                "marketing authorisation",
                "marketing authorization",
                "authorisation",
                "authorization",
                "autorizacion",
                "autorización",
            ],
            "Autorización"
        ),

        (
            [
                "commission decision",
                "decision",
                "decisión",
            ],
            "Decisión"
        ),

        (
            [
                "annex",
                "annexes",
                "anexo",
            ],
            "Nuevo documento"
        ),

    ]

    for keywords, label in rules:

        for keyword in keywords:

            if normalize(keyword) in t:
                return label

    return "Actualización"


# ============================================================
# DESCARGAR RSS
# ============================================================

def download_feed(url):

    print(f"Descargando: {url}")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=45
    )

    response.raise_for_status()

    return feedparser.parse(
        response.content
    )


# ============================================================
# RECOPILAR RESULTADOS
# ============================================================

def collect_entries():

    results = []

    seen = set()

    for source_url in RSS_SOURCES:

        try:

            feed = download_feed(
                source_url
            )

        except Exception as exc:

            print(
                f"ERROR descargando {source_url}: {exc}"
            )

            continue

        print(
            f"Entradas encontradas: {len(feed.entries)}"
        )

        for entry in feed.entries:

            title = clean_text(
                entry.get("title", "")
            )

            summary = clean_text(
                entry.get("summary", "")
            )

            description = clean_text(
                entry.get("description", "")
            )

            link = (
                entry.get("link")
                or entry.get("id")
                or source_url
            )

            # Incluimos todos los campos posibles
            full_text = " ".join(
                [
                    title,
                    summary,
                    description,
                    link,
                ]
            )

            company, matched_keyword = find_company(
                full_text
            )

            if not company:
                continue

            product = find_product(
                company,
                full_text
            )

            event = detect_event(
                full_text
            )

            date_value = parse_date(
                entry
            )

            # Si no encontramos fecha en los campos,
            # intentamos extraerla del propio texto.
            if date_value is None:

                match = re.search(
                    r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b",
                    full_text
                )

                if match:

                    try:

                        date_value = dt.datetime(
                            int(match.group(3)),
                            int(match.group(2)),
                            int(match.group(1)),
                            tzinfo=dt.timezone.utc
                        )

                    except Exception:
                        pass

            date_text = format_spanish_date(
                date_value
            )

            # ==================================================
            # TÍTULO PARA FEEDLY
            # ==================================================

            output_title = (
                f"COMISIÓN EUROPEA | "
                f"{date_text} | "
                f"{company}"
            )

            if product:

                output_title += (
                    f" | {product.upper()}"
                )

            output_title += (
                f" | {event}"
            )

            # ==================================================
            # GUID ESTABLE
            # ==================================================

            guid_source = (
                link
                + "|"
                + title
                + "|"
                + company
            )

            guid = hashlib.sha256(
                guid_source.encode(
                    "utf-8"
                )
            ).hexdigest()

            if guid in seen:
                continue

            seen.add(guid)

            results.append(
                {
                    "title": output_title,
                    "original_title": title,
                    "company": company,
                    "product": product or "",
                    "event": event,
                    "date": date_value,
                    "date_text": date_text,
                    "link": link,
                    "summary": summary or description,
                    "guid": guid,
                    "source": source_url,
                    "matched_keyword": matched_keyword,
                }
            )

    # Más reciente primero
    results.sort(
        key=lambda x: (
            x["date"]
            or dt.datetime(
                1970,
                1,
                1,
                tzinfo=dt.timezone.utc
            )
        ),
        reverse=True
    )

    return results


# ============================================================
# GENERAR RSS PARA FEEDLY
# ============================================================

def render_rss(results):

    rss = ET.Element(
        "rss",
        {
            "version": "2.0"
        }
    )

    channel = ET.SubElement(
        rss,
        "channel"
    )

    ET.SubElement(
        channel,
        "title"
    ).text = (
        "Comisión Europea · Farma cotizada España"
    )

    ET.SubElement(
        channel,
        "link"
    ).text = (
        "https://ec.europa.eu/health/"
        "documents/community-register/"
    )

    ET.SubElement(
        channel,
        "description"
    ).text = (
        "Novedades del Union Register de la Comisión Europea "
        "relacionadas con farmacéuticas y biotecnológicas "
        "cotizadas en España y BME Growth."
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "es"

    ET.SubElement(
        channel,
        "lastBuildDate"
    ).text = format_datetime(
        dt.datetime.now(
            dt.timezone.utc
        )
    )

    for result in results:

        item = ET.SubElement(
            channel,
            "item"
        )

        ET.SubElement(
            item,
            "title"
        ).text = result["title"]

        ET.SubElement(
            item,
            "link"
        ).text = result["link"]

        guid = ET.SubElement(
            item,
            "guid",
            {
                "isPermaLink": "false"
            }
        )

        guid.text = result["guid"]

        # IMPORTANTE PARA FEEDLY:
        # pubDate contiene la fecha real de la publicación.
        if result["date"]:

            ET.SubElement(
                item,
                "pubDate"
            ).text = format_datetime(
                result["date"]
            )

        description_parts = [

            f"<b>Empresa:</b> "
            f"{html.escape(result['company'])}",

            f"<b>Fecha:</b> "
            f"{html.escape(result['date_text'])}",

            f"<b>Tipo:</b> "
            f"{html.escape(result['event'])}",

        ]

        if result["product"]:

            description_parts.append(
                f"<b>Medicamento / principio activo:</b> "
                f"{html.escape(result['product'])}"
            )

        if result["original_title"]:

            description_parts.append(
                f"<b>Título original:</b> "
                f"{html.escape(result['original_title'])}"
            )

        if result["summary"]:

            description_parts.append(
                f"<b>Descripción:</b> "
                f"{html.escape(result['summary'])}"
            )

        description_parts.append(
            f"<b>Fuente:</b> Comisión Europea "
            f"– Union Register of Medicinal Products"
        )

        ET.SubElement(
            item,
            "description"
        ).text = (
            "<br><br>".join(
                description_parts
            )
        )

    tree = ET.ElementTree(
        rss
    )

    ET.indent(
        tree,
        space="  "
    )

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "========================================"
    )

    print(
        "RSS COMISIÓN EUROPEA - FARMA ESPAÑA"
    )

    print(
        "========================================"
    )

    results = collect_entries()

    print(
        f"\nTotal entradas filtradas: {len(results)}"
    )

    for result in results[:20]:

        print(
            result["title"]
        )

    render_rss(
        results
    )

    print(
        f"\nRSS generada correctamente: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
