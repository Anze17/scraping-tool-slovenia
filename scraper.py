#!/usr/bin/env python3
"""
Google Maps S.P. Scraper
Poišče podjetja na Google Maps, izvleče maile in spletne strani,
ter sestavi email draft.
"""

import re
import time
import argparse
import sys
import os
import functools

# Flush output takoj (vidno v konzoli v živo)
print = functools.partial(print, flush=True)
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

COPYRIGHT_YEAR_RE = re.compile(r"(?:©|copyright|&copy;)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})", re.I)
JQUERY_OLD_RE = re.compile(r"jquery[.-](\d+\.\d+)", re.I)


def score_website(url: str, timeout: int = 10) -> dict:
    """
    Oceni kakovost spletne strani. Nižji score = slabša stran = boljši kandidat.
    Vrne dict z: score (0-100), ocena (Slaba/Srednja/Dobra), razlogi.
    """
    issues = []
    score = 100

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        # 1. HTTPS
        if not url.startswith("https"):
            score -= 20
            issues.append("Nima HTTPS")

        # 2. Mobilni prikaz (viewport)
        viewport = soup.find("meta", attrs={"name": re.compile(r"viewport", re.I)})
        if not viewport:
            score -= 20
            issues.append("Ni mobilno prilagojena")

        # 3. Meta description
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
        if not meta_desc or not meta_desc.get("content", "").strip():
            score -= 10
            issues.append("Ni meta opisa")

        # 4. Staro copyright leto
        current_year = datetime.now().year
        footer_text = ""
        footer = soup.find("footer")
        if footer:
            footer_text = footer.get_text(" ")
        else:
            footer_text = html[-3000:]  # zadnji del strani

        years = COPYRIGHT_YEAR_RE.findall(footer_text)
        if years:
            latest_year = max(int(y) for y in years)
            age = current_year - latest_year
            if age >= 5:
                score -= 25
                issues.append(f"Copyright {latest_year} ({age} let stara)")
            elif age >= 3:
                score -= 15
                issues.append(f"Copyright {latest_year} ({age} leta stara)")
            elif age >= 2:
                score -= 5
                issues.append(f"Copyright {latest_year}")

        # 5. Stara jQuery verzija
        jq = JQUERY_OLD_RE.search(html)
        if jq:
            ver = jq.group(1)
            major = int(ver.split(".")[0])
            if major < 2:
                score -= 15
                issues.append(f"Stara jQuery {ver}")
            elif major < 3:
                score -= 5
                issues.append(f"jQuery {ver}")

        # 6. Flash
        if re.search(r"\.swf[\"' ]|<object[^>]+flash", html, re.I):
            score -= 30
            issues.append("Uporablja Flash")

        # 7. Tabele za layout
        tables = soup.find_all("table")
        if len(tables) > 3:
            layout_tables = [t for t in tables if not t.find_parent(["thead", "tbody", "article", "main"])]
            if len(layout_tables) > 2:
                score -= 10
                issues.append("Tabele za postavitev (stari dizajn)")

        # 8. Zelo malo vsebine
        text_len = len(soup.get_text(strip=True))
        if text_len < 300:
            score -= 15
            issues.append("Zelo malo vsebine")

        score = max(0, score)

        if score <= 40:
            ocena = "Slaba"
        elif score <= 65:
            ocena = "Srednja"
        else:
            ocena = "Dobra"

        return {"score": score, "ocena": ocena, "razlogi": issues}

    except Exception:
        return {"score": 0, "ocena": "Nedosegljiva", "razlogi": ["Stran ni dostopna"]}


# Emaili ki jih ignoriramo (privacy policies, slike, etc.)
IGNORE_EMAIL_DOMAINS = {
    "example.com", "sentry.io", "wixpress.com", "squarespace.com",
    "wordpress.com", "googletagmanager.com", "schema.org",
    "w3.org", "example.org", "yourdomain.com", "domain.com",
}


