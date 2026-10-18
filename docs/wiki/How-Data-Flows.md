# How data flows

Every number on the site makes the same journey, in five steps.

```
 1. Ask        2. Keep the original     3. Read           4. Tie together       5. Show
 public   ──►  saved untouched,    ──►  turn it into ──►  link records    ──►  the site and
 websites      with a fingerprint       tidy rows         that belong          anyone who
                                                          together             downloads
```

## 1. Ask the public sources

Small programs called **collectors** visit the public websites (SEAP, data.gov.ro, the
tax agency) and ask for one day, or one file, at a time.

- They are polite: they wait between requests, say who they are, and try again later
  when a website is busy.
- If a day fails, the next days still go ahead, and the failed day is tried again.
- A day the source could not give in full is marked as such, so nobody mistakes a
  partial day for a complete one.
- SEAP's lists give at most 2,000 rows at once. A busy day is cut into smaller slices
  until every slice fits, so nothing is cut off.

## 2. Keep the original

Before anything is read, what the source sent is saved **exactly as received**, together
with where it came from and when. Each saved file gets a digital fingerprint: a code that
changes if a single character of the file changes.

This is what lets anyone check a number later: the site can say which file a figure
came from, and that file has not been touched since. The saved copies are not public,
because some contain personal ID numbers that the site hides.

## 3. Read

The saved file is then read and turned into tidy rows: a purchase, a contract, a
payment, a budget line.

- If the way of reading changes (a bug is fixed, for example), everything can be read
  again from the saved originals, without asking the source again.
- Rows that cannot be read are counted, never silently dropped, and the site shows how
  many there were for each source ("Erori").
- Tax IDs (CUI) are checked with their built-in check digit, so a typo does not create a
  new company.
- Personal ID numbers (CNP) of sole traders are hidden before anything is saved as a
  row.
- Public files change format often (the contract lists came in six layouts in six
  years), so each file's real format is recognised from its content, not its label.

Every institution and company goes into one list, by its tax ID, so any name on any page
leads to the same kind of page.

## 4. Tie records together

Records from different sources rarely share a number. Date România ties them only on
stated evidence, and always records how sure the tie is. See
[Linking records](Linking-Records).

## 5. Show

The site, and anyone who asks, gets the figures with their source attached. The counting
rules are applied at this step, the same way for every page. See
[Counting money](Counting-Money).

The only thing anyone can send in is an error report, and it changes nothing until a
person reviews it. See [Reporting an error](Reader-Reports).

## Where the data stops

A full trail of a leu (budget, commitment, contract, payment, subcontractor) cannot be
built from what is published: payments to companies are mostly not published, and the
systems share no common number. Date România shows the ends it can read and marks the
middle as a gap, rather than guessing.
