#!/usr/bin/env python3
"""
Scraper za celo Slovenijo — poišče podjetja po vseh večjih mestih.
Vključi samo tiste z emailom IN slabo/brez spletne strani.

Uporaba:
  python slovenija.py "frizerstvo"
  python slovenija.py "avtomehanik" --prag 50 --max 15
  python slovenija.py "zobozdravnik" --zadeva "Ponudba" --sporocilo sporocilo_primer.txt
"""

import subprocess
import sys
import os
import argparse
import functools
from datetime import datetime

print = functools.partial(print, flush=True)

MESTA = [
    "Ljubljana", "Maribor", "Celje", "Kranj", "Koper",
    "Velenje", "Novo Mesto", "Ptuj", "Nova Gorica", "Murska Sobota",
    "Slovenj Gradec", "Škofja Loka", "Domžale", "Kamnik", "Jesenice",
    "Postojna", "Izola", "Piran", "Ajdovščina", "Žalec",
    "Litija", "Ravne na Koroškem", "Kočevje", "Trebnje", "Metlika",
    "Črnomelj", "Lendava", "Ormož", "Ljutomer", "Brežice",
    "Krško", "Sevnica", "Laško", "Radovljica", "Tržič",
    "Gornja Radgona", "Ilirska Bistrica", "Sežana", "Idrija", "Tolmin",
]


def main():
    parser = argparse.ArgumentParser(
        description="Scrapa Google Maps za podano dejavnost po vseh večjih mestih v Sloveniji",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Primeri:
  python slovenija.py "frizerstvo"
  python slovenija.py "avtomehanik" --prag 50
  python slovenija.py "računovodski servis" --max 15 --zadeva "Ponudba za spletno stran"
        """,
    )
    parser.add_argument("dejavnost", help='Dejavnost, npr. "frizerstvo"')
    parser.add_argument("--max", type=int, default=20,
                        help="Maks. rezultatov na mesto (privzeto: 20)")
    parser.add_argument("--prag", type=int, default=66,
                        help="Maks. ocena spletne strani da jo vključimo (privzeto: 66)")
    parser.add_argument("--zadeva", default="Poslovna ponudba",
                        help='Zadeva emaila')
    parser.add_argument("--sporocilo", default=None,
                        help="Pot do .txt z besedilom emaila")
    parser.add_argument("--mesta", default=None,
                        help='Po meri: "Ljubljana,Maribor,Celje"')
    args = parser.parse_args()

    mesta = MESTA
    if args.mesta:
        mesta = [m.strip() for m in args.mesta.split(",") if m.strip()]

    os.makedirs("Slovenija", exist_ok=True)

    print("=" * 60)
    print(f"Dejavnost: {args.dejavnost}")
    print(f"Mest:      {len(mesta)}")
    print(f"Max/mesto: {args.max}")
    print(f"Prag:      {args.prag}/100 (slabše = vključeno)")
    print("=" * 60)
    print()

    uspesno = 0
    neuspesno = []
    skupaj_datotek = []

    for i, mesto in enumerate(mesta, 1):
        iskanje = f"{args.dejavnost} {mesto}"
        print(f"[{i}/{len(mesta)}] {iskanje}")
        print("-" * 40)

        cmd = [
            sys.executable, "scraper.py", iskanje,
            "--max", str(args.max),
            "--prag", str(args.prag),
            "--zadeva", args.zadeva,
        ]
        if args.sporocilo:
            cmd += ["--sporocilo", args.sporocilo]

        try:
            result = subprocess.run(
                cmd,
                capture_output=False,
                text=True,
                timeout=600,
            )
            if result.returncode == 0:
                uspesno += 1
                # Poišči ustvarjeno datoteko
                if os.path.isdir("Slovenija"):
                    files = sorted(
                        [f for f in os.listdir("Slovenija") if args.dejavnost.split()[0].lower() in f.lower()],
                        key=lambda f: os.path.getmtime(os.path.join("Slovenija", f)),
                        reverse=True,
                    )
                    if files:
                        skupaj_datotek.append(os.path.join("Slovenija", files[0]))
            else:
                neuspesno.append(mesto)
        except subprocess.TimeoutExpired:
            print(f"  [!] Timeout za {mesto}, preskakujem...")
            neuspesno.append(mesto)
        except Exception as e:
            print(f"  [!] Napaka za {mesto}: {e}")
            neuspesno.append(mesto)

        print()

    # Povzetek
    print("=" * 60)
    print(f"KONEC — {uspesno}/{len(mesta)} mest uspesno")
    if neuspesno:
        print(f"Neuspesno: {', '.join(neuspesno)}")
    print(f"Drafti shranjeni v: Slovenija/")

    # Izpis vseh datotek
    if os.path.isdir("Slovenija"):
        files = os.listdir("Slovenija")
        print(f"Skupaj datotek: {len(files)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