def extract_emails_from_url(url: str, timeout: int = 10) -> list[str]:
    """Obišče spletno stran in poišče vse email naslove."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # Poišči mailto: linke (najbolj zanesljivo)
        emails = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("mailto:"):
                email = href[7:].split("?")[0].strip().lower()
                if email:
                    emails.add(email)

        # Fallback: regex po celotnem besedilu
        if not emails:
            text = soup.get_text(" ", strip=True)
            found = EMAIL_REGEX.findall(text)
            emails.update(e.lower() for e in found)

        # Filtriraj nekoristne emaile
        emails = {
            e for e in emails
            if not any(e.endswith(d) for d in IGNORE_EMAIL_DOMAINS)
            and "@" in e
            and len(e) < 100
        }
        return sorted(emails)

    except Exception as e:
        print(f"  [!] Napaka pri branju {url}: {e}")
        return []


def scrape_google_maps(query: str, max_results: int = 20) -> list[dict]:
    """Scrapa Google Maps in vrne seznam podjetij."""
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="sl-SI",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        search_url = f"https://www.google.com/maps/search/{requests.utils.quote(query)}"
        print(f"[*] Iščem: {query}")
        print(f"[*] URL: {search_url}")

        try:
            page.goto(search_url, timeout=30000)
            page.wait_for_timeout(3000)

            # Zavrni cookies če se pojavi dialog
            try:
                page.click('button[aria-label*="Reject"], button[aria-label*="Zavrni"], form:has(button) button:first-child', timeout=3000)
                page.wait_for_timeout(1000)
            except Exception:
                pass

            # Počakaj da se naloži seznam
            page.wait_for_selector('div[role="feed"]', timeout=15000)

            # Scrollaj da naloži več rezultatov
            feed = page.query_selector('div[role="feed"]')
            loaded = 0
            prev_count = 0
            max_scrolls = 10

            for scroll_i in range(max_scrolls):
                items = page.query_selector_all('div[role="feed"] > div > div[jsaction]')
                loaded = len(items)
                print(f"  Naloženih {loaded} rezultatov...", end="\r")

                if loaded >= max_results:
                    break
                if loaded == prev_count and scroll_i > 2:
                    break
                prev_count = loaded

                if feed:
                    feed.evaluate("el => el.scrollTop += 1500")
                page.wait_for_timeout(2000)

            print()

            # Klikni na vsak rezultat in izvleci podatke
            items = page.query_selector_all('div[role="feed"] > div > div[jsaction]')
            print(f"[*] Najdenih {len(items)} rezultatov, obdelujem prvih {min(len(items), max_results)}...")

            for i, item in enumerate(items[:max_results]):
                try:
                    item.click()
                    page.wait_for_timeout(2500)

                    biz = {}

                    # Ime
                    name_el = page.query_selector('h1.DUwDvf, h1[class*="fontHeadline"]')
                    biz["ime"] = name_el.inner_text().strip() if name_el else "?"

                    # Kategorija
                    cat_el = page.query_selector('button[jsaction*="category"], .DkEaL')
                    biz["kategorija"] = cat_el.inner_text().strip() if cat_el else ""

                    # Naslov
                    addr_el = page.query_selector('button[data-item-id="address"] .Io6YTe')
                    biz["naslov"] = addr_el.inner_text().strip() if addr_el else ""

                    # Telefon
                    phone_el = page.query_selector('button[data-item-id*="phone"] .Io6YTe')
                    biz["telefon"] = phone_el.inner_text().strip() if phone_el else ""

                    # Spletna stran
                    web_el = page.query_selector('a[data-item-id="authority"]')
                    biz["spletna_stran"] = web_el.get_attribute("href") if web_el else ""

                    # Google Maps URL
                    biz["maps_url"] = page.url

                    if biz["ime"] != "?":
                        results.append(biz)
                        status = f"  [{i+1}] {biz['ime']}"
                        if biz["spletna_stran"]:
                            status += f" — {biz['spletna_stran']}"
                        print(status)

                except PlaywrightTimeout:
                    print(f"  [!] Timeout pri rezultatu {i+1}, preskakujem...")
                except Exception as e:
                    print(f"  [!] Napaka pri rezultatu {i+1}: {e}")

        except PlaywrightTimeout:
            print("[!] Timeout — Google Maps se ni naložil. Preveri internetno povezavo.")
        except Exception as e:
            print(f"[!] Napaka pri scrapanju: {e}")
        finally:
            browser.close()

    return results


def enrich_with_emails(businesses: list[dict], min_score_threshold: int = 66) -> list[dict]:
    """Za vsako podjetje s spletno stranjo oceni kakovost in poišče email."""
    print(f"\n[*] Ocenjujem spletne strani in iscem emaile...")
    for biz in businesses:
        url = biz.get("spletna_stran", "")
        if not url:
            biz["emaili"] = []
            biz["web_score"] = None
            print(f"  Preskakujem (ni spleta): {biz['ime']}")
            continue

        # Oceni kakovost strani
        ws = score_website(url)
        biz["web_score"] = ws

        score_tag = f"[{ws['ocena']} {ws['score']}/100]"
        if ws["razlogi"]:
            score_tag += f" {', '.join(ws['razlogi'])}"

        # Preskoči dobre strani
        if ws["score"] >= min_score_threshold:
            biz["emaili"] = []
            print(f"  Preskakujem (dobra stran): {biz['ime']} {score_tag}")
            continue

        print(f"  Preverjam: {biz['ime']} {score_tag}")
        emails = extract_emails_from_url(url)

        # Če na homepage ni emaila, preveri /kontakt ali /contact
        if not emails:
            base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            for path in ["/kontakt", "/contact", "/kontakti", "/o-nas", "/about"]:
                contact_url = base + path
                emails = extract_emails_from_url(contact_url, timeout=8)
                if emails:
                    break

        biz["emaili"] = emails
        if emails:
            print(f"    [+] Najdeni maili: {', '.join(emails)}")
        else:
            print(f"    — Ni maila")

    return businesses


def generate_email_draft(
    businesses: list[dict],
    predmet: str,
    sporocilo_template: str,
    output_file: str,
) -> None:
    """Sestavi email draft datoteko."""

    with_email = [b for b in businesses if b.get("emaili")]
    without_email = [b for b in businesses if not b.get("emaili")]

    lines = []
    lines.append("=" * 70)
    lines.append("EMAIL DRAFT — Generiran: " + datetime.now().strftime("%d.%m.%Y %H:%M"))
    lines.append("=" * 70)
    with_bad_web = [b for b in businesses if b.get("web_score") and b["web_score"]["score"] < 100]
    no_web = [b for b in businesses if not b.get("spletna_stran")]
    lines.append(f"Skupaj najdenih:    {len(businesses)} podjetij")
    lines.append(f"Slaba/brez spleta:  {len(with_bad_web) + len(no_web)}")
    lines.append(f"Z emailom (v draftu): {len(with_email)}")
    lines.append("")

    if with_email:
        lines.append("=" * 70)
        lines.append("PODJETJA Z EMAILOM — pripravljeni za pošiljanje")
        lines.append("=" * 70)
        lines.append("")

        for biz in with_email:
            for email in biz["emaili"]:
                lines.append("-" * 50)
                lines.append(f"PREJEMNIK: {email}")
                lines.append(f"IME:       {biz['ime']}")
                if biz.get("naslov"):
                    lines.append(f"NASLOV:    {biz['naslov']}")
                if biz.get("telefon"):
                    lines.append(f"TELEFON:   {biz['telefon']}")
                if biz.get("spletna_stran"):
                    lines.append(f"SPLET:     {biz['spletna_stran']}")
                ws = biz.get("web_score")
                if ws:
                    razlogi = ", ".join(ws["razlogi"]) if ws["razlogi"] else "-"
                    lines.append(f"OCENA:     {ws['ocena']} ({ws['score']}/100) — {razlogi}")
                lines.append("")
                lines.append(f"ZADEVA: {predmet}")
                lines.append("")
                # Personalizirano sporocilo
                msg = sporocilo_template.replace("{ime}", biz["ime"])
                lines.append(msg)
                lines.append("")


    output = "\n".join(lines)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"\n[OK] Draft shranjen v: {output_file}")
    print(f"[OK] {len(with_email)} emailov pripravljenih za posiljanje")


def main():
    parser = argparse.ArgumentParser(
        description="Scrapa Google Maps, poišče emaile in sestavi draft",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Primeri uporabe:
  python scraper.py "frizerji Ljubljana"
  python scraper.py "zobozdravniki Maribor" --max 30
  python scraper.py "avtomehaniki Celje" --zadeva "Ponudba za oglasevanje" --output drafti/celje.txt
  python scraper.py "kozmetični saloni Kranj" --sporocilo sporocilo.txt
        """,
    )
    parser.add_argument("iskanje", help='Iskalni niz, npr. "frizerji Ljubljana"')
    parser.add_argument("--max", type=int, default=20, dest="max_results",
                        help="Maks. število rezultatov (privzeto: 20)")
    parser.add_argument("--zadeva", default="Poslovna ponudba",
                        help='Zadeva emaila (privzeto: "Poslovna ponudba")')
    parser.add_argument("--sporocilo", default=None,
                        help="Pot do .txt datoteke z besedilom emaila (uporabi {ime} za ime podjetja)")
    parser.add_argument("--output", default=None,
                        help="Ime izhodne datoteke (privzeto: draft_<iskanje>_<datum>.txt)")
    parser.add_argument("--prag", type=int, default=66,
                        help="Maks. ocena strani da jo vključimo (0-100, privzeto: 66). Nižje = samo res slabe strani.")
    args = parser.parse_args()

    # Besedilo emaila
    if args.sporocilo:
        try:
            with open(args.sporocilo, encoding="utf-8") as f:
                sporocilo = f.read().strip()
        except FileNotFoundError:
            print(f"[!] Datoteka sporocilo ne obstaja: {args.sporocilo}")
            sys.exit(1)
    else:
        sporocilo = (
            f"Pozdravljeni,\n\n"
            f"pišem vam v imenu [VAŠE IME/PODJETJE].\n\n"
            f"[VSEBINA SPOROCILA]\n\n"
            f"Lepo vas pozdravljam,\n"
            f"[VAŠE IME]"
        )

    # Izhodna datoteka v mapi Slovenija
    if not args.output:
        os.makedirs("Slovenija", exist_ok=True)
        safe_query = re.sub(r"[^\w\s-]", "", args.iskanje).strip().replace(" ", "_")
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        args.output = os.path.join("Slovenija", f"draft_{safe_query}_{date_str}.txt")

    # 1. Scrapaj Google Maps
    businesses = scrape_google_maps(args.iskanje, args.max_results)

    if not businesses:
        print("[!] Ni najdenih rezultatov.")
        sys.exit(1)

    # 2. Oceni strani in poišči emaile (samo slabe strani)
    businesses = enrich_with_emails(businesses, min_score_threshold=args.prag)

    # 3. Sestavi draft
    generate_email_draft(businesses, args.zadeva, sporocilo, args.output)


if __name__ == "__main__":
    main()
