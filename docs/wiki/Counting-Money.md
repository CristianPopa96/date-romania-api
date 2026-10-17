# Counting money

All the rules below live in one module, `src/date_romania/money.py`, and are applied in
SQL by every endpoint. They are never restated in a route or a collector.

All amounts are **lei without VAT**, as SEAP publishes them, and are JSON numbers in the
API.

## Direct purchases

| Rule | Why |
| --- | --- |
| Only purchases whose offer was **accepted** (SEAP state 7) are added up | The other states (refused by the supplier or the institution, no answer) carry values that were never spent |
| An accepted purchase published **above 900,400 lei** is left out of totals and reported apart as `above_limit` | 900,400 lei is the legal ceiling for works, the highest a direct purchase may have. One such value can outweigh a whole day. It is what SEAP publishes; it is not called an error. |

The ceiling for goods and services is lower (270,120 lei). Since 16.10.2026 each
purchase stores its contract type, so the per-type ceiling can be applied; it is not yet
applied to `above_limit`, because some services (Annex 2 of the law) have higher ceilings
and are not told apart yet.

### The "just under the ceiling" pattern

`/v1/patterns/near-limit` finds pairs of the same buyer and the same supplier with **at
least two** accepted direct purchases, each between **90% of the ceiling of its contract
type** and the ceiling. It is a fact worth asking documents about, never an accusation:
a value close to the ceiling does not show that a purchase was split.

## Award notices and contracts

| Rule | Why |
| --- | --- |
| Count contracts by `contract_date`, never by the notice's publication day | SEAP republishes a notice whenever a contract is added or changed, so the notices of one day carry contracts signed over several years |
| Totals count **ordinary** (kind 1) and **subsequent** (kind 3) contracts, never **framework agreements** (kind 2) | A framework agreement is a ceiling; the money committed is in its subsequent contracts |
| When a notice is republished under a new id, the contracts of the withdrawn one are left out (`contract_in_force`) | Otherwise the same contract would count twice |
| An **association** has one value; it is never split between members | SEAP gives one value for the whole contract and names no leader |
| Entity pages and rankings count contracts **signed in the period held**, with a note that the list is incomplete | Contracts appear in SEAP weeks after signing |
| A notice's own page shows the notice's own total, whatever the signing dates | It describes the notice, not a period |

On a company: contracts won **alone** and **in association** are two figures, never
added. In the supplier ranking, a contract won in association appears at every member,
with its full value.

## Never added together

Direct purchases and contracts are separate figures, separate lists and separate
ranking tabs. They are different kinds of spending and their periods are counted
differently.

## Programme exports

`export_contract` (SEAP's quarterly exports) serves only the Anghel Saligny trace. It
never enters a total, a ranking or an entity page: it is a second reading of SEAP with
fewer fields, an association is listed once per member with the whole value, and a
contract is repeated in every later export.

## Which days a total covers

Every total is computed over the days held and says so. The API returns the period with
every figure, and `source.documents` says how many stored answers the figure's own rows
were read from.
