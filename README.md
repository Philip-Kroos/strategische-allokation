# Strategische Allokation für den Euro-Anleger

Ein Arbeitsmodell für die strategische und taktische Asset-Allokation aus Sicht eines Euro-Anlegers.
Kern ist ein Portfolio-Check: Depot eingeben, Fonds werden in Regionen zerlegt, jede Position erhält
Plus- und Minuspunkte aus Bewertung und Trend, und das Depot wird mit einem Modellportfolio gleichen
Risikos verglichen. Darunter liegen Kapitalmarktannahmen auf zehn Jahre, Portfoliokonstruktion unter
Nebenbedingungen, Vermögensprojektion und Stresstests mit regimeabhängigen Korrelationen.

**Live:** https://philip-kroos.github.io/strategische-allokation/

**Arbeitspapier:** [Bewertung für die Strategie, Trend für die Taktik](docs/arbeitspapier.pdf) (2 Seiten, wird mit jedem Datenupdate neu gesetzt)

## Was das Modell macht

| Baustein | Methode |
|---|---|
| Portfolio-Check | Durchschau auf Fonds, Zusatzrisiko für Einzelaktien und enge Indizes, Modellportfolio mit gleichem Risiko und begrenzten aktiven Abweichungen |
| Signale | Bewertung (CAPE, Realrendite, Spread, realer Goldpreis) geht über die Zehnjahresrenditen in die strategische Quote. Trend (12-Monats-Überrendite je Volatilität) verschiebt die Quote taktisch. Test seit 1993 ohne Blick in die Zukunft: Trend +1,0 % p. a. nach Kosten (t-Wert 4,0), Bewertung als Monatssignal −0,6 % p. a. |
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
web/template.html, app.js, check.js  Oberfläche und Browser-Rechnung (Optimierung, Portfolio-Check, Monte Carlo, Szenarien)
docs/index.html           Fertige Seite für GitHub Pages (Daten eingebettet)
docs/data/model.json      Modelloutput
paper/                    Arbeitspapier: build_paper.py erzeugt paper.html, daraus das PDF
```

## Neu rechnen

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m saa.build     # schreibt docs/data/model.json
python web/render.py                   # schreibt docs/index.html
```

## Monatliche Aktualisierung

Ein GitHub-Workflow (`.github/workflows/monatsupdate.yml`) läuft am 6. und 20. jedes Monats und lässt sich unter Actions auch von Hand starten:

```bash
PYTHONPATH=src python -m saa.fetch     # lädt alle Rohdaten nach data/raw/
PYTHONPATH=src python -m saa.build
python web/render.py
```

Der Workflow committet die neuen Daten, GitHub Pages veröffentlicht die Seite daraufhin neu.
Jede Quelle wird einzeln geladen. Fällt eine aus, bleibt die letzte Datei stehen, `data/raw/fetch_log.json`
hält fest, was geklappt hat. Bundrendite, €STR, Spread und Kurse kommen direkt aus den Daten.
Die French Data Library veröffentlicht mit ein bis zwei Monaten Verzug. Fehlende Monate der Aktienreihen
werden mit Index-ETFs in EUR überbrückt (EXSA, SXR8, IEMM) und später durch die Indexdaten ersetzt.
Bewertungen kommen ebenfalls automatisch: CAPE je Land monatlich von Siblis Research, die
Dividendenrendite aus den monatlichen MSCI-Factsheets (USA, Europa, Schwellenländer), die Länderanteile
für Europa und Schwellenländer aus den iShares-Fonds (IEUR, EEM). Bis zur nächsten Veröffentlichung
schreibt das Modell die Werte mit dem Kursindex fort. Im Test mit US-Daten seit 1960 lag diese
Fortschreibung nach zwölf Monaten im Median 2,6 % neben dem tatsächlichen CAPE. Fällt eine Quelle aus,
gilt der letzte Wert und wird ebenso fortgeschrieben; `config/inputs.json` enthält nur noch Ersatzwerte
und Modellannahmen (fairer CAPE, Wachstum, Rückkäufe, Inflation).

Das Arbeitspapier (`docs/arbeitspapier.pdf`) wird bei jedem Lauf neu gesetzt: `paper/make_pdf.py` liest die
Quoten aus der fertigen Seite, `paper/build_paper.py` schreibt den Text aus den Modellzahlen, auch die
Aussagen zu Regime, Positionierung und Trend.

## Datenquellen

- Kenneth R. French Data Library (Marktrenditen USA, Europa, Schwellenländer)
- Deutsche Bundesbank, Zinsstruktur börsennotierter Bundeswertpapiere, 10 J., Monatsende
- EZB Data Portal (EUR/USD, Euribor, AAA-Zinsstrukturkurve, HVPI)
- FRED (3-Monats-Zins Deutschland, DM/USD vor 1999, VPI, €STR)
- Robert Shiller, S&P Composite (über datasets/s-and-p-500)
- Gold: COMEX-Future GC=F (Monatsende, ab Nov. 2000), davor Weltbank-Monatsdurchschnitte (über datasets/gold-prices)
- Yahoo Finance: Monatskurse iShares Core € Corp Bond (IEAC) sowie ETFs zur Kontrolle der Indexreihen
- Siblis Research (CAPE und Dividendenrendite nach Ländern), MSCI (Index-Factsheets), iShares (Länderanteile)

## Hinweis

Arbeitsmodell zu Forschungs- und Demonstrationszwecken. Keine Anlageberatung.
