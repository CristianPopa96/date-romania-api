# Linking records

A contract, a payment and a budget each come from a different source, and they rarely
share a common number. To show the road of the money, Date România has to tie them
together. It does so only on evidence it can state, and **every tie says how sure it
is**.

## How sure a tie is

| Level        | What it rests on                                                                                                                                |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Sure**     | The same tax ID (CUI) on both records, or both named in the same published record                                                               |
| **Probable** | Evidence put together by Date România that makes the tie likely, for example the builder's tax ID plus the town hall's name in the right county |
| **Possible** | Weaker evidence, for example a name that other records also carry                                                                               |

The site shows the level next to every tie, and headline figures never count a tie
weaker than they say.

## Institutions and companies

Every purchase and contract on SEAP names the buyer and the seller by tax ID. So an
institution's page and a company's page are tied **surely** to everything they bought
and sold.

## Anghel Saligny: from payment to contract

The Anghel Saligny payment files are the most detailed payment data Romania publishes:
they name the town hall, the project and, in recent files, the tax ID of the company
building it. But they never name the SEAP contract. So the tie is made like this:

1. The payment names the **builder** by tax ID and the **town hall** by name.
2. Date România looks, in SEAP's contract lists since 2021, for the **works contracts**
   that builder won from a buyer with that town hall's name.
3. The tie is **probable** when SEAP puts that buyer in the same county, or when no other
   buyer anywhere carries that name. It is **possible** when other buyers carry the same
   name. A buyer in another county is never tied.
4. No tie is ever **sure**, because the payment does not name the contract.

Each project ends in one of four states:

| On the site                        | Meaning                                                                           |
| ---------------------------------- | --------------------------------------------------------------------------------- |
| "Probabil un singur contract"      | Exactly one contract fits: the chain from the ministry to the builder is complete |
| "Mai multe contracte posibile"     | Several contracts fit; all are shown and none is picked                           |
| "Niciun contract găsit"            | No contract found; the chain stops at the builder                                 |
| "Constructor numit doar cu numele" | The file names the builder without a tax ID, so no search is made                 |

Only the first state counts as tied in the headline figures. Files before 27 August
2026 name builders without a tax ID; inside a project, such a payment goes with the
payments that name the same builder with one.

**Why "no contract found" happens.** Possible reasons, not checked one by one: the
contract was signed by an association of communes or by the county council; it was
published before 2021; the works were bought through a direct purchase; or the town
hall's name is written differently in SEAP.

## Places

Everything is tied to a place through SIRUTA, the official list of every county, town,
commune and village.

| Tie                                                | How it is made                                                                                         | Held (18.10.2026)                     |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------- |
| An institution or company → its town or commune    | The place the Finance Ministry's list gives for it; otherwise the town of its office at the tax agency | 49,523 of 49,525                      |
| An institution → the institution that funds it     | The Finance Ministry's list                                                                            | 8,135 institutions                    |
| A town or county → its town hall or county council | The public entity nobody funds whose name is the place's ("COMUNA ALBAC", "JUDETUL ALBA")              | 3,174 towns and communes, 41 counties |
| An Anghel Saligny payment → the place paid         | The town hall's name in its county                                                                     | all 3,821                             |

Names are matched carefully: the county, the kind of place (commune, town, municipality,
sector) and the name must all agree. Old spellings are forgiven only in the most common
cases ("Tirgu Mures" for "Târgu Mureș"), never a near miss. When two places could fit,
none is picked.

The budget of a town hall is tied to the town it governs, and through it to the town
hall's own page. No budget line is ever tied to a specific contract: the budget files do
not say which contract a line pays.

## Planned

- **EU projects**: the project codes written in some contract titles would tie contracts
  to EU-funded projects (probable).
- **Payments published voluntarily** by some institutions would tie to contracts by
  name, amount and period (possible).
