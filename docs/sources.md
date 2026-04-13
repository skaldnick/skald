# European Payments Beat — Source Registry

## Status: active — first run completed March 26, 2025. Observations below.

## Regulatory & official
- FCA publications: https://www.fca.org.uk/news/rss.xml
  - No param filtering supported. Low volume, payments/regulation is core topic — take full feed, filter lightly.
- EBA news: https://www.eba.europa.eu/rss.xml
  - **Dropped.** Feed summaries are HTML boilerplate only — alert body content is not in the feed.
    Keyword filtering cannot work without content. Scraping required to be useful; out of scope.
  - Payments topic page (scraping required): https://www.eba.europa.eu/publications-and-media/press-releases?text=&topic=219&date=
- ECB press: https://www.ecb.europa.eu/rss/press.html
  - No topic-filtered feed found (/rss/paym.html 404s). Take full feed, filter client-side.
- gov.uk (HM Treasury / FCA): https://www.gov.uk/search/news-and-communications.atom?keywords=%22open+banking%22
  - Phrase-quoted keyword param works. Returns relevant low-frequency results (Smart Data, PSR, FCA policy).
  - Organisation scoping (e.g. `&organisations[]=financial-conduct-authority`) returns empty — do not use.

## Standards bodies & industry
- Open Banking Limited: https://www.openbanking.org.uk/feed/
  - Active and on-topic. UK open banking standards, JROC updates, future entity design.
- European Payments Council: https://www.europeanpaymentscouncil.eu — no feed accessible (403). Monitor manually.
- Payment Systems Regulator: no RSS feed (email subscription only). PSR policy announcements surface via gov.uk "open banking" phrase feed.

## Trade press
- Finextra (payments channel): https://www.finextra.com/rss/channel.aspx?channel=payments
  - Channel param changes feed label but content is still broad. Filter client-side by keyword.
- PYMNTS (open banking tag): https://www.pymnts.com/tag/open-banking/feed/
  - Active and current. Good signal quality.
- PYMNTS (FCA tag): https://www.pymnts.com/tag/fca/feed/
  - Active, very current (Feb 2026). UK regulatory focus.
- PYMNTS (payments regulation tag): https://www.pymnts.com/tag/payments-regulation/feed/
  - Active (Mar 2025). Mixed UK/US/EU jurisdiction — filter client-side for EU/UK relevance.
- PYMNTS (open finance tag): https://www.pymnts.com/tag/open-finance/feed/
  - Low volume — last item Jul 2025. Keep as supplementary.
- PYMNTS (psd2/eba tags): abandoned — last items 2022–2023. Do not use.
- The Paypers: https://thepaypers.com/news — no feed found, scraping required. Excluded for now.
- Payments Dive: https://www.paymentsdive.com/feeds/news/
  - No filtering support (?q= param ignored). Take full feed, filter client-side.

## Google Alert Feeds
- open banking: https://www.google.com/alerts/feeds/10307432568024476394/7105842768072246404
- open finance: https://www.google.com/alerts/feeds/10307432568024476394/6734328040985392802
- PSD3: https://www.google.com/alerts/feeds/10307432568024476394/16372416596677282693
- "instant payments" Europe: https://www.google.com/alerts/feeds/10307432568024476394/13500249349444643736
- "payment systems regulator": https://www.google.com/alerts/feeds/10307432568024476394/2934695885739138194
- "variable recurring payments": https://www.google.com/alerts/feeds/10307432568024476394/14717764527932905523
- Note: "payment regulation" excluded — too few results to be useful.

## To evaluate
- Payments Cards & Mobile
- AltFi

## Exclusions
- Paid/paywalled sources
- Sources requiring scraping (legal/reliability risk)
- Social media feeds — Twitter/X API now $100/month minimum, not viable
- Fintech Futures — RSS blocked (403); Google News publication feed also blocked (consent wall + feed unavailable). Relevant stories will surface via Google Alerts.
- EBA RSS — payments content too rare to be useful; topic page requires scraping

## First-run observations (March 26, 2025)
Feed volumes per source: FCA 20, EBA 10, ECB 15, HM Treasury 20,
Google Alert — open banking 20, open finance 8, PSD3 0, instant payments 0,
payment systems regulator 1, variable recurring payments 11, Finextra 46,
PYMNTS 10. Total: 161 entries; recent (last 3 days): to be confirmed.

Google Alerts: mixed quality on first run. Some results are blog posts and
commentary rather than primary news. Source-side filtering of alert scope
(excluding blogs, low-authority domains) is preferable to client-side
filtering. PSD3 and instant payments alerts returned zero results — may need
keyword tuning. "Payment regulation" alert excluded early as too sparse.

Finextra dominates volume at 46 entries. Broad coverage; client-side keyword
filtering will be needed to surface payments-relevant items.

Story selection quality: first run selected 5 strong stories (FCA open
finance priorities, PSD3 readiness, ECB digital euro, T+1 testing plan,
Solaris pivot). One issue: model drafted a PSD3 story citing a February EBA
survey as if it were current — news recognition check in story prompt now
addresses this.

## Notes
Each source should be checked for: update frequency, story relevance ratio,
duplicate overlap with other sources.

Client-side keyword filtering will be needed for broad sources (Finextra,
ECB, EBA). Suggested terms: "open banking", "PSD2", "PSD3", "PSR", "FCA",
"EBA", "instant payments", "payment regulation", "open finance", "SEPA".
