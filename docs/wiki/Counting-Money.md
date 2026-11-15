# Counting money

A total is only useful if it means the same thing on every page. These are the rules
Date România follows. They are written once and used everywhere, so two pages can never
disagree. All amounts are in **lei without VAT**, as SEAP publishes them.

## Small direct purchases

An institution can buy something small without an auction, straight from SEAP's
catalogue. These are **direct purchases**.

- **Only accepted purchases are counted.** A purchase the supplier or the institution
  refused, or that got no answer, is still listed, but its value was never spent, so it
  is not added up.
- **Values above the legal limit are set apart.** The law (Law 98/2016, art. 7(5))
  allows a direct purchase under **270,120 lei** for goods and services and under
  **900,400 lei** for works. Each purchase is held to the limit of its type, as the
  institution filed it in SEAP; when the type is not known, to the higher one. When SEAP
  shows an accepted purchase above its limit, it is left out of the totals and shown
  next to them. Date România does not call it an error; it is what SEAP publishes, and
  one such value could outweigh a whole day.
- **Some services have no limit.** The social and other specific services listed in
  Annex 2 of the law (health, social services, education, culture, hotels and
  restaurants, legal, security, postal and a few more) are bought by each institution's
  own procedure, with no limit for a direct purchase. They are recognised by their CPV
  code and always counted.

### Purchases just under the limit

The site shows pairs of the same institution and the same company with **at least two**
accepted direct purchases, each worth between 90% of the legal limit of its type and the
limit. Annex 2 services are left out, since they have no limit to be near. A
value close to the limit does not prove a purchase was split to avoid an auction. It is
a fact worth asking for documents about, never an accusation.

## Contracts

A **contract notice** on SEAP announces who won a procedure. One notice can hold several
contracts, and SEAP publishes the notice again each time a contract is added or changed.

- **Contracts are counted by the day they were signed**, not by the day the notice was
  published, because a notice republished today can hold contracts signed years ago.
- **A framework agreement is a ceiling, not spending.** It sets the most that may be
  bought later. The money appears in the contracts signed under it, and only those are
  counted.
- **A withdrawn notice is not counted twice.** When a notice is corrected and
  republished, SEAP gives the new version a new id (the notice number stays the same)
  and withdraws the old one. When both are held, only the newest is counted, and the old
  version's page links to it.
- **A contract won by several companies together is never split.** SEAP gives one value
  for the whole contract and does not say who does how much. A company's page shows
  contracts won alone and contracts won together side by side, never added.
- **The list of contracts is always a little incomplete**: contracts reach SEAP weeks
  after signing. Every total of contracts carries that note.

## Never added together

- **Direct purchases and contracts** are always separate figures, separate lists and
  separate rankings.
- **Figures from different periods** are never added or subtracted. A town hall's budget
  covers all of 2024, its contracts the days held, its Anghel Saligny payments the
  dates of the ministry's files. Each figure names its own period.

## Town hall and county council budgets

The budget of a town hall or county council comes from the Ministry of Development's
yearly file of executed budgets (what really came in and went out by 31 December). The
site sorts the revenue into seven lines that always add up to the total:

1. Subsidies from the state budget
2. The town's share of income tax
3. The town's share of VAT
4. Its own revenue (local taxes and fees)
5. EU funds
6. Money from other public administrations
7. Other revenue

On the spending side it shows **capital spending** (investments: roads, buildings,
networks) and spending by **chapter** (transport, education, and so on).

The Anghel Saligny payments to the town hall are shown as a separate card and never
added to the state subsidies, because they cover a different period.

## Against the official totals

The home page sets the country's budget beside what our data shows. Two rules decide what
it may say:

- **A difference only between figures that measure the same thing over the same period.**
  The budgets of town halls and county councils for 2024 are cash spent in 2024 on both
  sides, so their difference is shown, in lei and percent, with what one side holds that
  the other does not (the official figure also holds the institutions they fund apart).
  The budget law's credits for Anghel Saligny against the ministry's payments is a plan
  against what was paid, so it is shown as a share ("plătit {p} % din credite"). Two
  figures that are different measures never compare, now or later ("Nu se compară"):
  Eurostat's local spending by domain counts what was owed in the year (accrual), our
  budgets what was paid. Anything else does not compare yet ("Nu se compară încă"): PNRR
  and EU projects are paid amounts in the execution, while we hold contracts and
  contracted values. The table lists the comparable checks first, then the different
  measures, then the rest, each group by the largest official figure.
- **Most of the budget never goes through procurement.** Pensions and other social help,
  salaries and interest are about 60 % of what the state spends, and no supplier is ever
  paid for them, so no contract can explain them. The home page shows that part muted,
  and never says what share of the money "we found". Goods and services, investments and
  EU and PNRR projects are the part that can meet a contract; even there the figures are
  not subtracted: the execution is cash paid with VAT in the months it covers, a contract
  is a value signed without VAT, often paid over several years, published in SEAP weeks
  after it was signed.

The planned year comes from the documents that go with the budget law, entered by hand
with the page each figure is printed on (`budget_law.py`); a rectification adds its own
rows, nothing is overwritten. The shares of the spending band are whole percents that
add up to 100.

## The Anghel Saligny contract lists

To follow the programme, Date România also reads SEAP's older quarterly lists of
contracts. They are used **only** to find the builder's contract. They never enter a
total or a ranking: they repeat each contract in every later list and give the full
value once per member of an association, so adding them up would count the same money
many times.
