# European Payments Beat — Source Registry

## Status: draft — to be validated over first 5 days of operation

## Regulatory & official
- FCA publications: https://www.fca.org.uk/news/rss.xml
  - No param filtering supported. Low volume, payments/regulation is core topic — take full feed, filter lightly.
- EBA news: https://www.eba.europa.eu/rss.xml
  - No param filtering supported. Feed covers all of banking regulation — payments content is rare.
  - Spot-checked 10 recent alerts: zero payments-relevant stories. Keyword filter will rarely fire.
  - Consider dropping from automated pipeline; monitor manually or revisit when scraping is in scope.
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

## Notes
Each source should be checked for: update frequency, story relevance ratio,
duplicate overlap with other sources. Document findings here before locking
the config.

Client-side keyword filtering will be needed for most sources. Suggested
terms: "open banking", "PSD2", "PSD3", "PSR", "FCA", "EBA", "instant
payments", "payment regulation", "open finance", "SEPA".
