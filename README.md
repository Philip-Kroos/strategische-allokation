# Strategische Allokation für den Euro-Anleger

Ein Arbeitsmodell für die strategische Asset-Allokation aus Sicht eines Euro-Anlegers:
Kapitalmarktannahmen auf zehn Jahre, Portfoliokonstruktion unter Nebenbedingungen,
Vermögensprojektion mit Entnahmen und Stresstests mit regimeabhängigen Korrelationen.

**Live:** https://philip-kroos.github.io/strategische-allokation/

## Was das Modell macht

| Baustein | Methode |
|---|---|
| Renditeannahmen Aktien | Mittel aus CAPE-Regression (Shiller-Daten 1881–2013, HAC-Standardfehler, Out-of-sample-Test) und Grinold-Kroner-Bausteinen (Dividende, Nettorückkäufe bzw. Verwässerung, reales Gewinnwachstum, teilweise Bewertungsnormalisierung) |
| Renditeannahmen Anleihen | Startrendite. Empirisch geprüft für Bundesanleihen seit 1972 (R² 0,86) |
| Risiko | Monatsrenditen in EUR 1990–2026, Ledoit-Wolf-Schrumpfung, Stambaugh-Projektion für kürzere Historien |
| Korrelationsregime | Getrennte Kovarianzmatrizen nach Vorzeichen der rollierenden Aktien-Bund-Korrelation |
| Portfolio | Mittelwert-Varianz mit Ober-/Untergrenzen, exakter Active-Set-Löser, Black-Litterman-artiger Anker an einem Referenzportfolio |
| Projektion | Monte-Carlo mit Parameterunsicherheit, inflationsindexierte Entnahmen, real |
| Stresstests | Historische Krisen seit 1994 und bedingte Schocks je Regime |
| Kontrolle | Konstruierte EUR-Reihen gegen investierbare ETFs (Korrelation 0,95 bis 0,99 bei Aktien) |

## Aufbau

```
config/inputs.json        Marktinputs mit Quellen (CAPE, Renditen, Dividenden)
data/raw/                 Rohdaten (FRED, EZB, Bundesbank, Fama-French, Shiller, Gold, ETF-Kurse)
src/saa/                  Python: Renditereihen, Anleihenmathematik, Bewertung, Risiko, Build
web/template.html, app.js Oberfläche und Browser-Rechnung (Optimierung, Monte Carlo, Szenarien)
docs/index.html           Fertige Seite für GitHub Pages (Daten eingebettet)
docs/data/model.json      Modelloutput
```

## Neu rechnen

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m saa.build     # schreibt docs/data/model.json
python web/render.py                   # schreibt docs/index.html
```

Aktualisierung der Marktdaten: Dateien in `data/raw/` ersetzen und die Marktinputs in
`config/inputs.json` (Stand, CAPE, Verfallrenditen) anpassen.

## Datenquellen

- Kenneth R. French Data Library (Marktrenditen USA, Europa, Schwellenländer)
- Deutsche Bundesbank, Zinsstruktur börsennotierter Bundeswertpapiere, 10 J., Monatsende
- EZB Data Portal (EUR/USD, Euribor, AAA-Zinsstrukturkurve, HVPI)
- FRED (3-Monats-Zins Deutschland, DM/USD vor 1999, VPI, €STR)
- Robert Shiller, S&P Composite (über datasets/s-and-p-500)
- Gold: COMEX-Future GC=F (Monatsende, ab Nov. 2000), davor Weltbank-Monatsdurchschnitte (über datasets/gold-prices)
- Yahoo Finance: Monatskurse iShares Core € Corp Bond (IEAC) sowie ETFs zur Kontrolle der Indexreihen
- Siblis Research (CAPE nach Ländern), MSCI (Länderanteile EM)

## Hinweis

Arbeitsmodell zu Forschungs- und Demonstrationszwecken. Keine Anlageberatung.
