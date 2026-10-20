# Date România: behind the numbers

Date România shows where Romanian public money goes. This wiki explains, in plain words,
what happens behind the site: where each number comes from, how it is checked, what is
counted and what is not, and how records from different sources are tied together.

You don't need any technical knowledge to read it. What the site shows, page by page,
is in the [site wiki](https://github.com/CristianPopa96/date-romania-web/wiki).
Instructions for running or changing the code are in this repository's
[README](https://github.com/CristianPopa96/date-romania-api#readme).

## Start here

| If you want to know…                                        | Read                                 |
| ----------------------------------------------------------- | ------------------------------------ |
| The journey of a number, from a public website to the page  | [How data flows](How-Data-Flows)     |
| Which public sources are used, and what each one can't tell | [Data sources](Data-Sources)         |
| Why a total is what it is                                   | [Counting money](Counting-Money)     |
| How a payment, a contract and a place are tied together     | [Linking records](Linking-Records)   |
| What happens when someone reports an error                  | [Reporting an error](Reader-Reports) |

## Why you can trust the numbers

- **Nothing is invented.** Every number comes from a public source: SEAP (the state's
  procurement system), ministries, the national statistics institute, the tax agency.
- **The original is kept.** Everything received from a source is saved exactly as it
  came, before anything is read from it, with a digital fingerprint that would change if
  a single character did. Any figure can be traced back to the file it came from.
- **Mistakes can be undone.** Because the originals are kept, the reading can be redone
  at any time without asking the source again, for example after a reading error is
  fixed.
- **Nothing is dropped quietly.** When a row of a file cannot be read, it is counted and
  the site shows how many there were, per source.
- **One set of counting rules.** What counts as money spent is decided in one place and
  used by every page, so two pages can never give different totals for the same thing.
- **Every link says how sure it is**: sure, probable or possible, with the evidence.
- **Respect for the sources.** Date România asks public websites slowly and politely,
  never in bursts, and says who it is.
- **Open.** The code is open source, and the data can be reused by anyone under CC BY
  4.0, naming the source.

## Where things stand

As of 20.10.2026 a new day is collected each morning. Held:

- **Purchases and contracts from SEAP**: every day from 1 January 2026. That is
  1,808,179 small direct purchases, and 34,445 contract notices holding 246,883
  contracts, 76,281 of them signed in those days.
- **Anghel Saligny programme**: six payment files from the ministry (May to August
  2026), and SEAP's contract lists since 2021 to find the builders' contracts.
- **Places and budgets**: every county, town, commune and village; the 2024 budget of
  every town hall and county council, and their population; the Finance Ministry's list
  of 13,485 public entities; and the tax agency's record of the 87,472 institutions and
  companies held.
