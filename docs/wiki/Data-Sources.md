# Data sources

Everything on Date România comes from public sources. This page lists each one, what it
tells us, and what it does not.

## Used today

| Source                                                                                                                          | Who publishes it                       | What it tells us                                                                                                                 |
| ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| [SEAP direct purchases](https://e-licitatie.ro/pub/direct-acquisitions/list/1)                                                  | ADR, which runs SEAP                   | Small purchases made without an auction: who bought, from whom, what kind of thing, for how much, and whether it went through    |
| [SEAP award notices](https://e-licitatie.ro/pub/notices/contract-award-notices/list/0/0)                                        | ADR                                    | Who won a public procurement procedure: the contracts, their value, the winners, how they were financed (including EU funds)     |
| [Anghel Saligny payments](https://data.gov.ro/dataset/plati-programul-national-de-investitii-anghel-saligny-pnias-2026-prezent) | Ministry of Development (MDLPA)        | Each payment the ministry made to a town hall for a road, water or sewage project, and the company building it                   |
| SEAP's quarterly contract lists, since 2021                                                                                     | ADR, on data.gov.ro                    | Older contracts, used only to find which contract an Anghel Saligny builder signed with the town hall                            |
| [SIRUTA](https://data.gov.ro/organization/ins)                                                                                  | National Institute of Statistics (INS) | Every county, town, commune and village, with an official code, and which commune each village belongs to                        |
| [List of public entities](https://extranet.anaf.mfinante.gov.ro/anaf/extranet/EXECUTIEBUGETARA)                                 | Finance Ministry                       | Every public institution, where it is, and which institution funds it (a school and its town hall, for example)                  |
| [Local budgets and population](https://data.gov.ro/dataset/politici-fiscale-si-bugetare-locale)                                 | Ministry of Development                | What every town hall and county council received and spent in 2024, and how many people live in each town and commune            |
| [ANAF register](https://www.anaf.ro/anaf/internet/ANAF/servicii_online/servicii_web_anaf)                                       | The tax agency                         | For each institution and company: the town of its office (never the street), its activity, VAT status and whether it is inactive |

## What each source does not tell us

| Source                  | What is missing                                                                                                                                                                                     |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SEAP direct purchases   | Which budget line pays for it. The items bought and the payment and delivery terms are on each purchase's own page, one request each: collected for accepted purchases of 100,000 lei or more only. |
| SEAP award notices      | Which budget line pays for it, and how many offers there were. Contracts appear weeks after signing: half more than 17 days later, one in ten more than 50 days later.                              |
| Anghel Saligny payments | The day of the payment. The town hall is named only by name, without its tax ID. Only files from 27 August 2026 on give the builder's tax ID.                                                       |
| SEAP contract lists     | Used only to follow the programme, never in totals: they repeat each contract in every later list and list an association once per member.                                                          |
| Local budgets           | Only town halls and county councils, only for whole years.                                                                                                                                          |

## The period held

Purchases and contracts from SEAP are held for **every day from 1 January 2026**, and a
new day is collected each morning. From 11 to 18 October 2026 the site was built on a
fixed slice of 40 days (1 September to 10 October 2026); the rest of the year was
collected on 18 to 20 October 2026. The Anghel Saligny trace also looks at contracts
back to 2021, from SEAP's quarterly lists, because the programme pays for contracts
signed since then. The ministry's payment files and SEAP's quarterly lists are checked
for new files on the 1st of every month, and the tax agency's record each morning, for
the institutions and companies that are new.

## Not used yet

| Source                                                | What it would add                                                                                                                                                                               |
| ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Budgets of every other institution (Finance Ministry) | What each school, hospital or ministry spent, month by month. The ministry's website asks for a verification code on every search, so it cannot be read; a request for the whole set is planned |
| Company financial statements (ANAF)                   | A company's turnover, staff and debts, year by year                                                                                                                                             |
| EU funds ministry (MIPE)                              | EU-funded projects, and how much EU money is used                                                                                                                                               |
| TED, the EU's procurement journal                     | Large procedures published at EU level                                                                                                                                                          |
| Payments published voluntarily (Cluj-Napoca, others)  | Named payments to companies                                                                                                                                                                     |
| Office holders (Monitorul Oficial, gov.ro)            | Who led each institution, and when                                                                                                                                                              |

## Why it is allowed

The data is public under Law 544/2001 (access to public information), Law 98/2016
(public procurement) and Law 179/2022 (open data and its reuse). Date România republishes
it under the CC BY 4.0 licence, with the source of every record.

SEAP's website runs on a data service that is not officially documented for the public.
Date România uses it carefully and slowly, and the published bulk files on data.gov.ro are
the fallback.
