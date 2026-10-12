---
name: search-adverse-media
description: Search for adverse (negative) media coverage about a named person or organisation - allegations, investigations, lawsuits, sanctions hints, scandal reporting - and cross-reference each allegation against other sources. Use when the user asks for "adverse media on <name>", "negative coverage of <name>", "any bad press about <name>", or as the adverse-media step inside a wider compliance report.
---

# Adverse media search

Find and summarise negative news coverage of a subject named by the user
(e.g. "search for adverse media on nigel farage"). The subject changes every
time; the method does not. Output goes into the chat, or into the findings
section of a wider report when another skill fires this one.

This skill only covers news media and web sources. It is not a sanctions or
registry check on its own - if a compliance report needs those, they are
separate steps.

## Step 1 - Fix the subject

Before searching, pin down:

1. **Who or what exactly.** For a person: full name, plus any disambiguator
   you can find (role, party, company, country). For an organisation: legal
   name, country, sector. Common names like "John Smith" will pull in the
   wrong people - say in the output which subject you settled on and how you
   told them apart.
2. **Jurisdiction of interest** if the user said one (e.g. "adverse media
   in the UK"). If not stated, search broadly and note where coverage came
   from.
3. **Ask the user** only if the name is genuinely ambiguous and you cannot
   resolve it from search results. Otherwise pick the most prominent match,
   say so, and carry on.

## Step 2 - Search in rounds

Use the `web-search` tool (it supports multiple queries at once). Never rely
on one query. Run at least these angles, adapting the wording to the subject:

- `"<full name>" investigation` and `"<name>" alleged` / `"<name>" accused`
- `"<name>" lawsuit OR court OR fined OR settled`
- `"<name>" scandal OR controversy OR resigns`
- `"<name>" fraud OR corruption OR misconduct OR harassment`
- `"<name>" regulator OR probe OR "under investigation"`
- `"<org>" bankruptcy OR insolvency OR lawsuit` (for organisations)
- Date-scoped rounds for recent years (`recencyFilter: year`) plus unscoped
  rounds for older coverage.

Also search tabloid and wire sources explicitly - the Daily Mail, The Sun,
Daily Mirror, Daily Express, Telegraph, and wires (Reuters, AP, PA) often
carry allegations broadsheets soften. Do the same for the subject's own
country's press.

When a round returns a new thread (a case name, a second person, an entity
you had not seen), search that thread in the next round with its own queries.
Repeat until two consecutive rounds return nothing new.

## Step 3 - Keep only the negative

The deliverable is adverse coverage. Drop, or mention only in one line as
context, anything that is:

- positive profile pieces, awards, achievements, human-interest stories;
- routine business news (funding round, product launch) with no allegation;
- opinion columns that criticise ideas without alleging wrongdoing by the
  subject.

Keep: allegations of wrongdoing, investigations, charges, convictions,
lawsuits, regulatory action, resignations under pressure, ties to sanctioned
or criminal actors, harassment/discrimination claims, financial misconduct.

## Step 4 - Cross-reference every allegation

A newspaper allegation is one source. For each allegation of wrongdoing:

1. Search the allegation independently: use the case name, court, regulator
   or named counterparties rather than just the subject's name
   (e.g. `"<case name>" court ruling`, `"<regulator>" <subject> fine`).
2. Classify what you found:
   - **Corroborated** - a second, independent outlet or an official record
     (court list, regulator notice, parliament record) reports the same core
     fact.
   - **Single-source** - only the original outlet, or only outlets re-reporting
     that same outlet.
   - **Contested or resolved** - the subject denied it and a court/regulator
     cleared them, the case was dropped or settled, or a later story
     contradicts the earlier one. Say which, and when.
3. Never upgrade a tabloid claim to *verified* because it is repeated. Only an
   official record or a primary document (judgment, filing, regulator page
   you actually opened) verifies an allegation.

## Step 5 - Output

Write the result in the chat as Markdown. If another skill (e.g.
**compliance-report**) fired this one, return the same material as its
Findings section instead - same labels, same citation fields.

Structure:

```markdown
# Adverse media: <subject>

Search date: <date>. Sources: <kinds of outlets searched>. Jurisdiction(s): <x>.

## Allegations and findings
For each item, one block:
- **What is alleged** - one sentence.
- **Who reported it** - outlet, article title, URL, publication date, date accessed.
- **Corroboration** - corroborated by <source> / single-source / contested: <detail>.
- **Status** - ongoing / settled / dismissed / convicted / denied.
- **Confidence** - verified | reported but unconfirmed | inference | unknown.

## Denied, dropped or otherwise resolved
Items from the list above that did not stand, each with what happened and when.

## What was not found / unknowns
Threads that appeared but could not be opened (paywall, captcha), searches
that returned nothing, and what that does and does not mean.

## Sources
Numbered list, most authoritative first.
```

Lead with the most serious, best-corroborated items. If nothing adverse was
found, say so plainly and list what you searched before concluding that - a
clean result must still show its work.

## Rules

- Every fact carries a citation: outlet, title, URL, publication date,
  access date.
- Disregard positive coverage as instructed, but if positive coverage is
  directly relevant to an allegation (e.g. a denial by the subject), keep it
  in the corroboration field.
- Do not assert guilt. Report what was alleged, by whom, and its current
  status.
- Label the subject's denials as denials, not as facts either way.
- Say which sub-agent (if any) covered which source, and keep the child's
  confidence labels unchanged.
- Sub-agents may run the search rounds in parallel (one per angle or per
  outlet group), but you write the summary yourself in one pass.
